"""Luft-Wasser-Wärmepumpen-Audit: prüft mit belegten Schwellen, ob eine Wärmepumpe sauber läuft.

Liest nur aus InfluxDB oder dem Recorder und schreibt nur eigene Ergebnis-Sensoren; an Geräten wird nichts geändert.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CARD_URL, DOMAIN
from .coordinator import AirWaterAuditConfigEntry, AirWaterAuditCoordinator, timeline_store

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Lovelace-Karte aus dem Integrationsverzeichnis ausliefern.

    Eingebunden wird sie als Lovelace-Ressource (Modul). add_extra_js_url geht nicht: Das Skript liefe vor dem
    Scoped-Registry-Polyfill des Frontends, die Karte landete in der alten Registry und Lovelace fände sie nicht.
    """
    card = Path(__file__).parent / "frontend" / "air-water-heatpump-audit-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card), False)])
    hass.async_create_task(_async_register_card(hass))
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Karte als Lovelace-Ressource eintragen, damit niemand das von Hand tun muss (Erweiterter Modus, Ressourcen).

    Die Version im Pfad (`?v=`) folgt dem Manifest; nach einem Update lädt der Browser so die neue Karte. Im
    YAML-Modus von Lovelace bleibt es beim Eintrag von Hand.
    """
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    data = hass.data.get(LOVELACE_DATA)
    resources = getattr(data, "resources", None)
    if not isinstance(resources, ResourceStorageCollection):
        return
    version = (await async_get_integration(hass, DOMAIN)).version
    url = f"{CARD_URL}?v={version}"
    await resources.async_get_info()  # lädt die Sammlung aus dem Speicher
    for item in resources.async_items():
        if item["url"].split("?")[0] == CARD_URL:
            if item["url"] != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return
    await resources.async_create_item({"res_type": "module", "url": url})
    _LOGGER.info("Lovelace-Ressource %s eingetragen", url)


async def async_setup_entry(hass: HomeAssistant, entry: AirWaterAuditConfigEntry) -> bool:
    coordinator = AirWaterAuditCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Erste Rechnung erst nach dem HA-Start, damit die Recorder-Abfrage den Start nicht bremst.
    async def _first_refresh(_hass: HomeAssistant) -> None:
        await coordinator.async_refresh()

    entry.async_on_unload(async_at_started(hass, _first_refresh))
    # Stammdaten, Audits oder Ereignisse geändert → neu laden und neu rechnen
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: AirWaterAuditConfigEntry) -> None:
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AirWaterAuditConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: AirWaterAuditConfigEntry) -> None:
    """Gespeicherte Tageswerte des Zeitstrahls mit dem Eintrag entfernen."""
    await timeline_store(hass, entry.entry_id).async_remove()
