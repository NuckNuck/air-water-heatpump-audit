"""Registry der Audits: Jedes Audit beschreibt sich selbst (Rollen, Stammdaten, Prüfungen, Zeitstrahl).

Ein neues Audit entsteht, indem man ein Modul unter `audits/` mit einem `AUDIT` anlegt und es in `audits.REGISTRY`
einträgt. Runner, Sensoren, Karte und Einrichtung lesen alles Weitere von hier. Entwurf: docs/audit_modules_design.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .result import CheckResult

if TYPE_CHECKING:
    from .context import Context

# Zeitraum eines Audits: ganzes Fenster, ab dem letzten Ereignis, ab dem letzten Warmwasser-Ereignis (context.py)
WINDOW, SECTION, DHW_SECTION = "window", "section", "dhw"


@dataclass(frozen=True)
class CheckSpec:
    check_id: str  # „E3“
    key: str  # „carnot_efficiency“ → unique_id, translation_key, entity_id
    run: Callable[[Context], CheckResult]


@dataclass(frozen=True)
class TimelineSpec:
    """Ein echter Tageswert je Audit im Zeitstrahl (Entscheid F100), mit denselben Schwellen wie die Prüfung."""

    scale: Callable[[dict], dict]  # Stammdaten → {metric, unit, min, max, bands, …}
    point: Callable[[Context, float, float, str], dict]  # (ctx, Tagesbeginn, Tagesende, Tag) → {value, verdict, …}
    metric_names: dict[str, str] = field(default_factory=dict)  # Sprache → Name der Kennzahl


@dataclass(frozen=True)
class AuditSpec:
    audit_id: str
    order: int
    color: str  # feste Audit-Farbe (Datenreife, Zeitstrahl), keine Ampelfarbe
    section: str  # WINDOW: ganzes Fenster; SECTION: ab dem letzten Ereignis; DHW_SECTION: ab dem letzten Warmwasser-Ereignis
    roles: tuple[str, ...]  # alle Rollen, die das Audit (auch über Grundgrößen) liest
    required_roles: tuple[str, ...]  # ohne sie ist das Audit nicht sinnvoll; für die Einrichtung
    master_keys: tuple[str, ...]  # Stammdaten, die das Audit nutzt
    checks: tuple[CheckSpec, ...]
    names: dict[str, str]  # Sprache → Name des Audits
    timeline: TimelineSpec | None = None
    # Nachbearbeitung aller Ergebnisse des Audits (z. B. gemeinsame Datenreife), vor den Aktionen
    finish: Callable[[Context, list[CheckResult]], None] | None = None
    recommended: bool = True  # bei der Einrichtung vorausgewählt
    extra: dict = field(default_factory=dict)


def validate(audits: list[AuditSpec], known_roles: tuple[str, ...]) -> None:
    """Eindeutige IDs und Keys, nur bekannte Rollen. Fehler beim Import statt später im Betrieb."""
    ids = [a.audit_id for a in audits]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Audit-IDs doppelt: {ids}")
    checks = [(c.check_id, c.key) for a in audits for c in a.checks]
    for i in (0, 1):
        values = [c[i] for c in checks]
        if len(values) != len(set(values)):
            raise ValueError(f"Prüfungen doppelt: {values}")
    for a in audits:
        unknown = set(a.roles) - set(known_roles)
        if unknown or not set(a.required_roles) <= set(a.roles):
            raise ValueError(f"{a.audit_id}: unbekannte oder nicht angemeldete Rollen {unknown or a.required_roles}")
