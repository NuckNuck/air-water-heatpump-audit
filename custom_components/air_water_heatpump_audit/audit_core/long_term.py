"""Statistik-Tage: Tage vor dem Fenster aus der Langzeitstatistik (Spezifikation 1.11, Issue #19).

Die Langzeitstatistik liefert je Tag nur Summen und Mittel. Die Wärme kommt deshalb vom Wärmezähler der Steuerung,
korrigiert mit dem Verhältnis zur selbst gerechneten Wärme an den Tagen, für die es Rohdaten gibt (F294 a).
Statistik-Tage urteilen nicht; sie ergänzen Zeitstrahl, Hochrechnung und Wirkung (F295).

Eingang `stats`: {"electricity_kwh": {Tag: kWh}, "controller_heat_kwh": {Tag: kWh}, "outdoor_mean": {Tag: °C}},
Tag im Format von days.label(). Die Datenquelle liefert dieselben Tageswerte auch für die Tage des Fensters, damit der
Faktor gleich Gemessenes mit gleich Gemessenem vergleicht.
"""

from __future__ import annotations

from .efficiency import MIN_DAY_KWH, WEEK_DAYS

SOURCE = "statistics"
MIN_FACTOR_DAYS = WEEK_DAYS  # Spezifikation 1.11: eine Woche, damit einzelne Tage mit Lücken nicht durchschlagen


def heat_factors(raw_rows: list[dict], controller_heat: dict[str, float]) -> tuple[float, float] | None:
    """(Faktor roh, Faktor korrigiert) = Σ eigene Wärme ÷ Σ Steuerungswärme über die gültigen Rohdaten-Tage mit
    Steuerungswärme > 0; None bei weniger als MIN_FACTOR_DAYS solchen Tagen."""
    pairs = [(r, controller_heat[r["day"]]) for r in raw_rows if (controller_heat.get(r["day"]) or 0) > 0]
    if len(pairs) < MIN_FACTOR_DAYS:
        return None
    controller = sum(c for _, c in pairs)
    return (sum(r["heat_raw_kwh"] for r, _ in pairs) / controller,
            sum(r["heat_kwh"] for r, _ in pairs) / controller)


def statistic_rows(stats: dict | None, raw_rows: list[dict], before_day: str) -> list[dict]:
    """Gültige Statistik-Tage vor `before_day` (erster voller Tag des Fensters), aufsteigend.

    Gültig: Strom ≥ MIN_DAY_KWH und Steuerungswärme > 0. Ohne Faktor (heat_factors) keine Tage."""
    if not stats:
        return []
    electricity = stats.get("electricity_kwh") or {}
    controller = stats.get("controller_heat_kwh") or {}
    outdoor = stats.get("outdoor_mean") or {}
    factors = heat_factors(raw_rows, controller)
    if factors is None:
        return []
    f_raw, f_corr = factors
    rows = []
    for day in sorted(d for d in electricity if d < before_day):
        kwh, heat = electricity[day], controller.get(day)
        if kwh is None or kwh < MIN_DAY_KWH or not heat or heat <= 0:
            continue
        heat_raw, heat_corr = heat * f_raw, heat * f_corr
        mean = outdoor.get(day)
        rows.append({"day": day, "source": SOURCE, "electricity_kwh": round(kwh, 2),
                     "heat_raw_kwh": round(heat_raw, 2), "heat_kwh": round(heat_corr, 2),
                     "dhw_heat_kwh": None, "ideal_kwh": None,
                     "cop_raw": round(heat_raw / kwh, 2), "cop": round(heat_corr / kwh, 2),
                     "outdoor_mean": None if mean is None else round(mean, 1),
                     "heat_factor": round(f_corr, 3)})
    return rows
