"""Contract-Tests zu Spezifikation 8.2: Rohdaten zwischen Läufen behalten, nur Neues nachladen (Issue #35).

Datenquelle ist der Recorder; beobachtet wird der Port `load_series` (welcher Zeitraum geladen wird) und das
Ergebnis eines Laufs.
"""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.air_water_heatpump_audit import coordinator as module
from custom_components.air_water_heatpump_audit.const import DEFAULT_OPTIONS, DOMAIN

from test_integration import ALL_AUDITS, AUDIT_SUBENTRY, MAHTANAR

OVERLAP = timedelta(minutes=5)
WINDOW_START = "2000-01-01 00:00:00"


async def _entry(hass: HomeAssistant, audits=ALL_AUDITS) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, subentries_data=audits, data=MAHTANAR,
                            options=DEFAULT_OPTIONS | {"data_since": WINDOW_START})
    entry.add_to_hass(hass)
    with patch("custom_components.air_water_heatpump_audit.async_at_started", lambda hass, cb: lambda: None):
        assert await hass.config_entries.async_setup(entry.entry_id)  # Läufe stößt der Test selbst an
    await hass.async_block_till_done()
    return entry


async def _record(hass: HomeAssistant, states: dict[str, str]) -> None:
    for eid, state in states.items():
        hass.states.async_set(eid, state)
    await async_wait_recording_done(hass)


async def _run_and_capture_starts(hass: HomeAssistant, entry) -> list:
    """Ein Lauf; liefert die Beginnzeiten, ab denen die Datenquelle gefragt wurde."""
    starts = []
    real = module.load_series

    def spy(hass_, roles, start, end):
        starts.append(start)
        return real(hass_, roles, start, end)

    with patch.object(module, "load_series", spy):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    assert entry.runtime_data.last_update_success, entry.runtime_data.last_exception
    return starts


async def test_second_run_loads_from_five_minutes_before_last_end(hass: HomeAssistant, freezer):
    await _record(hass, {"binary_sensor.heatpump_compressor": "on"})
    entry = await _entry(hass)
    first_end = dt_util.utcnow()
    await _run_and_capture_starts(hass, entry)
    freezer.tick(timedelta(hours=1))

    starts = await _run_and_capture_starts(hass, entry)

    assert starts and all(s == first_end - OVERLAP for s in starts)


async def test_first_run_loads_whole_window(hass: HomeAssistant):
    entry = await _entry(hass)

    starts = await _run_and_capture_starts(hass, entry)

    window_start = entry.runtime_data.data["period"]["start"]  # Fensterbeginn dieses Laufs
    assert starts and all(s.timestamp() == window_start for s in starts)


async def test_run_with_reloaded_data_matches_run_with_full_load(hass: HomeAssistant, freezer):
    await _record(hass, {"binary_sensor.heatpump_compressor": "on", "sensor.heatpump_feed_temp": "33.5",
                         "sensor.heatpump_return_temp": "29.0", "sensor.heatpump_esp_uptime": "100"})
    cached = await _entry(hass)
    await _run_and_capture_starts(hass, cached)
    freezer.tick(timedelta(minutes=30))
    await _record(hass, {"binary_sensor.heatpump_compressor": "off", "sensor.heatpump_feed_temp": "35.0",
                         "sensor.heatpump_esp_uptime": "1900"})

    await _run_and_capture_starts(hass, cached)
    fresh = await _entry(hass)
    await _run_and_capture_starts(hass, fresh)

    a, b = cached.runtime_data.data, fresh.runtime_data.data
    assert a["points"] == b["points"]
    assert a["audits"] == b["audits"]


async def test_full_load_again_after_24_hours(hass: HomeAssistant, freezer):
    entry = await _entry(hass)
    await _run_and_capture_starts(hass, entry)
    freezer.tick(timedelta(hours=24, minutes=1))

    starts = await _run_and_capture_starts(hass, entry)

    window_start = entry.runtime_data.data["period"]["start"]  # Fensterbeginn dieses Laufs
    assert starts and all(s.timestamp() == window_start for s in starts)


async def test_full_load_when_price_sensor_appears(hass: HomeAssistant, freezer):
    entry = await _entry(hass, ALL_AUDITS + [AUDIT_SUBENTRY("cost")])  # Preis-Sensoren liest nur das Kosten-Audit
    await _run_and_capture_starts(hass, entry)
    freezer.tick(timedelta(hours=1))
    hass.states.async_set("sensor.gas_price", "0.12", {"heating_system": "natural_gas", "unit_of_measurement": "€/kWh"})

    starts = await _run_and_capture_starts(hass, entry)

    window_start = entry.runtime_data.data["period"]["start"]  # Fensterbeginn dieses Laufs
    assert starts and all(s.timestamp() == window_start for s in starts)
