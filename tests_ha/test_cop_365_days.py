"""Contract-Tests zu Spezifikation 4.3: Sensor „Arbeitszahl der letzten 365 Tage“ (Issue #33)."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.air_water_heatpump_audit.const import DEFAULT_OPTIONS, DOMAIN

from test_integration import ALL_AUDITS, AUDIT_SUBENTRY, MAHTANAR

SENSOR = "sensor.air_water_heatpump_audit_cop_365_days"


def _stored_day(days_ago: int, heat: float, electricity: float) -> dict:
    label = (dt_util.now().date() - timedelta(days=days_ago)).isoformat()
    return {"day": label, "start": 0, "end": 0, "source": "statistics",
            "efficiency": {"value": None, "verdict": "not_assessable", "cop": heat / electricity,
                           "cop_raw": heat / electricity, "heat_kwh": heat, "electricity_kwh": electricity}}


async def _setup(hass: HomeAssistant, hass_storage, days: list[dict], audits=ALL_AUDITS) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=audits, data=MAHTANAR,
                            options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00"})
    key = f"{DOMAIN}.timeline.{entry.entry_id}"
    hass_storage[key] = {"version": 1, "key": key, "data": {"days": days}}
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_stored_days_give_ratio_of_sums_with_attributes(hass: HomeAssistant, hass_storage):
    days = [_stored_day(20, 30.0, 10.0), _stored_day(1, 10.0, 10.0)]

    await _setup(hass, hass_storage, days)

    state = hass.states.get(SENSOR)
    assert float(state.state) == 2.0
    assert state.attributes["state_class"] == "measurement" and "unit_of_measurement" not in state.attributes
    assert state.attributes["days"] == 2 and state.attributes["complete"] is False
    assert (state.attributes["first_day"], state.attributes["last_day"]) == (days[0]["day"], days[1]["day"])
    assert (state.attributes["heat_kwh"], state.attributes["electricity_kwh"]) == (40.0, 20.0)


async def test_without_efficiency_audit_unavailable(hass: HomeAssistant, hass_storage):
    await _setup(hass, hass_storage, [_stored_day(1, 30.0, 10.0)], audits=[AUDIT_SUBENTRY("capacity")])

    assert hass.states.get(SENSOR).state == "unavailable"


async def test_without_usable_day_unavailable(hass: HomeAssistant, hass_storage):
    await _setup(hass, hass_storage, [_stored_day(400, 30.0, 10.0)])

    assert hass.states.get(SENSOR).state == "unavailable"
