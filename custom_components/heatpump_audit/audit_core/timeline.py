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


def daily_points(ctx: Context, audits: list[AuditSpec]) -> list[dict]:
    """Ein Eintrag je vollem lokalen Tag im Fenster, darin je Audit mit Zeitstrahl ein Punkt {value, verdict, …}.

    Die Punkte rechnen über das ganze Fenster (Grundgrößen `…_window`), unabhängig vom letzten Ereignis.
    """
    out = []
    for a, b in ctx.full_days():
        label = days.label(a, ctx.tz)
        entry = {"day": label, "start": a, "end": b}
        for spec in audits:
            entry[spec.audit_id] = spec.timeline.point(ctx, a, b, label)
        out.append(entry)
    return out


def merge(stored: list[dict], fresh: list[dict], keep_days: int = KEEP_DAYS) -> list[dict]:
    """Gespeicherte Tage um neu gerechnete ergänzen; ein neu gerechneter Tag ersetzt den gespeicherten."""
    by_day = {d["day"]: d for d in stored} | {d["day"]: d for d in fresh}
    return [by_day[k] for k in sorted(by_day)][-keep_days:]
