"""Haushalt: Wer wohnt wann im Haus und wie viel Warmwasser ist damit zu erwarten (Spezifikation 1.4, 6.6).

Herstellerneutral und ohne Hardware: Die Personen trägt der Besitzer ein. Jede Person hat ein Anwesenheitsmuster,
damit z. B. Kinder, die abwechselnd in zwei Haushalten leben, nur in ihren Wochen zählen. Das Audit rechnet mit dem
Anteil der Anwesenheit über den Auswertungszeitraum, nicht mit der Kopfzahl.

Personen kommen als Liste von dicts (Stammdaten `household`):
    {"name": "…", "birth_year": 2015, "presence": "always" | "rotation" | "weekdays" | "share",
     "weeks_present": 1, "weeks_absent": 1, "rotation_start": "2026-01-05",   # rotation
     "weekdays": ["fri", "sat", "sun"], "every_n_weeks": 2,                   # weekdays (+ rotation_start als Anker)
     "share_pct": 50,                                                          # share
     "showers_per_week": 7, "baths_per_week": 0, "shower_time": "morning"}
Fehlende Gewohnheiten ersetzt das Audit durch typische Werte für das Alter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import days
from .heat import RHO_CP_KJ_PER_L_K

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
PRESENCE_MODES = ("always", "rotation", "weekdays", "share")
SHOWER_TIMES = ("morning", "midday", "evening", "varied")

# Mischwasser an der Dusche und Kaltwasser (Bezugswerte, Quellen: docs/specification.md 6.6)
MIXED_C = 40.0
COLD_WATER_C = 10.0
# Liter Mischwasser (40 °C) je Vorgang und Grundbedarf je Person und Tag (Hände, Küche, Waschbecken)
SHOWER_L = 40.0
BATH_L = 120.0
CHILD_BATH_L = 60.0  # Kinderbad bis 5 Jahre: halbe Wanne
BASE_L_PER_DAY = 10.0
# Typische Gewohnheiten, wenn nichts eingetragen ist: (bis Alter, Duschen/Woche, Bäder/Woche)
TYPICAL_HABITS = ((5, 0.0, 3.0), (11, 3.0, 1.0), (17, 6.0, 0.0), (200, 6.0, 0.0))


@dataclass(frozen=True)
class Person:
    name: str
    birth_year: int | None
    presence: str = "always"
    weeks_present: int = 1
    weeks_absent: int = 1
    rotation_start: date | None = None
    weekdays: tuple[str, ...] = ()
    every_n_weeks: int = 1
    share_pct: float = 100.0
    showers_per_week: float | None = None
    baths_per_week: float | None = None
    shower_time: str = "varied"

    def age(self, on: date) -> int | None:
        return None if self.birth_year is None else on.year - self.birth_year

    def habits(self, on: date) -> tuple[float, float]:
        """(Duschen/Woche, Bäder/Woche): eingetragen, sonst typisch fürs Alter (ohne Alter: erwachsen)."""
        age = self.age(on)
        _, showers, baths = TYPICAL_HABITS[-1] if age is None else next(h for h in TYPICAL_HABITS if age <= h[0])
        return (showers if self.showers_per_week is None else self.showers_per_week,
                baths if self.baths_per_week is None else self.baths_per_week)

    def presence_on(self, day: date) -> float:
        """Anteil des Tages im Haushalt: 1 oder 0, bei „share“ der eingetragene Anteil."""
        if self.presence == "share":
            return max(0.0, min(100.0, self.share_pct)) / 100
        anchor = self.rotation_start or date(2024, 1, 1)  # ein Montag
        if self.presence == "rotation":
            cycle = max(1, self.weeks_present) + max(0, self.weeks_absent)
            week = ((day - anchor).days // 7) % cycle
            return 1.0 if week < max(1, self.weeks_present) else 0.0
        if self.presence == "weekdays":
            in_week = ((day - anchor).days // 7) % max(1, self.every_n_weeks) == 0
            return 1.0 if in_week and WEEKDAYS[day.weekday()] in self.weekdays else 0.0
        return 1.0

    def mixed_l_per_day(self, on: date) -> float:
        """Erwarteter Warmwasserbedarf an einem Tag im Haushalt, als Mischwasser 40 °C."""
        showers, baths = self.habits(on)
        age = self.age(on)
        bath_l = CHILD_BATH_L if age is not None and age <= TYPICAL_HABITS[0][0] else BATH_L
        return (showers * SHOWER_L + baths * bath_l) / 7 + BASE_L_PER_DAY


def _date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_persons(raw: list[dict] | None) -> list[Person]:
    """Stammdaten → Personen; unbekannte Felder werden ignoriert, kaputte Einträge übersprungen."""
    out = []
    for p in raw or []:
        try:
            out.append(Person(
                name=str(p.get("name") or ""), birth_year=int(p["birth_year"]) if p.get("birth_year") else None,
                presence=p.get("presence") if p.get("presence") in PRESENCE_MODES else "always",
                weeks_present=int(p.get("weeks_present") or 1), weeks_absent=int(p.get("weeks_absent") or 0),
                rotation_start=_date(p.get("rotation_start")), weekdays=tuple(p.get("weekdays") or ()),
                every_n_weeks=int(p.get("every_n_weeks") or 1),
                share_pct=float(p["share_pct"]) if p.get("share_pct") is not None else 100.0,
                showers_per_week=None if p.get("showers_per_week") is None else float(p["showers_per_week"]),
                baths_per_week=None if p.get("baths_per_week") is None else float(p["baths_per_week"]),
                shower_time=p.get("shower_time") if p.get("shower_time") in SHOWER_TIMES else "varied"))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def local_dates(start: float, end: float, tz: str = days.DEFAULT_TZ) -> list[date]:
    """Kalendertage, die der Zeitraum berührt, gewichtet wird über die vollen Tage."""
    zone = ZoneInfo(tz)
    return [datetime.fromtimestamp(a, zone).date() for a, _ in days.full_days(start, end, tz)]


def persons_mean(persons: list[Person], dates: list[date]) -> float:
    """Mittlere Zahl anwesender Personen über die Tage."""
    if not dates:
        return 0.0
    return sum(p.presence_on(d) for p in persons for d in dates) / len(dates)


def expected_mixed_l(persons: list[Person], dates: list[date]) -> float | None:
    """Erwarteter Warmwasserbedarf im Mittel der Tage, als Mischwasser 40 °C in Liter pro Tag."""
    if not persons or not dates:
        return None
    return sum(p.presence_on(d) * p.mixed_l_per_day(d) for p in persons for d in dates) / len(dates)


def mixed_l(heat_kwh: float, cold_c: float = COLD_WATER_C) -> float:
    """Wärme → Liter Mischwasser 40 °C."""
    return heat_kwh * 3600 / (RHO_CP_KJ_PER_L_K * (MIXED_C - cold_c))


def tank_l(heat_kwh: float, tank_c: float, cold_c: float = COLD_WATER_C) -> float | None:
    """Wärme → Liter, die bei dieser Speichertemperatur aus dem Speicher fließen (und kalt nachströmen)."""
    return heat_kwh * 3600 / (RHO_CP_KJ_PER_L_K * (tank_c - cold_c)) if tank_c > cold_c else None


def reserve_mixed_l(volume_l: float, tank_c: float, cold_c: float = COLD_WATER_C) -> float:
    """Wie viel Mischwasser 40 °C ein voller Speicher liefert, ohne Schichtverluste: V · (T − Tk) / (40 − Tk)."""
    return volume_l * max(0.0, tank_c - cold_c) / (MIXED_C - cold_c)
