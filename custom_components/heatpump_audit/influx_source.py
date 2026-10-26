"""Adapter InfluxDB 2: Zeitreihen je Rolle aus dem Bucket, den die HA-Integration „InfluxDB“ beschreibt.

Nutzt die Verbindung (URL, Token, Organisation, Bucket) des vorhandenen InfluxDB-Eintrags, damit der Besitzer nichts
doppelt einrichten muss. Schema der HA-Integration: Tag `entity_id` ohne Domain, Tag `domain`, Feld `value` (Zahl),
`state` (Text) und je Attribut ein Feld. Gleiche Semantik wie der Recorder-Adapter: Zahlen als float, Text nur für
Text-Rollen, inklusive des zu `start` gültigen Werts. InfluxQL (InfluxDB 1.x) wird nicht unterstützt.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .audit_core.series import Series
from .const import TEXT_ROLES, WEATHER_ATTRIBUTE

INFLUXDB_DOMAIN = "influxdb"
LOOKBACK_S = 30 * 86400  # so weit vor `start` wird der dann gültige Wert gesucht (Sollwerte ändern sich selten)
TIMEOUT = aiohttp.ClientTimeout(total=120)


class InfluxError(Exception):
    """InfluxDB nicht erreichbar oder Abfrage abgelehnt."""


@dataclass(frozen=True)
class InfluxConnection:
    url: str
    token: str
    org: str
    bucket: str
    verify_ssl: bool = True


def connection_from_entry(entry: ConfigEntry) -> InfluxConnection | None:
    """Verbindung aus dem Eintrag der HA-Integration InfluxDB; None bei InfluxDB 1.x oder fehlenden Angaben."""
    d = entry.data
    if str(d.get("api_version")) != "2" or not all(d.get(k) for k in ("url", "token", "organization", "bucket")):
        return None
    return InfluxConnection(d["url"].rstrip("/"), d["token"], d["organization"], d["bucket"], d.get("verify_ssl", True))


def find_connection(hass: HomeAssistant) -> InfluxConnection | None:
    for entry in hass.config_entries.async_entries(INFLUXDB_DOMAIN):
        if (conn := connection_from_entry(entry)) is not None:
            return conn
    return None


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def field_for(role: str, entity_id: str) -> str:
    if role in TEXT_ROLES:
        return "state"
    return WEATHER_ATTRIBUTE if entity_id.startswith("weather.") else "value"


def build_query(bucket: str, field: str, entity_ids: list[str], start: float, end: float) -> str:
    """Flux: je Entität der letzte Wert vor `start` plus alle Werte in [start, end), als eine Tabelle nach Zeit."""
    match = " or ".join(f"(r.domain == {_quote(e.split('.', 1)[0])} and r.entity_id == {_quote(e.split('.', 1)[1])})"
                        for e in sorted(entity_ids))
    flt = f"|> filter(fn: (r) => r._field == {_quote(field)} and ({match}))"
    src = f"from(bucket: {_quote(bucket)})"
    return (f"before = {src} |> range(start: {_iso(start - LOOKBACK_S)}, stop: {_iso(start)}) {flt} |> last()\n"
            f"inside = {src} |> range(start: {_iso(start)}, stop: {_iso(end)}) {flt}\n"
            'union(tables: [before, inside]) |> keep(columns: ["_time", "_value", "domain", "entity_id"])'
            ' |> group() |> sort(columns: ["_time"])')


def parse_csv(text: str, roles: dict[str, str]) -> dict[str, Series]:
    """CSV-Antwort → Zeitreihe je Rolle. Pro Entität gilt vor `start` nur der jüngste Wert (last() je Measurement)."""
    by_entity: dict[str, list[str]] = defaultdict(list)
    for role, eid in roles.items():
        by_entity[eid].append(role)
    out: dict[str, Series] = {role: [] for role in roles}
    for row in csv.DictReader(io.StringIO(text)):
        t_raw = row.get("_time")
        if not t_raw or t_raw == "_time":  # Leerzeilen und wiederholte Kopfzeilen
            continue
        eid = f"{row.get('domain')}.{row.get('entity_id')}"
        t = datetime.fromisoformat(t_raw.replace("Z", "+00:00")).timestamp()
        for role in by_entity.get(eid, []):
            raw = row["_value"]
            if role in TEXT_ROLES:
                out[role].append((t, raw))
                continue
            try:
                out[role].append((t, float(raw)))
            except ValueError:
                continue
    return out


def trim_before(series: Series, start: float) -> Series:
    """Nur der jüngste Wert vor `start` bleibt (Entitäten mit mehreren Measurements liefern mehrere)."""
    before = [p for p in series if p[0] < start]
    return before[-1:] + [p for p in series if p[0] >= start]


async def _query(hass: HomeAssistant, conn: InfluxConnection, flux: str) -> str:
    session = async_get_clientsession(hass, verify_ssl=conn.verify_ssl)
    try:
        async with session.post(f"{conn.url}/api/v2/query", params={"org": conn.org}, data=flux.encode(),
                                headers={"Authorization": f"Token {conn.token}", "Content-Type": "application/vnd.flux",
                                         "Accept": "application/csv"}, timeout=TIMEOUT) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise InfluxError(f"HTTP {resp.status}: {body[:200]}")
            return body
    except (aiohttp.ClientError, TimeoutError) as err:
        raise InfluxError(str(err) or type(err).__name__) from err


async def load_series(hass: HomeAssistant, conn: InfluxConnection, roles: dict[str, str],
                      start: float, end: float) -> dict[str, Series]:
    """Eine Abfrage je Feld (Zahlen und Text lassen sich in Flux nicht in einer Tabelle mischen)."""
    by_field: dict[str, dict[str, str]] = defaultdict(dict)
    for role, eid in roles.items():
        by_field[field_for(role, eid)][role] = eid
    out: dict[str, Series] = {}
    for field, group in by_field.items():
        text = await _query(hass, conn, build_query(conn.bucket, field, list(set(group.values())), start, end))
        parsed = await hass.async_add_executor_job(parse_csv, text, group)
        out |= {role: trim_before(s, start) for role, s in parsed.items()}
    return out


async def first_timestamp(hass: HomeAssistant, conn: InfluxConnection, entity_id: str) -> float | None:
    """Ältester Wert einer Entität im Bucket (für D1: wie weit reichen die Rohdaten zurück)."""
    domain, object_id = entity_id.split(".", 1)
    flux = (f"from(bucket: {_quote(conn.bucket)}) |> range(start: 0)"
            f" |> filter(fn: (r) => r.domain == {_quote(domain)} and r.entity_id == {_quote(object_id)})"
            ' |> first() |> keep(columns: ["_time"]) |> group() |> min(column: "_time")')
    for row in csv.DictReader(io.StringIO(await _query(hass, conn, flux))):
        if row.get("_time") and row["_time"] != "_time":
            return datetime.fromisoformat(row["_time"].replace("Z", "+00:00")).timestamp()
    return None
