"""Contract-Tests: Laden der Statistik-Tage aus der Langzeitstatistik von HA (Spezifikation 1.11).

Vertrag: Tageswerte in Ortszeit; Strom und Steuerungswärme als Änderung je Tag in kWh, Außentemperatur als
Tagesmittel (Wetterdienst bevorzugt). Ohne Statistik für Strom oder Steuerungswärme keine Statistik-Tage (None).
"""

from datetime import timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.air_water_heatpump_audit.audit_core import days
from custom_components.air_water_heatpump_audit.recorder_source import load_statistics

METER, HEAT = "sensor.wp_meter", "sensor.wp_heat_today"
OUTDOOR_REF, OUTDOOR_UNIT = "sensor.weather_temp", "sensor.wp_outdoor"
ROLES = {"electricity_meter": METER, "controller_heat_today": HEAT, "outdoor_temp_reference": OUTDOOR_REF,
         "outdoor_temp": OUTDOOR_UNIT}
METER_KWH_PER_H, HEAT_KWH_PER_H = 1.0, 3.0
OUTDOOR_REF_C, OUTDOOR_UNIT_C = 4.0, 9.0
HOURS = 48


def _sum_meta(eid: str) -> dict:
    return {"mean_type": StatisticMeanType.NONE, "has_sum": True, "name": None, "source": "recorder",
            "statistic_id": eid, "unit_class": "energy", "unit_of_measurement": "kWh"}


def _mean_meta(eid: str) -> dict:
    return {"mean_type": StatisticMeanType.ARITHMETIC, "has_sum": False, "name": None, "source": "recorder",
            "statistic_id": eid, "unit_class": "temperature", "unit_of_measurement": "°C"}


async def _import(hass: HomeAssistant, start, ids: tuple[str, ...]) -> None:
    hours = [start + timedelta(hours=h) for h in range(HOURS)]
    if METER in ids:
        async_import_statistics(hass, _sum_meta(METER), [
            {"start": t, "state": (h + 1) * METER_KWH_PER_H, "sum": (h + 1) * METER_KWH_PER_H}
            for h, t in enumerate(hours)])
    if HEAT in ids:
        async_import_statistics(hass, _sum_meta(HEAT), [
            {"start": t, "state": (h + 1) * HEAT_KWH_PER_H, "sum": (h + 1) * HEAT_KWH_PER_H}
            for h, t in enumerate(hours)])
    for eid, value in ((OUTDOOR_REF, OUTDOOR_REF_C), (OUTDOOR_UNIT, OUTDOOR_UNIT_C)):
        if eid in ids:
            async_import_statistics(hass, _mean_meta(eid), [
                {"start": t, "mean": value, "min": value, "max": value} for t in hours])
    await async_wait_recording_done(hass)


async def _load(hass: HomeAssistant, start, roles=ROLES):
    tz = str(dt_util.get_default_time_zone())
    return await get_instance(hass).async_add_executor_job(
        load_statistics, hass, roles, start, start + timedelta(hours=HOURS), lambda t: days.label(t, tz))


def _two_days_ago():
    return dt_util.start_of_local_day() - timedelta(days=2)


async def test_daily_change_and_mean_per_local_day(hass: HomeAssistant):
    start = _two_days_ago()
    await _import(hass, start, (METER, HEAT, OUTDOOR_REF, OUTDOOR_UNIT))
    out = await _load(hass, start)
    first = days.label(start.timestamp(), str(dt_util.get_default_time_zone()))
    # Der erste Tag hat keinen Vortageswert; ab dem zweiten zählen volle 24 h
    later = [d for d in out["electricity_kwh"] if d != first]
    assert later
    for day in later:
        assert out["electricity_kwh"][day] == 24 * METER_KWH_PER_H
        assert out["controller_heat_kwh"][day] == 24 * HEAT_KWH_PER_H
    assert set(out["outdoor_mean"].values()) == {OUTDOOR_REF_C}  # Wetterdienst vor Außenfühler


async def test_outdoor_unit_used_without_weather_service(hass: HomeAssistant):
    start = _two_days_ago()
    await _import(hass, start, (METER, HEAT, OUTDOOR_UNIT))
    roles = {k: v for k, v in ROLES.items() if k != "outdoor_temp_reference"}
    out = await _load(hass, start, roles)
    assert set(out["outdoor_mean"].values()) == {OUTDOOR_UNIT_C}


async def test_without_controller_heat_statistics_no_statistic_days(hass: HomeAssistant):
    start = _two_days_ago()
    await _import(hass, start, (METER, OUTDOOR_REF))
    assert await _load(hass, start) is None


async def test_without_controller_heat_role_no_statistic_days(hass: HomeAssistant):
    start = _two_days_ago()
    await _import(hass, start, (METER, HEAT))
    roles = {"electricity_meter": METER}
    assert await _load(hass, start, roles) is None


async def _requested_start(hass: HomeAssistant, data_since: str | None):
    """Startet einen Lauf der Integration und liefert, ab wann sie die Langzeitstatistik anfragt."""
    from unittest.mock import patch

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.air_water_heatpump_audit.const import DEFAULT_OPTIONS, DOMAIN

    calls = []

    def fake_load(hass_, roles, start, end, label):
        calls.append((start, end))
        return None

    entry = MockConfigEntry(domain=DOMAIN, data=ROLES,
                            subentries_data=[{"subentry_type": "audit", "data": {"audit": "efficiency"},
                                              "title": "efficiency", "unique_id": "efficiency"}],
                            options=DEFAULT_OPTIONS | {"data_since": data_since})
    entry.add_to_hass(hass)
    with patch("custom_components.air_water_heatpump_audit.coordinator.load_statistics", fake_load):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert calls
    return calls[-1]


async def test_statistics_requested_at_most_400_days_back(hass: HomeAssistant):
    start, end = await _requested_start(hass, None)
    assert end - start <= timedelta(days=400)
    assert end - start >= timedelta(days=399)


async def test_statistics_not_requested_before_data_since(hass: HomeAssistant):
    since = dt_util.start_of_local_day() - timedelta(days=50)
    start, _ = await _requested_start(hass, since.strftime("%Y-%m-%d %H:%M:%S"))
    assert start >= since
