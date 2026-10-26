"""Adapter InfluxDB 2 (Schema der HA-Integration: Tag entity_id ohne Domain, Tag domain, Felder value/state)."""

from __future__ import annotations

import csv
import io
import os
import urllib.request
from datetime import datetime, timezone

# Zugang aus der Umgebung: Datei mit Zeilen „Org: …“ und „Grafana-Token: …“ (Token mit Leserecht genügt).
CREDENTIALS = os.environ.get("HEATPUMP_AUDIT_CREDENTIALS", "influx_credentials.txt")
URL = os.environ.get("HEATPUMP_AUDIT_INFLUX_URL", "http://localhost:8086")
BUCKET = "homeassistant"
LOOKBACK_S = 2 * 86400  # so weit zurück wird der vor dem Start gültige Wert gesucht


def _credential(key: str) -> str:
    for line in open(CREDENTIALS, encoding="utf-8"):
        if line.startswith(key):
            return line.split(":", 1)[1].strip()
    raise KeyError(key)


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class InfluxSource:
    def __init__(self) -> None:
        self._org = _credential("Org")
        self._token = _credential("Grafana-Token")  # nur Leserecht

    def _query(self, flux: str) -> list[dict]:
        req = urllib.request.Request(f"{URL}/api/v2/query?org={self._org}", data=flux.encode(),
                                     headers={"Authorization": f"Token {self._token}",
                                              "Content-Type": "application/vnd.flux", "Accept": "application/csv"})
        text = urllib.request.urlopen(req, timeout=60).read().decode()
        return [r for r in csv.DictReader(io.StringIO(text)) if r.get("_time")]

    def series(self, entity_id: str, start: float, end: float, field: str = "value"):
        """Zeitreihe [(t, v)] einer Entität inklusive des vor `start` gültigen Werts.

        entity_id mit Domain (z. B. "sensor.heatpump_feed_temp"); field "value" (Zahl) oder "state" (Text).
        """
        domain, object_id = entity_id.split(".", 1)
        flux = (f'from(bucket: "{BUCKET}") |> range(start: {_iso(start - LOOKBACK_S)}, stop: {_iso(end)})\n'
                f'|> filter(fn: (r) => r.entity_id == "{object_id}" and r.domain == "{domain}" and r._field == "{field}")\n'
                f'|> keep(columns: ["_time", "_value"]) |> sort(columns: ["_time"])')
        rows = self._query(flux)
        out = []
        for r in rows:
            t = datetime.fromisoformat(r["_time"].replace("Z", "+00:00")).timestamp()
            v = r["_value"]
            if field != "state":
                v = float(v)
            out.append((t, v))
        before = [p for p in out if p[0] <= start]
        return before[-1:] + [p for p in out if p[0] > start]
