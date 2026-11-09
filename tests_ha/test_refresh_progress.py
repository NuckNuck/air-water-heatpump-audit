"""Contract-Tests zu Spezifikation 8.1: Aktualisieren ohne Neuladen und Fortschritt per WebSocket (Issue #31)."""

import threading
from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.air_water_heatpump_audit.const import DEFAULT_OPTIONS, DOMAIN

from test_integration import ALL_AUDITS, MAHTANAR

AUDIT_SENSOR = "sensor.air_water_heatpump_audit_capacity"
STEPS = {"load", "statistics", "compute", "store"}
EVENT = {"time": "2026-10-25 14:30:00", "kind": "valves", "note": "Bad auf 4"}
OTHER_EVENT = {"time": "2026-10-26 09:00:00", "kind": "valves", "note": "Bad auf 3"}


def _hours_ago(hours: int) -> str:
    return (dt_util.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:00")


async def _loaded_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=dict(MAHTANAR), subentries_data=ALL_AUDITS,
                            options=DEFAULT_OPTIONS | {"data_since": "2000-01-01 00:00:00"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _subscribe(ws, entry_id: str | None = None) -> int:
    await ws.send_json_auto_id({"type": f"{DOMAIN}/progress/subscribe"} | ({"entry_id": entry_id} if entry_id else {}))
    reply = await ws.receive_json()
    assert reply["success"], reply
    return reply["id"]


async def _save_event(ws, entry, event: dict) -> None:
    await ws.send_json_auto_id({"type": f"{DOMAIN}/event/save", "entry_id": entry.entry_id, "event": event})
    while (reply := await ws.receive_json())["type"] != "result":
        pass  # Fortschritt eines Abos auf derselben Verbindung
    assert reply["success"], reply


async def test_options_changed_results_stay_available_and_are_recomputed(hass: HomeAssistant, hass_ws_client):
    hass.states.async_set("binary_sensor.heatpump_compressor", "on")
    await async_wait_recording_done(hass)
    entry = await _loaded_entry(hass)
    recent = {**EVENT, "time": _hours_ago(1)}
    seen = []
    hass.bus.async_listen(EVENT_STATE_CHANGED, lambda e: seen.append(e.data["new_state"].state)
                          if e.data["entity_id"] == AUDIT_SENSOR and e.data["new_state"] else None)

    await _save_event(await hass_ws_client(hass), entry, recent)
    await hass.async_block_till_done()

    assert STATE_UNAVAILABLE not in seen
    section = hass.states.get(AUDIT_SENSOR).attributes["section"]  # neu gerechnet, ohne eigenen Anstoß
    assert section["kind"] == "valves" and section["note"] == "Bad auf 4"


async def test_roles_changed_entry_is_reloaded(hass: HomeAssistant):
    entry = await _loaded_entry(hass)
    before = entry.runtime_data

    hass.config_entries.async_update_entry(entry, data=entry.data | {"controller_heat_today": "sensor.heat_today"})
    await hass.async_block_till_done()

    assert entry.runtime_data is not before


async def test_options_changed_during_run_cause_exactly_one_more_run(hass: HomeAssistant, hass_ws_client):
    hass.states.async_set("binary_sensor.heatpump_compressor", "on")
    await async_wait_recording_done(hass)
    entry = await _loaded_entry(hass)
    first = {**EVENT, "time": _hours_ago(2)}
    second = {**OTHER_EVENT, "time": _hours_ago(1)}
    ws = await hass_ws_client(hass)
    sub = await _subscribe(ws, entry.entry_id)
    await ws.receive_json()  # Stand nach dem Abo
    release = threading.Event()
    from custom_components.air_water_heatpump_audit import coordinator as module
    real = module.load_series

    def slow_load(*args):  # Datenquelle hält den Lauf an, bis beide Änderungen da sind
        release.wait(5)
        return real(*args)

    with patch.object(module, "load_series", slow_load):
        await _save_event(ws, entry, first)
        await _save_event(ws, entry, second)
        release.set()
        await hass.async_block_till_done()

    starts = set()
    while True:
        msg = await ws.receive_json()
        assert msg["id"] == sub
        if msg["event"]["running"]:
            starts.add(msg["event"]["started"])
        elif msg["event"]["step"] is None and msg["event"]["done"] == msg["event"]["total"] and len(starts) >= 2:
            break
    assert len(starts) == 2
    assert [e["note"] for e in entry.options["events"]] == ["Bad auf 4", "Bad auf 3"]
    assert hass.states.get(AUDIT_SENSOR).attributes["section"]["note"] == "Bad auf 3"


async def test_progress_subscription_sends_current_state_first(hass: HomeAssistant, hass_ws_client):
    entry = await _loaded_entry(hass)
    ws = await hass_ws_client(hass)

    sub = await _subscribe(ws, entry.entry_id)

    msg = await ws.receive_json()
    assert msg["id"] == sub and msg["type"] == "event"
    state = msg["event"]
    assert state["entry_id"] == entry.entry_id and state["running"] is False and state["step"] is None
    assert state["done"] == state["total"] >= 1
    assert state["started"] is not None and state["last_duration_s"] >= 0


async def test_progress_during_run_reports_steps_within_bounds(hass: HomeAssistant, hass_ws_client):
    entry = await _loaded_entry(hass)
    ws = await hass_ws_client(hass)
    await _subscribe(ws, entry.entry_id)
    await ws.receive_json()

    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    messages = []
    while not messages or messages[-1]["running"]:
        messages.append((await ws.receive_json())["event"])
    running = [m for m in messages if m["running"]]
    assert running and {m["step"] for m in running} <= STEPS
    assert all(0 <= m["done"] <= m["total"] and m["total"] == running[0]["total"] for m in running)
    assert [m["done"] for m in running] == sorted(m["done"] for m in running)
    assert messages[-1]["done"] == messages[-1]["total"] and messages[-1]["step"] is None


async def test_progress_with_unknown_entry_is_rejected(hass: HomeAssistant, hass_ws_client):
    await _loaded_entry(hass)
    ws = await hass_ws_client(hass)

    await ws.send_json_auto_id({"type": f"{DOMAIN}/progress/subscribe", "entry_id": "missing"})

    assert (await ws.receive_json())["error"]["code"] == "not_found"


async def test_progress_without_entry_covers_all_entries(hass: HomeAssistant, hass_ws_client):
    first = await _loaded_entry(hass)
    second = await _loaded_entry(hass)
    ws = await hass_ws_client(hass)

    await _subscribe(ws)

    reported = {(await ws.receive_json())["event"]["entry_id"] for _ in range(2)}
    assert reported == {first.entry_id, second.entry_id}


async def test_last_duration_survives_reload(hass: HomeAssistant, hass_ws_client):
    entry = await _loaded_entry(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    with patch("custom_components.air_water_heatpump_audit.async_at_started", lambda hass, cb: lambda: None):
        assert await hass.config_entries.async_setup(entry.entry_id)  # ohne ersten Lauf
        await hass.async_block_till_done()
        ws = await hass_ws_client(hass)
        await _subscribe(ws, entry.entry_id)
        state = (await ws.receive_json())["event"]

    assert state["running"] is False and state["started"] is None
    assert state["last_duration_s"] is not None
