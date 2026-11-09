"""Coordinator: liest stündlich die Zeitreihen (InfluxDB oder Recorder) und rechnet alle Audits neu."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import influx_source
from .audit_core import timeline
from .audit_core.actions import CONTROL_ROLES
from .audit_core import heating_prices
from .audit_core.audits import REGISTRY
from .audit_core.runner import ROLE_KEYS, roles_for, run_audits
from .const import (CONF_AUDIT, CONF_IMPORT_TIMELINE_FROM, LEGACY_DOMAIN, SUBENTRY_AUDIT)
from .const import (CONF_COMPARE_HEATING_SYSTEMS, PRICE_ATTR_AS_OF, PRICE_ATTR_SOURCE, PRICE_ATTR_SOURCE_KIND,
                    PRICE_ATTR_SYSTEM, PRICE_ROLE_PREFIX, PRICE_ATTR_INCLUDES_FIXED, PRICE_ATTR_BASE_FEE)
from .const import (CONF_BOOSTER_HEATER_2_KW, CONF_BOOSTER_HEATER_KW, CONF_DATA_SINCE, CONF_DATA_SOURCE,
                    CONF_EVENT_KIND, CONF_EVENT_NOTE, CONF_EVENT_TIME, CONF_IMMERSION_HEATER_KW, CONF_WINDOW_DAYS,
                    DEFAULT_OPTIONS, DOMAIN, MASTER_KEYS, SOURCE_INFLUXDB, SOURCE_RECORDER, UPDATE_INTERVAL)
from .const import CONF_EVENTS, CONF_HOUSEHOLD, RECORD_ID, language
from .records import event_title, records
from .recorder_source import load_series

_LOGGER = logging.getLogger(__name__)

type AirWaterAuditConfigEntry = ConfigEntry[AirWaterAuditCoordinator]

TIMELINE_STORE_VERSION = 1
ROLE_AUDIT_ORDER = [a.audit_id for a in REGISTRY]
COST_AUDIT = "cost"


def timeline_store(hass: HomeAssistant, entry_id: str) -> Store:
    """Tageswerte des Zeitstrahls; sie bleiben, auch wenn Recorder oder InfluxDB die Rohdaten nicht mehr haben."""
    return Store(hass, TIMELINE_STORE_VERSION, f"{DOMAIN}.timeline.{entry_id}")


# Für D1: Ab wann reichen die Rohdaten in InfluxDB zurück? Erste vorhandene Rolle dieser Liste.
DEPTH_ROLES = ("compressor_running", "flow_temp", "heartbeat")


class AirWaterAuditCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Ein Lauf = alle Audits über das Fenster [max(jetzt − Fenster, Daten ab), jetzt]."""

    config_entry: AirWaterAuditConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AirWaterAuditConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self._influx_since: float | None = None  # ältester Wert in InfluxDB, einmal je Laufzeit ermittelt
        self._store = timeline_store(hass, entry.entry_id)
        self._timeline_days: list[dict] | None = None  # None = noch nicht aus dem Speicher geladen
        self._warned_prices: set[str] = set()  # Preis-Sensoren, zu denen schon eine Warnung im Log steht

    def _option(self, key: str):
        return self.config_entry.options.get(key, DEFAULT_OPTIONS[key])

    def audits(self) -> list[str]:
        """Zugeschaltete Audits (Untereinträge) in Registry-Reihenfolge."""
        chosen = {sub.data.get(CONF_AUDIT) for sub in self.config_entry.subentries.values()
                  if sub.subentry_type == SUBENTRY_AUDIT}
        return [a for a in ROLE_AUDIT_ORDER if a in chosen]

    def _roles(self) -> dict[str, str]:
        """Nur Rollen, die die zugeschalteten Audits lesen; weniger Last für Recorder und InfluxDB."""
        needed = roles_for(self.audits())
        return {r: e for r, e in self.config_entry.data.items() if r in ROLE_KEYS and r in needed and e}

    def _controls(self) -> dict[str, dict]:
        """Heutiger Zustand der zugeordneten Stellgrößen; daraus schlagen die Aktionen Werte vor."""
        out = {}
        for role in CONTROL_ROLES:
            eid = self.config_entry.data.get(role)
            st = self.hass.states.get(eid) if eid else None
            if st is None:
                continue
            a = st.attributes
            out[role] = {"entity_id": eid, "state": st.state, "min": a.get("min"), "max": a.get("max"),
                         "step": a.get("step"), "options": a.get("options"), "unit": a.get("unit_of_measurement")}
        return out

    def _price_refs(self) -> list[dict] | None:
        """Preis-Sensoren anderer Heizsysteme (Attribut `heating_system`); None = Vergleich aus oder kein Kosten-Audit.

        Sensoren mit unbekanntem System oder unpassender Einheit fallen weg (mit Warnung im Log)."""
        if not self._option(CONF_COMPARE_HEATING_SYSTEMS) or COST_AUDIT not in self.audits():
            return None
        out = []
        for st in self.hass.states.async_all("sensor"):
            system = st.attributes.get(PRICE_ATTR_SYSTEM)
            if system is None:
                continue
            ref = {"id": st.entity_id, "system": system, "unit": st.attributes.get("unit_of_measurement"),
                   "name": st.attributes.get("friendly_name"), "source": st.attributes.get(PRICE_ATTR_SOURCE),
                   "source_kind": st.attributes.get(PRICE_ATTR_SOURCE_KIND),
                   "as_of": st.attributes.get(PRICE_ATTR_AS_OF),
                   "includes_fixed_charges": st.attributes.get(PRICE_ATTR_INCLUDES_FIXED),
                   "annual_base_fee": st.attributes.get(PRICE_ATTR_BASE_FEE)}
            if heating_prices.usable(ref):
                out.append(ref)
            elif st.entity_id not in self._warned_prices:
                self._warned_prices.add(st.entity_id)
                _LOGGER.warning("Preis-Sensor %s übergangen: System %r oder Einheit %r wird nicht unterstützt",
                                st.entity_id, system, ref["unit"])
        return sorted(out, key=lambda r: (list(heating_prices.SYSTEMS).index(r["system"]), r["id"]))

    def window(self, max_days: float | None = None) -> tuple[float, float]:
        end = dt_util.utcnow()
        days = float(self._option(CONF_WINDOW_DAYS))
        if max_days is not None:
            days = min(days, max_days)
        start = end - timedelta(days=days)
        raw_since = self._option(CONF_DATA_SINCE)
        since = dt_util.parse_datetime(str(raw_since)) if raw_since else None
        if since is not None:
            since = dt_util.as_utc(since if since.tzinfo else since.replace(tzinfo=dt_util.get_default_time_zone()))
            start = max(start, since)
        return start.timestamp(), end.timestamp()

    def _load_recorder(self, roles: dict[str, str], start: float, end: float) -> dict:
        return load_series(self.hass, roles, dt_util.utc_from_timestamp(start), dt_util.utc_from_timestamp(end))

    def _compute(self, series: dict, start: float, end: float, keep_days: float, long_term_days: float | None,
                 controls: dict[str, dict], price_refs: list[dict] | None = None) -> dict[str, Any]:
        heater_kw = {role: self._option(key) for role, key in (("immersion_heater", CONF_IMMERSION_HEATER_KW),
                                                                ("booster_heater", CONF_BOOSTER_HEATER_KW),
                                                                ("booster_heater_2", CONF_BOOSTER_HEATER_2_KW))}
        master = {k: self._option(k) for k in MASTER_KEYS}
        master["household"] = [{k: v for k, v in p.items() if k != RECORD_ID}
                               for p in records(self.config_entry, CONF_HOUSEHOLD)]
        return run_audits(series, start, end, recorder_keep_days=keep_days, long_term_days=long_term_days,
                          heater_kw=heater_kw, master=master, events=self._events(), controls=controls,
                          tz=str(dt_util.get_default_time_zone()), audits=self.audits(),
                          price_refs=None if price_refs is None else [
                              r | {"series": series.get(PRICE_ROLE_PREFIX + r["id"], [])} for r in price_refs])

    def _events(self) -> list[dict[str, Any]]:
        """Ereignisse aus den Optionen (records.py); Zeit ohne Zone gilt als lokale Zeit."""
        out = []
        lang = language(self.hass)
        for event in records(self.config_entry, CONF_EVENTS):
            when = dt_util.parse_datetime(str(event.get(CONF_EVENT_TIME)))
            if when is None:
                continue
            when = when if when.tzinfo else when.replace(tzinfo=dt_util.get_default_time_zone())
            out.append({"time": when.timestamp(), "kind": event.get(CONF_EVENT_KIND, "other"),
                        "note": event.get(CONF_EVENT_NOTE, ""), "title": event_title(event, lang),
                        "id": event.get(RECORD_ID), "local_time": event.get(CONF_EVENT_TIME)})
        return out

    def _influx_connection(self) -> tuple[influx_source.InfluxConnection | None, str | None]:
        """Verbindung oder Grund, warum InfluxDB nicht genutzt wird (None = bewusst Recorder)."""
        wanted = self._option(CONF_DATA_SOURCE)
        if wanted == SOURCE_RECORDER:
            return None, None
        conn = influx_source.find_connection(self.hass)
        if conn is None:
            return None, (None if wanted == "auto" else "Keine InfluxDB-2-Integration eingerichtet.")
        return conn, None

    async def _influx_depth_days(self, conn: influx_source.InfluxConnection, roles: dict[str, str],
                                 end: float) -> float | None:
        if self._influx_since is None:
            eid = next((roles[r] for r in DEPTH_ROLES if r in roles), None)
            if eid is not None:
                self._influx_since = await influx_source.first_timestamp(self.hass, conn, eid)
        return None if self._influx_since is None else (end - self._influx_since) / 86400

    async def _async_update_data(self) -> dict[str, Any]:
        price_refs = self._price_refs()
        # Preis-Sensoren laden wie Rollen; der Präfix hält sie getrennt von den Rollen-Keys
        roles = self._roles() | {PRICE_ROLE_PREFIX + r["id"]: r["id"] for r in price_refs or []}
        recorder = get_instance(self.hass)
        conn, note = self._influx_connection()
        series: dict = {}
        long_term_days = None
        from_recorder = list(roles)
        t0 = time.monotonic()
        start, end = self.window(None if conn else recorder.keep_days)
        if conn is not None:
            try:
                series = await influx_source.load_series(self.hass, conn, roles, start, end)
                long_term_days = await self._influx_depth_days(conn, roles, end)
                # Rollen, die InfluxDB nicht hat (z. B. per include/exclude ausgefiltert), kommen aus dem Recorder.
                from_recorder = [r for r in roles if not series.get(r)]
            except influx_source.InfluxError as err:
                _LOGGER.warning("InfluxDB nicht nutzbar, rechne mit dem Recorder: %s", err)
                note = f"InfluxDB nicht erreichbar ({err}), Recorder genutzt."
                conn, series = None, {}
                start, end = self.window(recorder.keep_days)
                from_recorder = list(roles)
        if from_recorder:
            # Datenbankzugriff im Executor des Recorders, das Rechnen im allgemeinen Executor.
            series |= await recorder.async_add_executor_job(
                self._load_recorder, {r: roles[r] for r in from_recorder}, start, end)
        t1 = time.monotonic()
        report = await self.hass.async_add_executor_job(self._compute, series, start, end, recorder.keep_days,
                                                        long_term_days, self._controls(), price_refs)
        report["runtime_s"] = {"load": round(t1 - t0, 2), "audits": round(time.monotonic() - t1, 2)}
        report["timeline"]["days"] = await self._merge_timeline(report["timeline"]["days"])
        report["events"] = sorted(self._events(), key=lambda e: e["time"])
        report["points"] = {r: len(s) for r, s in series.items()}
        report["source"] = {"used": SOURCE_INFLUXDB if conn else SOURCE_RECORDER,
                            "roles_from_recorder": from_recorder if conn else [], "note": note}
        _LOGGER.debug("Audit gerechnet: %s, Quelle %s", report["runtime_s"], report["source"])
        return report

    async def _merge_timeline(self, fresh: list[dict]) -> list[dict]:
        if self._timeline_days is None:
            stored = await self._store.async_load() or {}
            if not stored and (old := self.config_entry.data.get(CONF_IMPORT_TIMELINE_FROM)):
                # Übernahme aus „WP-Audit“: dessen gespeicherte Tageswerte einmalig lesen
                stored = await Store(self.hass, TIMELINE_STORE_VERSION, f"{LEGACY_DOMAIN}.timeline.{old}").async_load() or {}
            self._timeline_days = stored.get("days", [])
        self._timeline_days = timeline.merge(self._timeline_days, fresh)
        await self._store.async_save({"days": self._timeline_days})
        return self._timeline_days
