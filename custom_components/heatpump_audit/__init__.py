"""WP-Audit: prüft mit belegten Schwellen, ob eine Wärmepumpe sauber läuft (Spezifikation docs/heatpump_audit_spec.md).

Liest nur aus InfluxDB oder dem Recorder und schreibt nur eigene Ergebnis-Sensoren; an Geräten wird nichts geändert.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .const import CARD_URL, DOMAIN
from .coordinator import HeatpumpAuditConfigEntry, HeatpumpAuditCoordinator, timeline_store

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Lovelace-Karte aus dem Integrationsverzeichnis ausliefern.

    Eingebunden wird sie als Lovelace-Ressource (Modul). add_extra_js_url geht nicht: Das Skript liefe vor dem
    Scoped-Registry-Polyfill des Frontends, die Karte landete in der alten Registry und Lovelace fände sie nicht.
    """
    card = Path(__file__).parent / "frontend" / "heatpump-audit-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card), False)])
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HeatpumpAuditConfigEntry) -> bool:
    coordinator = HeatpumpAuditCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Erste Rechnung erst nach dem HA-Start, damit die Recorder-Abfrage den Start nicht bremst.
    async def _first_refresh(_hass: HomeAssistant) -> None:
        await coordinator.async_refresh()

    entry.async_on_unload(async_at_started(hass, _first_refresh))
    # Stammdaten oder Ereignisse geändert → neu laden und neu rechnen
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: HeatpumpAuditConfigEntry) -> None:
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HeatpumpAuditConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: HeatpumpAuditConfigEntry) -> None:
    """Gespeicherte Tageswerte des Zeitstrahls mit dem Eintrag entfernen."""
    await timeline_store(hass, entry.entry_id).async_remove()
