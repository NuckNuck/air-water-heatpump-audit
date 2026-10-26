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
from .audit_core.runner import ROLE_KEYS, run_audits
from .const import (CONF_BOOSTER_HEATER_2_KW, CONF_BOOSTER_HEATER_KW, CONF_DATA_SINCE, CONF_DATA_SOURCE,
                    CONF_EVENT_KIND, CONF_EVENT_NOTE, CONF_EVENT_TIME, CONF_IMMERSION_HEATER_KW, CONF_WINDOW_DAYS,
                    DEFAULT_OPTIONS, DOMAIN, MASTER_KEYS, SOURCE_INFLUXDB, SOURCE_RECORDER, SUBENTRY_EVENT,
                    UPDATE_INTERVAL)
from .recorder_source import load_series

_LOGGER = logging.getLogger(__name__)

type AirWaterAuditConfigEntry = ConfigEntry[AirWaterAuditCoordinator]

TIMELINE_STORE_VERSION = 1


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

    def _option(self, key: str):
        return self.config_entry.options.get(key, DEFAULT_OPTIONS[key])

    def _roles(self) -> dict[str, str]:
        return {r: e for r, e in self.config_entry.data.items() if r in ROLE_KEYS and e}

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
                 controls: dict[str, dict]) -> dict[str, Any]:
        heater_kw = {role: self._option(key) for role, key in (("immersion_heater", CONF_IMMERSION_HEATER_KW),
                                                                ("booster_heater", CONF_BOOSTER_HEATER_KW),
                                                                ("booster_heater_2", CONF_BOOSTER_HEATER_2_KW))}
        master = {k: self._option(k) for k in MASTER_KEYS}
        return run_audits(series, start, end, recorder_keep_days=keep_days, long_term_days=long_term_days,
                          heater_kw=heater_kw, master=master, events=self._events(), controls=controls,
                          tz=str(dt_util.get_default_time_zone()))

    def _events(self) -> list[dict[str, Any]]:
        """Ereignisse aus den Untereinträgen; Zeit ohne Zone gilt als lokale Zeit."""
        out = []
        for sub in self.config_entry.subentries.values():
            if sub.subentry_type != SUBENTRY_EVENT:
                continue
            when = dt_util.parse_datetime(str(sub.data.get(CONF_EVENT_TIME)))
            if when is None:
                continue
            when = when if when.tzinfo else when.replace(tzinfo=dt_util.get_default_time_zone())
            out.append({"time": when.timestamp(), "kind": sub.data.get(CONF_EVENT_KIND, "other"),
                        "note": sub.data.get(CONF_EVENT_NOTE, ""), "title": sub.title, "subentry_id": sub.subentry_id})
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
        roles = self._roles()
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
                                                        long_term_days, self._controls())
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
            self._timeline_days = stored.get("days", [])
        self._timeline_days = timeline.merge(self._timeline_days, fresh)
        await self._store.async_save({"days": self._timeline_days})
        return self._timeline_days
