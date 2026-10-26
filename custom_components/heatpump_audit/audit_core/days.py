"""Kalendertage in Ortszeit (Sommerzeit-fest: ein Tag kann 23 oder 25 h haben)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .series import Interval

DEFAULT_TZ = "Europe/Berlin"


def midnights(start: float, end: float, tz: str = DEFAULT_TZ) -> list[float]:
    """Alle lokalen Mitternächte in [start, end]."""
    zone = ZoneInfo(tz)
    d = datetime.fromtimestamp(start, zone).date()
    out = []
    while True:
        t = datetime(d.year, d.month, d.day, tzinfo=zone).timestamp()
        if t > end:
            return out
        if t >= start:
            out.append(t)
        d += timedelta(days=1)


def full_days(start: float, end: float, tz: str = DEFAULT_TZ) -> list[Interval]:
    """Vollständig im Zeitraum liegende lokale Tage als (Mitternacht, nächste Mitternacht)."""
    m = midnights(start, end, tz)
    return list(zip(m, m[1:]))


def label(t: float, tz: str = DEFAULT_TZ) -> str:
    return datetime.fromtimestamp(t, ZoneInfo(tz)).strftime("%Y-%m-%d")


def display(day: str) -> str:
    """Tag aus label() für Fließtexte: „2026-10-27“ → „27.10.2026“."""
    y, m, d = day.split("-")
    return f"{d}.{m}.{y}"
