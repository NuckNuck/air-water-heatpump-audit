"""WebSocket-Abo für den Fortschritt eines Laufs (Spezifikation 8.1): Die Karten zeigen damit „Wird aktualisiert …“."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .coordinator import SIGNAL_PROGRESS


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/progress/subscribe",
                                  vol.Optional("entry_id"): str})
@callback
def ws_subscribe_progress(hass: HomeAssistant, connection: websocket_api.ActiveConnection,
                          msg: dict[str, Any]) -> None:
    """Sofort der Stand je geladenem Eintrag, danach jede Änderung; ohne `entry_id` alle Einträge."""
    wanted = msg.get("entry_id")
    if wanted is not None:
        entry = hass.config_entries.async_get_entry(wanted)
        if entry is None or entry.domain != DOMAIN:
            connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Eintrag nicht gefunden")
            return

    @callback
    def forward(entry_id: str, progress: dict[str, Any]) -> None:
        if wanted is None or entry_id == wanted:
            connection.send_message(websocket_api.event_message(msg["id"], progress))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_PROGRESS, forward)
    connection.send_result(msg["id"])
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        if wanted is None or entry.entry_id == wanted:
            connection.send_message(websocket_api.event_message(msg["id"], entry.runtime_data.progress()))


@callback
def async_register_progress(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_subscribe_progress)
