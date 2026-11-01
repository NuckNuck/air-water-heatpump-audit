"""Zeitstrahl: je vollem Tag ein echter Messwert pro Audit, dazu die Ampel-Bänder (Entscheid F100).

Kein Gesamt-Score: Jede Linie ist eine Kennzahl, die es auch in der Tabelle gibt, mit denselben Schwellen. Tageswerte
hängen nicht von Ereignissen ab; Ereignisse zeichnet die Karte als senkrechte Linien darüber.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import days

if TYPE_CHECKING:
    from .context import Context
    from .registry import AuditSpec

KEEP_DAYS = 400  # so viele Tage hält die Integration gespeichert, auch wenn die Rohdaten älter sind
_DAY_KEYS = ("day", "start", "end")


def _has_data(entry: dict) -> bool:
    """Mindestens ein Audit hat an diesem Tag einen Wert; Abdeckung 0 % zählt nicht."""
    return any(isinstance(p, dict) and p.get("value") for k, p in entry.items() if k not in _DAY_KEYS)


def trim_leading_empty(days_: list[dict]) -> list[dict]:
    """Tage vor dem ersten Tag mit Daten weglassen (z. B. vor dem Einbau); Lücken danach bleiben sichtbar."""
    first = next((i for i, d in enumerate(days_) if _has_data(d)), len(days_))
    return days_[first:]


def daily_points(ctx: Context, audits: list[AuditSpec]) -> list[dict]:
    """Ein Eintrag je vollem lokalen Tag im Fenster, darin je Audit mit Zeitstrahl ein Punkt {value, verdict, …}.

    Die Punkte rechnen über das ganze Fenster (Grundgrößen `…_window`), unabhängig vom letzten Ereignis. Tage vor
    dem ersten Messwert entfallen.
    """
    out = []
    for a, b in ctx.full_days():
        label = days.label(a, ctx.tz)
        entry = {"day": label, "start": a, "end": b}
        for spec in audits:
            entry[spec.audit_id] = spec.timeline.point(ctx, a, b, label)
        out.append(entry)
    return trim_leading_empty(out)


def merge(stored: list[dict], fresh: list[dict], keep_days: int = KEEP_DAYS) -> list[dict]:
    """Gespeicherte Tage um neu gerechnete ergänzen; ein neu gerechneter Tag ersetzt den gespeicherten. Leere Tage
    vor dem ersten Messwert fallen auch aus dem Speicher."""
    by_day = {d["day"]: d for d in stored} | {d["day"]: d for d in fresh}
    return trim_leading_empty([by_day[k] for k in sorted(by_day)])[-keep_days:]
