"""Ergebnis einer Prüfung: Urteil, Kennzahl, Herkunft der Schwelle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

OK, HINT, WARN, INFO, NOT_ASSESSABLE = "ok", "hint", "warn", "info", "not_assessable"
_RANK = {OK: 0, HINT: 1, WARN: 2}

SOURCED, DERIVED, PHYSICAL, DESCRIPTIVE = "sourced", "derived", "physical", "descriptive"

# Zählweise der Datenmenge einer Prüfung (readiness.py): volle Kalendertage, verstrichene Zeit, gezählte Vorkommnisse
FULL_DAYS, ELAPSED, RATE = "full_days", "elapsed", "rate"


@dataclass
class CheckResult:
    check_id: str
    key: str
    verdict: str
    value: object = None
    unit: str = ""
    text: str = ""
    origin: str = DESCRIPTIVE
    details: dict = field(default_factory=dict)
    action: dict | None = None  # {who, text} bei Gelb/Rot, siehe actions.py
    progress: dict | None = None  # Datenmenge für die Datenreife, siehe progress()

    def as_dict(self) -> dict:
        return asdict(self)


def progress(have: float, need: float, unit: str, basis: str, since: float, lag_h: float = 0.0) -> dict:
    """Wie viel Daten eine Prüfung hat und braucht.

    unit: days, heating_days, hours, heating_hours, cycles, windows; bei ELAPSED sind have/need Stunden.
    since: ab wann gezählt wird; lag_h: um so viele Stunden später wird ein voller Tag erst zählbar (D5).
    """
    return {"have": round(have, 2), "need": need, "unit": unit, "basis": basis, "since": since, "lag_h": lag_h}


def overall(results: list[CheckResult]) -> str:
    """Schlechtestes bewertetes Urteil; info zählt nicht; nur nicht Bewertbares ergibt not_assessable."""
    rated = [r.verdict for r in results if r.verdict in _RANK]
    if rated:
        return max(rated, key=_RANK.__getitem__)
    if any(r.verdict == INFO for r in results):
        return INFO
    return NOT_ASSESSABLE


def num(value: float, spec: str = "g") -> str:
    """Zahl für Fließtexte im deutschen Format: Dezimalkomma, Tausenderpunkt nur bei spec mit ",". """
    text = format(value, spec)
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def count(n: int, one: str, many: str) -> str:
    """Anzahl mit passendem Wort für Fließtexte: count(1, "Tag", "Tage") → „1 Tag“, count(3, …) → „3 Tage“."""
    return f"{n} {one if n == 1 else many}"


def grade(value: float, ok_max: float, hint_max: float) -> str:
    """Einseitige Schwelle: ≤ ok_max grün, ≤ hint_max gelb, darüber rot."""
    if value <= ok_max:
        return OK
    return HINT if value <= hint_max else WARN
