"""Audit 1 – Effizienz gesamt (Spezifikation: docs/specification.md, Abschnitt 4).

Strom immer vom Stromzähler (Grundsatz 1), Wärme selbst gerechnet, roh und mit Fühler-Offset aus D4 (F74).
Herstellerneutral: nur Rollen und Stammdaten (Spezifikation 1.6).
"""

from __future__ import annotations

from . import days
from .data_basis import check_coverage
from .heat import energy_kwh, time_mean
from .result import DERIVED, DESCRIPTIVE, HINT, INFO, NOT_ASSESSABLE, OK, SOURCED, WARN, CheckResult, count, num
from .series import Series, combine, intervals_where, value_at

KELVIN = 273.15
MIN_DAY_KWH = 2.0  # darunter ist der Zählerschritt von 1 kWh größer als 50 %
WEEK_DAYS = 7
MIN_LIFT_K = 5.0  # kleinere Hübe lassen den Carnot-COP gegen unendlich laufen
# E2: Monatsarbeitszahl, Mittel von 22 L/W-WP (WP-QS S. 87 f.): 2,7 bei 2 °C (Dez. 2022), 3,8 bei 13 °C (Oktober)
FIELD_MONTHLY_COP = ((2.0, 2.7), (13.0, 3.8))
# E3: Feldbereich L/W 0,32–0,44 (WP-QS S. 123). Grün ab 0,30 wegen weiterer Systemgrenze (Pumpen, Standby, Heizstab,
# Warmwasser); rot erst unter 0,32 × 0,75, also auch mit ±15 % Wärmefehler klar unter dem Feldminimum.
CARNOT_OK_MIN, CARNOT_WARN_BELOW, CARNOT_PLAUSIBLE_MAX = 0.30, 0.24, 0.50
FIELD_DHW_SHARE = 19  # E4: TWE-Anteil an der Wärme, WP-QS S. 72


def _on(v) -> bool:
    return v in (1, 1.0, True, "on")


def carnot_power(power: Series, flow: Series, ret: Series, outdoor: Series, start: float, end: float) -> Series:
    """Ideale Strom-Leistung in kW = Wärmeleistung ÷ Carnot-COP (Fraunhofer-Konvention, ohne Offsets).

    Senke = Mittel aus Vor- und Rücklauf, Quelle = Außentemperatur. Bei Hub < 5 K None (zählt nicht).
    """
    sink = combine(flow, ret, lambda a, b: (float(a) + float(b)) / 2 + KELVIN, start, end)
    cop = combine(sink, outdoor, lambda s, o: s / (s - float(o) - KELVIN) if s - float(o) - KELVIN >= MIN_LIFT_K
                  else None, start, end)
    return combine(power, cop, lambda p, c: float(p) / c if c else 0.0, start, end)


def daily_rows(meter: Series, raw: Series, corrected: Series, ideal: Series, outdoor: Series, dhw: Series,
               heartbeat: Series, start: float, end: float, tz: str = days.DEFAULT_TZ) -> list[dict]:
    """Gültige Tage (Spezifikation 4.1): voller Tag, Heartbeat ≥ 98 %, Zählerstände bekannt, Strom ≥ 2 kWh."""
    rows = []
    for a, b in days.full_days(start, end, tz):
        if check_coverage(heartbeat, a, b).verdict != OK:
            continue
        m_a, m_b = value_at(meter, a), value_at(meter, b)
        if m_a is None or m_b is None:
            continue
        electricity = float(m_b) - float(m_a)
        if electricity < MIN_DAY_KWH:
            continue
        day = [(a, b)]
        heat_raw, heat = energy_kwh(raw, day), energy_kwh(corrected, day)
        dhw_heat = energy_kwh(corrected, intervals_where(dhw, _on, a, b))
        outside = time_mean(outdoor, day)
        rows.append({"day": days.label(a, tz), "electricity_kwh": round(electricity, 2),
                     "heat_raw_kwh": round(heat_raw, 2), "heat_kwh": round(heat, 2),
                     "dhw_heat_kwh": round(dhw_heat, 2), "ideal_kwh": round(energy_kwh(ideal, day), 3),
                     "cop_raw": round(heat_raw / electricity, 2), "cop": round(heat / electricity, 2),
                     "outdoor_mean": None if outside is None else round(outside, 1)})
    return rows


def _sum(rows: list[dict], key: str) -> float:
    return sum(r[key] for r in rows)


def _provisional(offset_robust: bool, meter_step: float | None) -> list[str]:
    notes = []
    if not offset_robust:
        notes.append("Fühler-Offset noch nicht belastbar")
    if meter_step is None or meter_step >= 1:
        notes.append("Zähler nur ganze kWh")
    return notes


def check_daily_cop(rows: list[dict], offset_robust: bool, meter_step: float | None) -> CheckResult:
    """E1: Arbeitszahl des letzten gültigen Tages; immer info (keine Tagesskala in der Literatur)."""
    if not rows:
        return CheckResult("E1", "daily_cop", NOT_ASSESSABLE, text="Noch kein gültiger voller Tag.",
                           origin=DESCRIPTIVE, details={"days": rows})
    r = rows[-1]
    text = (f"{days.display(r['day'])}: Arbeitszahl {num(r['cop'], '.1f')} (roh {num(r['cop_raw'], '.1f')}) aus "
            f"{num(r['heat_kwh'], '.1f')} kWh Wärme und {num(r['electricity_kwh'], '.0f')} kWh Strom")
    if r["outdoor_mean"] is not None:
        text += f" bei {num(r['outdoor_mean'], '.1f')} °C außen"
    text += "."
    notes = _provisional(offset_robust, meter_step)
    if notes:
        text += " Vorläufig: " + ", ".join(notes) + "."
    return CheckResult("E1", "daily_cop", INFO, r["cop"], "", text, DESCRIPTIVE, {"days": rows})


def _week(rows: list[dict]) -> list[dict] | None:
    return rows[-WEEK_DAYS:] if len(rows) >= WEEK_DAYS else None


def field_cop(outdoor: float | None) -> float | None:
    """Fraunhofer-Monatsmittel bei dieser Außentemperatur; außerhalb 2–13 °C kein Vergleichswert."""
    (t0, c0), (t1, c1) = FIELD_MONTHLY_COP
    if outdoor is None or not t0 <= outdoor <= t1:
        return None
    return c0 + (c1 - c0) * (outdoor - t0) / (t1 - t0)


def _week_outdoor(week: list[dict]) -> float | None:
    values = [r["outdoor_mean"] for r in week if r["outdoor_mean"] is not None]
    return sum(values) / len(values) if values else None


def check_weekly_cop(rows: list[dict]) -> CheckResult:
    """E2: Arbeitszahl der Woche mit Feld-Vergleichswert; info, die Bewertung macht E3."""
    week = _week(rows)
    if week is None:
        return CheckResult("E2", "weekly_cop", NOT_ASSESSABLE,
                           text=f"{count(len(rows), 'gültiger Tag', 'gültige Tage')}, nötig {WEEK_DAYS}.", origin=SOURCED)
    electricity, heat, heat_raw = _sum(week, "electricity_kwh"), _sum(week, "heat_kwh"), _sum(week, "heat_raw_kwh")
    cop, outdoor = heat / electricity, _week_outdoor(week)
    text = (f"{days.display(week[0]['day'])} bis {days.display(week[-1]['day'])}: Arbeitszahl {num(cop, '.1f')} "
            f"(roh {num(heat_raw / electricity, '.1f')}).")
    reference = field_cop(outdoor)
    if reference is not None:
        text += (f" Feldtest-Mittel bei {num(outdoor, '.0f')} °C außen: {num(reference, '.1f')} (Fraunhofer, "
                 "Monatswerte von 22 Wärmepumpen; ein Mittelwert, keine Grenze).")
    elif outdoor is not None:
        text += f" Für {num(outdoor, '.0f')} °C außen gibt es keinen Feld-Vergleichswert."
    return CheckResult("E2", "weekly_cop", INFO, round(cop, 2), "", text, SOURCED,
                       {"electricity_kwh": round(electricity, 1), "heat_kwh": round(heat, 1),
                        "heat_raw_kwh": round(heat_raw, 1), "outdoor_mean": outdoor, "field_cop": reference})


def carnot_verdict(eta: float, offset_robust: bool) -> str:
    """Ampel für einen Gütegrad (E3, auch für Tageswerte im Zeitstrahl). Rot nur mit belastbarem Fühler-Offset.

    Über der Plausibilitätsgrenze kein Gelb, sondern Info: Ein zu guter Wert ist kein Mangel der Anlage, sondern ein
    Hinweis auf die Messung (Audit 0). Gelb oben und unten machte die Skala missverständlich (Nutzer 26.10.)."""
    if eta > CARNOT_PLAUSIBLE_MAX:
        return INFO
    if eta >= CARNOT_OK_MIN:
        return OK
    return WARN if eta < CARNOT_WARN_BELOW and offset_robust else HINT


def check_carnot_efficiency(rows: list[dict], dq: str, offset_robust: bool) -> CheckResult:
    """E3: Gütegrad der Woche = ideale ÷ gemessene Strommenge. Einziges Urteil von Audit 1."""
    week = _week(rows)
    if week is None:
        return CheckResult("E3", "carnot_efficiency", NOT_ASSESSABLE,
                           text=f"{count(len(rows), 'gültiger Tag', 'gültige Tage')}, nötig {WEEK_DAYS}.", origin=DERIVED)
    if dq == "low":
        return CheckResult("E3", "carnot_efficiency", NOT_ASSESSABLE,
                           text="Datenqualität niedrig (Audit 0), kein Urteil.", origin=DERIVED)
    eta = _sum(week, "ideal_kwh") / _sum(week, "electricity_kwh")
    verdict = carnot_verdict(eta, offset_robust)
    text = f"Gütegrad {num(eta, '.2f')} (Feldtest Luft/Wasser 0,32–0,44, Mittel 0,39). "
    if eta > CARNOT_PLAUSIBLE_MAX:
        text += ("Besser als jede Anlage im Feldtest – wahrscheinlicher ist ein Messfehler (Fühler-Offset, Durchfluss, "
                 "Stromzähler erfasst nicht die ganze Wärmepumpe).")
    elif verdict == OK:
        text += "Für ihre Temperaturen arbeitet die Wärmepumpe normal."
    elif verdict == WARN:
        text += ("Deutlich unter allen Anlagen im Feldtest, auch mit Messunsicherheit. Ursachen in Audit 2 und 3 "
                 "prüfen (Takten, Heizstab, Vorlauf), sonst Fachbetrieb.")
    else:
        text += "Unter dem Feldtest-Bereich. Beobachten; Hinweise in Audit 2 und 3 können die Ursache zeigen."
    if not offset_robust:
        text += " Vorläufig: Fühler-Offset noch nicht belastbar."
    return CheckResult("E3", "carnot_efficiency", verdict, round(eta, 3), "", text, DERIVED,
                       {"ideal_kwh": round(_sum(week, "ideal_kwh"), 2),
                        "electricity_kwh": round(_sum(week, "electricity_kwh"), 1)})


def check_dhw_share(rows: list[dict]) -> CheckResult:
    """E4: Anteil Warmwasser an der Wärme der Woche."""
    week = _week(rows)
    if week is None:
        return CheckResult("E4", "dhw_share", NOT_ASSESSABLE,
                           text=f"{count(len(rows), 'gültiger Tag', 'gültige Tage')}, nötig {WEEK_DAYS}.", origin=SOURCED)
    heat = _sum(week, "heat_kwh")
    if heat <= 0:
        return CheckResult("E4", "dhw_share", NOT_ASSESSABLE, text="Keine Wärme in der Woche.", origin=SOURCED)
    share = 100 * _sum(week, "dhw_heat_kwh") / heat
    return CheckResult("E4", "dhw_share", INFO, round(share, 1), "%",
                       f"{num(share, '.0f')} % der Wärme gingen ins Warmwasser (Feldtest-Mittel übers Jahr "
                       f"{FIELD_DHW_SHARE} %; im Sommer mehr, im Winter weniger).", SOURCED)
