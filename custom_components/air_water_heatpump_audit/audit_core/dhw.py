"""Audit 4 – Warmwasser (Spezifikation: docs/specification.md, Abschnitt 6).

Eine Warmwasserladung ist eine Phase mit `dhw_active` an. Strom je Ladung vom Zähler (Grundsatz 1), Wärme selbst
gerechnet wie in Audit 1. Die Speichertemperatur liest nur Werte außerhalb der Ladung: Während der Ladung zeigen
manche Speicherfühler Mischwerte aus nachströmendem Kaltwasser. Herstellerneutral: nur Rollen und Stammdaten.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import days
from .data_basis import heartbeat_gaps
from .efficiency import KELVIN, MIN_LIFT_K, carnot_verdict
from .heat import RHO_CP_KJ_PER_L_K, energy_kwh, time_mean
from .result import (DERIVED, ELAPSED, HINT, INFO, NOT_ASSESSABLE, OK, PHYSICAL, RATE, SOURCED, CheckResult, count,
                     num, progress)
from .series import Interval, Series, clip, combine, intervals_where, overlaps, subtract, total, value_at

CHARGE_MIN_S = 60  # kürzere Phasen sind Umschalten des Ventils, keine Ladung (wie Zyklus-Klasse dhw)
AFTER_CHARGE_S = 30 * 60  # Speichertemperatur nach der Ladung: höchster Wert in dieser Zeit
MIN_CHARGES = 7  # W1, W2, W5: etwa eine Woche mit einer Ladung pro Tag
MIN_CHARGE_KWH = 0.2  # Ladungen mit weniger Strom: ein Zählerschritt wäre zu viel Anteil
# W2/W3: Desinfektion = Speicher erreicht 60 °C (DVGW W 551). 1 K Fühlertoleranz, grün im Zweifel.
DISINFECTION_C = 60.0
SENSOR_TOLERANCE_K = 1.0
# W2: Speichertemperatur. Unter 50 °C ohne regelmäßige Desinfektion → Hygiene-Hinweis (DVGW W 551: Betriebs-
# temperaturen unter 50 °C vermeiden); über 55 °C → Effizienz-Hinweis.
HYGIENE_MIN_C = 50.0
EFFICIENCY_MAX_C = 55.0
DISINFECTION_MAX_GAP_DAYS = 7  # „regelmäßig“: mindestens eine Desinfektion je Woche
DISINFECTION_MAX_PER_WEEK = 2  # W3: öfter kostet Strom ohne Hygienegewinn
# W4: Bereitschaftsverlust aus dem Abkühlen in ruhigen Nachtstunden, auf die Prüfbedingung der EU-Kennzeichnung
# umgerechnet (Speicher 65 °C, Umgebung 20 °C, VO (EU) 812/2013).
NIGHT_HOURS = (0, 5)  # Ortszeit; nachts wird kaum gezapft
QUIET_MIN_S = 3 * 3600
DRAW_K_PER_H = 1.0  # schneller abkühlen heißt: es wurde gezapft, das Fenster zählt nicht
MIN_QUIET_WINDOWS = 5
MIN_QUIET_H = 15.0
ERP_AMBIENT_C, ERP_DELTA_K = 20.0, 45.0
MIN_TANK_DELTA_K = 10.0  # darunter wird die Umrechnung auf 45 K zu ungenau
# Grenzen der Effizienzklassen: Warmhalteverlust S in W < a + b · V^0,4 (V in Liter), VO (EU) 812/2013 Anhang II
ERP_CLASSES = (("A+", 5.5, 3.16), ("A", 8.5, 4.25), ("B", 12.0, 5.93), ("C", 16.66, 8.33), ("D", 21.0, 10.33),
               ("E", 26.0, 13.66), ("F", 31.0, 16.66))
ERP_OK_CLASS = "C"  # Mindestanforderung der Ökodesign-Verordnung (EU) 814/2013 für neue Speicher bis 500 l
# Die Schätzung (0,5-K-Fühler, Raum mit 20 °C angenommen) ist etwa eine Klasse unsicher: Klasse D ist noch grün mit
# Anmerkung, gelb erst darüber (grün im Zweifel).
ERP_HINT_ABOVE_CLASS = "D"
# W5: Ladezeitpunkt. Wärmste drei Stunden des Tages als Vergleich; Einbuße nach Carnot ab 10 % → Hinweis.
WARM_WINDOW_S = 3 * 3600
TIMING_HINT_PCT = 10.0


def _on(v) -> bool:
    return v in (1, 1.0, True, "on")


@dataclass
class Charge:
    start: float
    end: float
    electricity_kwh: float | None
    heat_kwh: float
    ideal_kwh: float
    tank_after: float | None  # höchste Speichertemperatur bis 30 min nach der Ladung
    sink_mean: float | None  # Mittel aus Vor- und Rücklauf in °C
    outdoor_mean: float | None

    @property
    def disinfection(self) -> bool:
        return self.tank_after is not None and self.tank_after >= DISINFECTION_C - SENSOR_TOLERANCE_K


def _delta(meter: Series, a: float, b: float) -> float | None:
    m_a, m_b = value_at(meter, a), value_at(meter, b)
    return None if m_a is None or m_b is None else float(m_b) - float(m_a)


def _max_in(series: Series, a: float, b: float) -> float | None:
    values = [float(v) for _, v in clip(series, a, b)]
    return max(values) if values else None


def detect_charges(dhw: Series, meter: Series, heat: Series, ideal: Series, tank: Series, flow: Series, ret: Series,
                   outdoor: Series, heartbeat: Series, artifacts: list[Interval], start: float, end: float) -> list[Charge]:
    """Abgeschlossene Ladungen im Zeitraum. Ladungen am Rand, in Lücken oder an Neustarts zählen nicht."""
    gaps = heartbeat_gaps(heartbeat, start, end) if heartbeat else []
    phases = intervals_where(dhw, _on, start, end)
    sink = combine(flow, ret, lambda f, r: (float(f) + float(r)) / 2, start, end)
    out = []
    for i, (a, b) in enumerate(phases):
        if b - a < CHARGE_MIN_S or a <= start or b >= end or overlaps((a, b), gaps) or overlaps((a, b), artifacts):
            continue
        next_start = phases[i + 1][0] if i + 1 < len(phases) else end
        out.append(Charge(a, b, _delta(meter, a, b), energy_kwh(heat, [(a, b)]), energy_kwh(ideal, [(a, b)]),
                          _max_in(tank, b, min(b + AFTER_CHARGE_S, next_start)), time_mean(sink, [(a, b)]),
                          time_mean(outdoor, [(a, b)])))
    return out


def _metered(charges: list[Charge]) -> list[Charge]:
    return [c for c in charges if c.electricity_kwh is not None and c.electricity_kwh >= MIN_CHARGE_KWH]


def efficiency_of(charges: list[Charge]) -> tuple[float, float] | None:
    """(Gütegrad, Arbeitszahl) über die Ladungen; None ohne Strom."""
    metered = _metered(charges)
    electricity = sum(c.electricity_kwh for c in metered)
    if not electricity:
        return None
    return sum(c.ideal_kwh for c in metered) / electricity, sum(c.heat_kwh for c in metered) / electricity


def check_dhw_efficiency(charges: list[Charge], dq: str, offset_robust: bool, meter_step: float | None,
                         since: float) -> CheckResult:
    """W1: Gütegrad der Warmwasserladungen. Schwellen wie E3: dieselbe Maschine, der Gütegrad rechnet den höheren
    Temperaturhub heraus."""
    metered = _metered(charges)
    prog = progress(len(metered), MIN_CHARGES, "charges", RATE, since)
    key = ("W1", "dhw_efficiency")
    if meter_step is None or meter_step > 0.1:
        return CheckResult(*key, NOT_ASSESSABLE, text="Der Stromzähler ist zu grob für einzelne Ladungen "
                           "(nötig 0,1 kWh oder feiner, siehe D8).", origin=DERIVED)
    if len(metered) < MIN_CHARGES:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"{count(len(metered), 'Ladung', 'Ladungen')} mit Zählerwerten, "
                           f"nötig {MIN_CHARGES}.", origin=DERIVED, progress=prog)
    if dq == "low":
        return CheckResult(*key, NOT_ASSESSABLE, text="Datenqualität niedrig (Audit 0), kein Urteil.", origin=DERIVED,
                           progress=prog)
    eta, cop = efficiency_of(metered)
    electricity = sum(c.electricity_kwh for c in metered)
    verdict = carnot_verdict(eta, offset_robust)
    text = (f"Gütegrad {num(eta, '.2f')}, Arbeitszahl {num(cop, '.1f')} aus {count(len(metered), 'Ladung', 'Ladungen')} "
            f"mit {num(electricity, '.1f')} kWh Strom. ")
    if verdict == INFO:
        text += "Besser als jede Anlage im Feldtest – eher ein Messfehler (Durchfluss, Fühler)."
    elif verdict == OK:
        text += "Die Wärmepumpe bereitet Warmwasser so effizient wie beim Heizen üblich."
    else:
        text += ("Unter dem Bereich, der beim Heizen üblich ist (0,30–0,50). Heizstab, sehr hohe Speichertemperatur "
                 "oder häufige kurze Ladungen können die Ursache sein (W2, W3).")
    if not offset_robust:
        text += " Vorläufig: Fühler-Offset noch nicht belastbar."
    return CheckResult(*key, verdict, round(eta, 3), "", text, DERIVED,
                       {"cop": round(cop, 2), "charges": len(metered), "electricity_kwh": round(electricity, 2),
                        "heat_kwh": round(sum(c.heat_kwh for c in metered), 2)}, progress=prog)


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def disinfections(charges: list[Charge]) -> list[Charge]:
    return [c for c in charges if c.disinfection]


def check_dhw_temperature(charges: list[Charge], since: float, end: float, setpoint: Series) -> CheckResult:
    """W2: Speichertemperatur nach normalen Ladungen (Median), gegen Hygiene (50 °C ohne Desinfektion) und
    Effizienz (55 °C)."""
    key = ("W2", "dhw_temperature")
    normal = [c.tank_after for c in charges if c.tank_after is not None and not c.disinfection]
    prog = progress(len(normal), MIN_CHARGES, "charges", RATE, since)
    if len(normal) < MIN_CHARGES:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"{count(len(normal), 'Ladung', 'Ladungen')} mit "
                           f"Speichertemperatur, nötig {MIN_CHARGES}.", origin=SOURCED, progress=prog)
    temp = _median(normal)
    last_disinfection = max((c.end for c in disinfections(charges)), default=None)
    gap_days = (end - (last_disinfection or since)) / 86400
    regular = last_disinfection is not None and gap_days <= DISINFECTION_MAX_GAP_DAYS
    target = time_mean(setpoint, [(since, end)]) if setpoint else None
    text = f"Speicher nach dem Laden {num(temp, '.1f')} °C (Median)"
    text += f", eingestellt {num(target, '.0f')} °C. " if target is not None else ". "
    details = {"tank_after_median": round(temp, 1), "setpoint_mean": None if target is None else round(target, 1),
               "last_disinfection": last_disinfection, "regular_disinfection": regular}
    if temp > EFFICIENCY_MAX_C + SENSOR_TOLERANCE_K:
        verdict = HINT
        text += (f"Wärmer als nötig: Über {num(EFFICIENCY_MAX_C, 'g')} °C sinkt die Effizienz deutlich, und viele "
                 "Wärmepumpen schaffen das nur mit dem Heizstab.")
    elif temp < HYGIENE_MIN_C - SENSOR_TOLERANCE_K and not regular:
        if (end - since) / 86400 < DISINFECTION_MAX_GAP_DAYS:
            return CheckResult(*key, NOT_ASSESSABLE, round(temp, 1), "°C", text + "Unter 50 °C; ob regelmäßig "
                               f"desinfiziert wird, zeigt sich nach {DISINFECTION_MAX_GAP_DAYS} Tagen.", SOURCED,
                               details, progress=progress((end - since) / 3600, DISINFECTION_MAX_GAP_DAYS * 24,
                                                          "hours", ELAPSED, since))
        verdict = HINT
        text += (f"Unter {num(HYGIENE_MIN_C, 'g')} °C und seit {num(gap_days, '.0f')} Tagen keine Aufheizung auf "
                 f"{num(DISINFECTION_C, 'g')} °C. Die Trinkwasser-Regeln raten davon ab (Legionellen).")
    else:
        verdict = OK
        text += "Passt: effizient genug"
        text += (", und regelmäßig auf 60 °C aufgeheizt." if temp < HYGIENE_MIN_C - SENSOR_TOLERANCE_K
                 else " und warm genug.")
    return CheckResult(*key, verdict, round(temp, 1), "°C", text, SOURCED, details, progress=prog)


def check_disinfection(charges: list[Charge], heater: list[Interval], heater_kw: float | None, since: float,
                       end: float) -> CheckResult:
    """W3: Aufheizungen auf 60 °C pro Woche und der Strom des Heizstabs dabei."""
    key = ("W3", "disinfection")
    weeks = (end - since) / (7 * 86400)
    found = disinfections(charges)
    heater_h = sum(total([(max(a, c.start), min(b, c.end + AFTER_CHARGE_S)) for a, b in heater
                          if a < c.end + AFTER_CHARGE_S and b > c.start]) for c in found) / 3600
    heater_kwh = heater_h * heater_kw if heater_kw is not None else None
    details = {"count": len(found), "times": [c.start for c in found], "heater_hours": round(heater_h, 2),
               "heater_kwh": None if heater_kwh is None else round(heater_kwh, 2)}
    prog = progress((end - since) / 3600, 14 * 24, "hours", ELAPSED, since)
    if weeks < 2:
        return CheckResult(*key, NOT_ASSESSABLE, len(found), "", f"{count(len(found), 'Aufheizung', 'Aufheizungen')} "
                           "auf 60 °C bisher; bewertet ab 14 Tagen.", DERIVED, details, progress=prog)
    per_week = len(found) / weeks
    text = f"{count(len(found), 'Aufheizung', 'Aufheizungen')} auf 60 °C in {num(weeks * 7, '.0f')} Tagen"
    if heater_kwh:
        text += f", Heizstab dabei ≈ {num(heater_kwh, '.1f')} kWh"
    text += ". "
    if per_week > DISINFECTION_MAX_PER_WEEK:
        verdict = HINT
        text += "Öfter als zweimal pro Woche kostet Strom, ohne die Hygiene weiter zu verbessern."
    else:
        verdict = OK
        text += "Häufigkeit unauffällig." if found else "Keine – ob das reicht, beurteilt W2 mit der Speichertemperatur."
    return CheckResult(*key, verdict, round(per_week, 2), "1/Woche", text, DERIVED, details, progress=prog)


def quiet_windows(tank: Series, dhw: Series, heartbeat: Series, artifacts: list[Interval], start: float, end: float,
                  tz: str) -> list[tuple[float, float, float, float]]:
    """Nachtfenster ohne Ladung und ohne Zapfen: (Beginn, Ende, Temperatur am Beginn, am Ende)."""
    blocked = [(a, b + AFTER_CHARGE_S) for a, b in intervals_where(dhw, _on, start, end)]
    blocked += heartbeat_gaps(heartbeat, start, end) if heartbeat else []
    blocked += list(artifacts)
    out = []
    for a, _ in days.full_days(start - 86400, end + 86400, tz):
        night = (a + NIGHT_HOURS[0] * 3600, a + NIGHT_HOURS[1] * 3600)
        if night[0] < start or night[1] > end:
            continue
        pieces = [p for p in subtract([night], blocked) if p[1] - p[0] >= QUIET_MIN_S]
        if not pieces:
            continue
        p0, p1 = max(pieces, key=lambda p: p[1] - p[0])
        t0, t1 = value_at(tank, p0), value_at(tank, p1)
        if t0 is None or t1 is None:
            continue
        drop_per_h = (float(t0) - float(t1)) / ((p1 - p0) / 3600)
        if 0 <= drop_per_h <= DRAW_K_PER_H:
            out.append((p0, p1, float(t0), float(t1)))
    return out


def erp_limit_w(volume_l: float, label: str) -> float:
    _, a, b = next(c for c in ERP_CLASSES if c[0] == label)
    return a + b * volume_l ** 0.4


def erp_class(loss_w: float, volume_l: float) -> str:
    return next((label for label, a, b in ERP_CLASSES if loss_w < a + b * volume_l ** 0.4), "G")


def check_standby_loss(windows: list[tuple[float, float, float, float]], volume_l: float | None,
                       since: float) -> CheckResult:
    """W4: Bereitschaftsverlust des Speichers aus dem Abkühlen in ruhigen Nachtstunden."""
    key = ("W4", "standby_loss")
    hours = sum(b - a for a, b, _, _ in windows) / 3600
    prog = progress(len(windows), MIN_QUIET_WINDOWS, "windows", RATE, since)
    if not volume_l:
        return CheckResult(*key, NOT_ASSESSABLE, text="Stammdaten fehlen: Inhalt des Warmwasserspeichers.",
                           origin=PHYSICAL)
    if len(windows) < MIN_QUIET_WINDOWS or hours < MIN_QUIET_H:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"{count(len(windows), 'ruhige Nacht', 'ruhige Nächte')} "
                           f"({num(hours, '.0f')} h), nötig {MIN_QUIET_WINDOWS} und {num(MIN_QUIET_H, 'g')} h.",
                           origin=PHYSICAL, progress=prog)
    drop = sum(t0 - t1 for _, _, t0, t1 in windows)
    loss_w = volume_l * RHO_CP_KJ_PER_L_K * drop / (hours * 3600) * 1000
    tank_mean = sum((t0 + t1) / 2 * (b - a) for a, b, t0, t1 in windows) / (hours * 3600)
    delta = tank_mean - ERP_AMBIENT_C
    if delta < MIN_TANK_DELTA_K:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"Speicher nachts nur {num(tank_mean, '.0f')} °C warm; zu wenig "
                           "Unterschied zum Raum für eine Umrechnung.", origin=PHYSICAL, progress=prog)
    loss_45 = loss_w * ERP_DELTA_K / delta
    label, limit = erp_class(loss_45, volume_l), erp_limit_w(volume_l, ERP_OK_CLASS)
    hint_limit = erp_limit_w(volume_l, ERP_HINT_ABOVE_CLASS)
    kwh_day = loss_w * 24 / 1000
    text = (f"Speicher verliert ≈ {num(loss_w, '.0f')} W bei {num(tank_mean, '.0f')} °C, ≈ {num(kwh_day, '.1f')} kWh "
            f"Wärme am Tag. Umgerechnet auf die Prüfbedingung des Energielabels {num(loss_45, '.0f')} W, "
            f"etwa Klasse {label}. ")
    if loss_45 <= limit:
        verdict = OK
        text += "Gut gedämmt."
    elif loss_45 <= hint_limit:
        verdict = OK
        text += (f"Knapp über der Mindestanforderung für neue Speicher ({num(limit, '.0f')} W, Klasse "
                 f"{ERP_OK_CLASS}), im Rahmen der Schätzgenauigkeit.")
    else:
        verdict = HINT
        text += (f"Deutlich mehr als die Mindestanforderung für neue Speicher ({num(limit, '.0f')} W, Klasse "
                 f"{ERP_OK_CLASS}): Dämmung, Anschlüsse und Zirkulation prüfen.")
    text += f" Schätzung aus {count(len(windows), 'Nacht', 'Nächten')}, Aufstellraum mit 20 °C angenommen."
    return CheckResult(*key, verdict, round(loss_45), "W", text, PHYSICAL,
                       {"loss_w": round(loss_w), "loss_45k_w": round(loss_45), "tank_mean": round(tank_mean, 1),
                        "kwh_per_day": round(kwh_day, 2), "erp_class": label, "limit_w": round(limit),
                        "hint_above_w": round(hint_limit),
                        "windows": len(windows), "hours": round(hours, 1)}, progress=prog)


def warmest_window_mean(outdoor: Series, a: float, b: float) -> float | None:
    """Mittel der wärmsten drei Stunden zwischen a und b (Startzeiten stündlich)."""
    best = None
    t = a
    while t + WARM_WINDOW_S <= b:
        m = time_mean(outdoor, [(t, t + WARM_WINDOW_S)])
        if m is not None and (best is None or m > best):
            best = m
        t += 3600
    return best


def carnot_cop(sink_c: float, source_c: float) -> float | None:
    lift = sink_c - source_c
    return (sink_c + KELVIN) / lift if lift >= MIN_LIFT_K else None


def check_dhw_timing(charges: list[Charge], outdoor: Series, since: float, tz: str) -> CheckResult:
    """W5: Einbuße, weil bei kälterer Luft geladen wird als in den wärmsten drei Stunden desselben Tages (Carnot)."""
    key = ("W5", "dhw_timing")
    rows = []
    for c in charges:
        if c.sink_mean is None or c.heat_kwh <= 0:
            continue
        day_start = next(a for a, b in days.full_days(c.start - 86400, c.start + 86400, tz) if a <= c.start < b)
        actual = time_mean(outdoor, [(c.start, c.end)])
        best = warmest_window_mean(outdoor, day_start, day_start + 86400)
        if actual is None or best is None:
            continue
        cop_now, cop_best = carnot_cop(c.sink_mean, actual), carnot_cop(c.sink_mean, max(best, actual))
        if cop_now and cop_best:
            rows.append((c.heat_kwh, 1 - cop_now / cop_best, best - actual, days.label(c.start, tz)))
    prog = progress(len(rows), MIN_CHARGES, "charges", RATE, since)
    if len(rows) < MIN_CHARGES:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"{count(len(rows), 'Ladung', 'Ladungen')} mit Außentemperatur, "
                           f"nötig {MIN_CHARGES}.", origin=DERIVED, progress=prog)
    heat = sum(r[0] for r in rows)
    loss = 100 * sum(r[0] * r[1] for r in rows) / heat
    colder = sum(r[0] * r[2] for r in rows) / heat
    text = (f"Geladen wird im Mittel {num(colder, '.1f')} K kälter als in den wärmsten drei Stunden des Tages; das "
            f"kostet beim Warmwasser ≈ {num(loss, '.0f')} % Effizienz (nach Carnot). ")
    if loss >= TIMING_HINT_PCT:
        verdict = HINT
        text += "Ein Zeitfenster am Nachmittag würde Strom sparen."
    else:
        verdict = OK
        text += "Kaum Spielraum."
    return CheckResult(*key, verdict, round(loss, 1), "%", text, DERIVED,
                       {"colder_k": round(colder, 1), "charges": len(rows)}, progress=prog)


def daily_point(charges: list[Charge], a: float, b: float, offset_robust: bool) -> dict:
    """Zeitstrahl: Gütegrad der Ladungen eines Tages, mit derselben Ampel wie W1."""
    result = efficiency_of([c for c in charges if a <= c.start < b])
    if result is None:
        return {"value": None, "verdict": NOT_ASSESSABLE}
    eta, cop = result
    return {"value": round(eta, 3), "verdict": carnot_verdict(eta, offset_robust), "cop": round(cop, 2)}
