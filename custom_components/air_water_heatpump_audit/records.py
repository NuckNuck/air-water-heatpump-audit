"""Ereignisse und Personen im Haushalt: Listen in den Optionen des Eintrags statt Untereinträgen.

HA zeigt Untereinträge flach auf der Integrationsseite und gruppiert sie nicht. Ereignisse werden beim Optimieren
schnell viele; deshalb verwaltet sie die Zeitstrahl-Karte (WebSocket-Befehle unten), Personen das Menü „Haushalt“ im
Options Flow. Jeder Eintrag trägt eine `id`. Eine Änderung schreibt die Optionen neu; der Update-Listener lädt den
Eintrag dann neu und rechnet neu.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from .const import (CONF_EVENT_KIND, CONF_EVENT_NOTE, CONF_EVENT_TIME, CONF_EVENTS, CONF_HOUSEHOLD, DOMAIN,
                    EVENT_KIND_LABELS, EVENT_KINDS, RECORD_ID, SUBENTRY_EVENT, SUBENTRY_PERSON)

# Version der Optionen, ab der Ereignisse und Personen Listen sind (ConfigFlow.MINOR_VERSION)
RECORDS_MINOR_VERSION = 2


def records(entry: ConfigEntry, key: str) -> list[dict[str, Any]]:
    """Ereignisse (`events`) oder Personen (`household`) des Eintrags; Kopien, nach dem Speichern unverändert."""
    return [dict(r) for r in entry.options.get(key) or []]


def with_id(record: dict[str, Any]) -> dict[str, Any]:
    return {RECORD_ID: record.get(RECORD_ID) or ulid_now()} | {k: v for k, v in record.items() if k != RECORD_ID}


@callback
def save_records(hass: HomeAssistant, entry: ConfigEntry, key: str, items: list[dict[str, Any]]) -> None:
    hass.config_entries.async_update_entry(entry, options=dict(entry.options) | {key: items})


def event_title(data: dict[str, Any], lang: str) -> str:
    """Kurztitel eines Ereignisses für Listen, z. B. „25.10.2026 19:31 · Pumpe verstellt“."""
    labels = EVENT_KIND_LABELS[lang]
    when = dt_util.parse_datetime(str(data.get(CONF_EVENT_TIME)))
    stamp = when.strftime("%d.%m.%Y %H:%M") if when else str(data.get(CONF_EVENT_TIME))
    kind = data.get(CONF_EVENT_KIND, "other")
    return f"{stamp} · {labels.get(kind, kind)}"


def subentries_to_records(entry: ConfigEntry) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Ereignis- und Personen-Untereinträge als Listen und die IDs der Untereinträge, die damit wegfallen."""
    moved: dict[str, list[dict[str, Any]]] = {CONF_EVENTS: records(entry, CONF_EVENTS),
                                              CONF_HOUSEHOLD: records(entry, CONF_HOUSEHOLD)}
    gone = []
    for sub in entry.subentries.values():
        key = {SUBENTRY_EVENT: CONF_EVENTS, SUBENTRY_PERSON: CONF_HOUSEHOLD}.get(sub.subentry_type)
        if key:
            moved[key].append({RECORD_ID: sub.subentry_id} | dict(sub.data))
            gone.append(sub.subentry_id)
    return moved, gone


async def async_migrate_records(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Untereinträge „event“ und „person“ in die Optionen übernehmen (bis 0.18.0b6 Untereinträge)."""
    moved, gone = subentries_to_records(entry)
    for subentry_id in gone:
        hass.config_entries.async_remove_subentry(entry, subentry_id)
    hass.config_entries.async_update_entry(entry, options=dict(entry.options) | moved,
                                           minor_version=RECORDS_MINOR_VERSION)


# WebSocket-Befehle der Zeitstrahl-Karte: Ereignis anlegen/ändern und löschen (nur Admins)
EVENT_SCHEMA = vol.Schema({vol.Optional(RECORD_ID): str,
                           vol.Required(CONF_EVENT_TIME): str,
                           vol.Required(CONF_EVENT_KIND): vol.In(EVENT_KINDS),
                           vol.Optional(CONF_EVENT_NOTE, default=""): str})


def _entry(hass: HomeAssistant, connection, msg) -> ConfigEntry | None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Eintrag nicht gefunden")
        return None
    return entry


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/event/save", vol.Required("entry_id"): str,
                                  vol.Required("event"): EVENT_SCHEMA})
@callback
def ws_save_event(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Ereignis anlegen (ohne `id`) oder ersetzen (mit `id`). Die Zeit muss lesbar sein, z. B. 2026-10-25 14:30:00."""
    if (entry := _entry(hass, connection, msg)) is None:
        return
    event = with_id(msg["event"])
    if dt_util.parse_datetime(event[CONF_EVENT_TIME]) is None:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, "Zeitpunkt nicht lesbar")
        return
    events = records(entry, CONF_EVENTS)
    if msg["event"].get(RECORD_ID) and not any(e.get(RECORD_ID) == event[RECORD_ID] for e in events):
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Ereignis nicht gefunden")
        return
    events = [e for e in events if e.get(RECORD_ID) != event[RECORD_ID]] + [event]
    events.sort(key=lambda e: str(e.get(CONF_EVENT_TIME)))
    save_records(hass, entry, CONF_EVENTS, events)
    connection.send_result(msg["id"], {RECORD_ID: event[RECORD_ID]})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/event/delete", vol.Required("entry_id"): str,
                                  vol.Required("event_id"): str})
@callback
def ws_delete_event(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if (entry := _entry(hass, connection, msg)) is None:
        return
    events = records(entry, CONF_EVENTS)
    rest = [e for e in events if e.get(RECORD_ID) != msg["event_id"]]
    if len(rest) == len(events):
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Ereignis nicht gefunden")
        return
    save_records(hass, entry, CONF_EVENTS, rest)
    connection.send_result(msg["id"], {})


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_save_event)
    websocket_api.async_register_command(hass, ws_delete_event)
