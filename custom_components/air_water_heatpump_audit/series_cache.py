"""Rohdaten zwischen zwei Läufen im Speicher behalten und nur das Neue nachladen (Spezifikation 8.2)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .audit_core.series import Series
from .influx_source import trim_before

OVERLAP_S = 300  # so weit vor dem Ende des letzten Laufs wird nachgeladen; spät geschriebene Werte kommen mit
FULL_RELOAD_S = 86400  # spätestens dann ganz laden (Quelle hat ältere Werte nachträglich ergänzt)


@dataclass
class SeriesCache:
    """Zeitreihen des letzten Laufs; `key` beschreibt, was geladen wurde (Quelle, Rollen, Preis-Sensoren)."""

    key: object = None
    series: dict[str, Series] = field(default_factory=dict)
    from_recorder: list[str] = field(default_factory=list)  # Rollen, die InfluxDB nicht hatte
    end: float | None = None
    full_at: float | None = None

    def delta_start(self, key: object, start: float, end: float) -> float | None:
        """Ab wann nachzuladen ist; None = das ganze Fenster laden."""
        if key != self.key or self.end is None or self.full_at is None:
            return None
        if end - self.full_at > FULL_RELOAD_S or self.end <= start:
            return None
        return max(start, self.end - OVERLAP_S)

    def merge(self, fresh: dict[str, Series], start: float, since: float) -> dict[str, Series]:
        """Gespeicherte Werte vor `since` plus neu geladene ab `since`, gekürzt auf das Fenster ab `start`."""
        out = {}
        for role in set(self.series) | set(fresh):
            old = [p for p in self.series.get(role, []) if p[0] < since]
            new = fresh.get(role, [])
            out[role] = trim_before(old + [p for p in new if p[0] >= since] if old else new, start)
        return out

    def keep(self, key: object, series: dict[str, Series], from_recorder: list[str], end: float,
             full: bool) -> None:
        self.key, self.series, self.from_recorder, self.end = key, series, list(from_recorder), end
        if full:
            self.full_at = end

    def clear(self) -> None:
        self.key, self.series, self.from_recorder, self.end, self.full_at = None, {}, [], None, None
