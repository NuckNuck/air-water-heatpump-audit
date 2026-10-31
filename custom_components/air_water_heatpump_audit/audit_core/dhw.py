"""Audit 4 – Warmwasser (Spezifikation: docs/specification.md, Abschnitt 6).

Eine Warmwasserladung ist eine Phase mit `dhw_active` an. Strom je Ladung vom Zähler (Grundsatz 1), Wärme selbst
gerechnet wie in Audit 1. Die Speichertemperatur liest nur Werte außerhalb der Ladung: Während der Ladung zeigen
manche Speicherfühler Mischwerte aus nachströmendem Kaltwasser. Herstellerneutral: nur Rollen und Stammdaten.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from . import days
from . import household as hh
from .data_basis import heartbeat_gaps
from .efficiency import KELVIN, MIN_LIFT_K, carnot_verdict
from .heat import RHO_CP_KJ_PER_L_K, energy_kwh, time_mean
from .result import (DERIVED, ELAPSED, HINT, INFO, NOT_ASSESSABLE, OK, PHYSICAL, RATE, SOURCED, CheckResult, count,
                     num, progress)
from .series import Interval, Series, clip, combine, intervals_where, overlaps, subtract, total, value_at

# Ereignisse, ab denen das Audit Warmwasser neu rechnet (Arten wie in den Ereignis-Untereinträgen)
EVENT_KINDS = ("dhw_setting", "hardware", "other")
CHARGE_MIN_S = 60  # kürzere Phasen sind Umschalten des Ventils, keine Ladung (wie Zyklus-Klasse dhw)
AFTER_CHARGE_S = 30 * 60  # Speichertemperatur nach der Ladung: höchster Wert in dieser Zeit
MIN_CHARGES = 7  # W1, W2, W5: etwa eine Woche mit einer Ladung pro Tag
MIN_CHARGE_KWH = 0.2  # Ladungen mit weniger Strom: ein Zählerschritt wäre zu viel Anteil
# W2/W3: Aufheizen auf 60 °C (Legionellenschaltung). 1 K Fühlertoleranz, grün im Zweifel.
DISINFECTION_C = 60.0
SENSOR_TOLERANCE_K = 1.0
# W2: Speichertemperatur nach dem Laden. Untere Betriebstemperatur für Ein- und Zweifamilienhäuser ohne Zirkulation
# 50 °C (DVGW-Information 2023, S. 11); eine Legionellenschaltung ersetzt sie nicht sicher (UBA 2024, S. 5). Über
# 60 °C verlangt keine Regel mehr; jedes Kelvin kostet beim Warmwasser ≈ 1,4 % (WP-QS S. 171).
HYGIENE_MIN_C = 50.0
EFFICIENCY_MAX_C = 60.0
DHW_PENALTY_PCT_PER_K = 1.4
DISINFECTION_MAX_PER_WEEK = 2  # W3: öfter kostet Strom ohne Hygienegewinn
# W2 unter 50 °C: grün, wenn der Speicher regelmäßig auf 60 °C aufgeheizt wird (Entscheid F226). Abstand aus den
# Stammdaten, Vorgabe einmal pro Woche; ein Tag Spielraum für die Uhrzeit der Aufheizung.
DISINFECTION_INTERVAL_DAYS = 7
INTERVAL_SLACK_DAYS = 1
# W6: Wasseraustausch. Steht Trinkwasser länger als 72 h, gilt der Betrieb nicht mehr als bestimmungsgemäß.
STAGNATION_MAX_DAYS = 3.0
# Wert ab dem ersten vollen Tag; Urteil erst, wenn der Zeitraum die 72 h überspannt; Wochenmuster erst nach 7 Tagen
MIN_DRAW_DAYS = 3
FULL_PATTERN_DAYS = 7
SHOWER_LPM = 8.0  # Mischwasser 40 °C je Minute an einer üblichen Dusche
# W1: Arbeitszahl nur Warmwasser, Luft/Wasser im Bestand: Mittel 2,8, Spanne 2,1–3,5 (WP-QS S. 79)
FIELD_DHW_COP, FIELD_DHW_COP_RANGE = 2.8, (2.1, 3.5)
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
    tank_before: float | None = None  # Speichertemperatur, bei der die Ladung startet

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
                          time_mean(outdoor, [(a, b)]), _float(value_at(tank, a))))
    return out


def _float(v) -> float | None:
    return None if v is None else float(v)


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
    lo, hi = FIELD_DHW_COP_RANGE
    text = (f"Gütegrad {num(eta, '.2f')}, Arbeitszahl {num(cop, '.1f')} aus {count(len(metered), 'Ladung', 'Ladungen')} "
            f"mit {num(electricity, '.1f')} kWh Strom (Feldtest nur Warmwasser: Mittel {num(FIELD_DHW_COP, '.1f')}, "
            f"{num(lo, '.1f')}–{num(hi, '.1f')}). ")
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


def regular_disinfection(charges: list[Charge], window_start: float, end: float,
                         interval_days: float) -> tuple[bool | None, float | None]:
    """(regelmäßig?, Tage seit der letzten Aufheizung). None, solange der Zeitraum für ein Urteil zu kurz ist."""
    limit = (interval_days + INTERVAL_SLACK_DAYS) * 86400
    times = sorted(c.start for c in disinfections(charges))
    if not times:
        return (False if end - window_start > limit else None), None
    gaps = [b - a for a, b in zip(times, times[1:])] + [end - times[-1]]
    return all(g <= limit for g in gaps), (end - times[-1]) / 86400


def check_dhw_temperature(charges: list[Charge], since: float, end: float, setpoint: Series,
                          window_charges: list[Charge] | None = None, window_start: float | None = None,
                          interval_days: float | None = None, turnover_days: float | None = None) -> CheckResult:
    """W2: Speichertemperatur nach dem Laden (Median aller Ladungen) gegen die untere Betriebstemperatur (Hygiene)
    und die Grenze, ab der nur noch Strom verloren geht. Seltene Aufheizungen auf 60 °C verschieben den Median kaum;
    ist der Speicher immer auf 60 °C eingestellt, zeigt der Median genau das.

    Unter 50 °C entscheidet, ob der Speicher regelmäßig auf 60 °C aufgeheizt wird (Entscheid F226). Die Aufheizungen
    zählen übers ganze Fenster (window_charges ab window_start): Ein Ereignis ändert nichts an der Hygiene davor."""
    key = ("W2", "dhw_temperature")
    normal = [c.tank_after for c in charges if c.tank_after is not None]
    prog = progress(len(normal), MIN_CHARGES, "charges", RATE, since)
    if len(normal) < MIN_CHARGES:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"{count(len(normal), 'Ladung', 'Ladungen')} mit "
                           f"Speichertemperatur, nötig {MIN_CHARGES}.", origin=SOURCED, progress=prog)
    temp = _median(normal)
    target = time_mean(setpoint, [(since, end)]) if setpoint else None
    interval = interval_days or DISINFECTION_INTERVAL_DAYS
    text = f"Speicher nach dem Laden {num(temp, '.1f')} °C (Median)"
    text += f", eingestellt {num(target, '.0f')} °C. " if target is not None else ". "
    details = {"tank_after_median": round(temp, 1), "setpoint_mean": None if target is None else round(target, 1),
               "interval_days": interval}
    exchange = (f" Der Speicherinhalt wird etwa alle {num(turnover_days, '.1f')} Tage ausgetauscht (W6)."
                if turnover_days is not None else "")
    if temp < HYGIENE_MIN_C - SENSOR_TOLERANCE_K:
        w_start = since if window_start is None else window_start
        regular, last_days = regular_disinfection(window_charges if window_charges is not None else charges,
                                                  w_start, end, interval)
        details["days_since_disinfection"] = None if last_days is None else round(last_days, 1)
        below = (f"Unter {num(HYGIENE_MIN_C, 'g')} °C, der unteren Betriebstemperatur für Ein- und "
                 "Zweifamilienhäuser. ")
        if regular is None:
            need_h = (interval + INTERVAL_SLACK_DAYS) * 24
            return CheckResult(*key, NOT_ASSESSABLE, round(temp, 1), "°C", text + below +
                               f"Ob er regelmäßig auf 60 °C aufgeheizt wird (alle {num(interval, 'g')} Tage), zeigt "
                               "sich erst nach diesem Abstand." + exchange, SOURCED, details,
                               progress=progress((end - w_start) / 3600, need_h, "hours", ELAPSED, w_start))
        if regular:
            verdict = OK
            text += below + (f"Der Speicher wird aber regelmäßig auf 60 °C aufgeheizt (zuletzt vor "
                             f"{num(last_days, '.0f')} Tagen) – das hält Legionellen klein.") + exchange
        else:
            verdict = HINT
            when = (f"Die letzte Aufheizung auf 60 °C liegt {num(last_days, '.0f')} Tage zurück"
                    if last_days is not None else "Eine Aufheizung auf 60 °C war nicht zu sehen")
            text += below + (f"{when}; vorgesehen ist mindestens alle {num(interval, 'g')} Tage. Legionellen "
                             "vermehren sich zwischen 25 und 45 °C.") + exchange
    elif temp > EFFICIENCY_MAX_C + SENSOR_TOLERANCE_K:
        verdict = HINT
        text += (f"Wärmer als die Hygiene verlangt: Jedes Kelvin kostet beim Warmwasser ≈ "
                 f"{num(DHW_PENALTY_PCT_PER_K, 'g')} % Effizienz, und oft hilft dafür der Heizstab.")
    else:
        verdict = OK
        text += "Warm genug für die Hygiene"
        text += (" (knapp an der Untergrenze von 50 °C)." if temp < HYGIENE_MIN_C else
                 ", ohne unnötig Strom zu kosten.")
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
    temps = [c.tank_after for c in charges if c.tank_after is not None]
    if temps and _median(temps) >= DISINFECTION_C - SENSOR_TOLERANCE_K:
        return CheckResult(*key, OK, None, "", "Der Speicher wird bei jeder Ladung auf 60 °C geladen; ob das zu warm "
                           "ist, bewertet W2.", DERIVED, details, progress=prog)
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
        text += ("Häufigkeit unauffällig." if found else
                 "Keine. Vorgeschrieben ist sie im Einfamilienhaus nicht; liegt der Speicher unter 50 °C, "
                 "bewertet W2 das.")
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


def standby_w(windows: list[tuple[float, float, float, float]], volume_l: float | None) -> tuple[float, float] | None:
    """(Bereitschaftsverlust in W, mittlere Speichertemperatur) aus den ruhigen Nachtfenstern."""
    hours = sum(b - a for a, b, _, _ in windows) / 3600
    if not volume_l or len(windows) < MIN_QUIET_WINDOWS or hours < MIN_QUIET_H:
        return None
    drop = sum(t0 - t1 for _, _, t0, t1 in windows)
    tank_mean = sum((t0 + t1) / 2 * (b - a) for a, b, t0, t1 in windows) / (hours * 3600)
    return volume_l * RHO_CP_KJ_PER_L_K * drop / (hours * 3600) * 1000, tank_mean


def check_standby_loss(windows: list[tuple[float, float, float, float]], volume_l: float | None,
                       since: float, charged_kwh_day: float | None = None) -> CheckResult:
    """W4: Bereitschaftsverlust des Speichers aus dem Abkühlen in ruhigen Nachtstunden. charged_kwh_day: Wärme, die
    die Wärmepumpe im Mittel pro Tag in den Speicher lädt (W6); damit sagt der Text, welcher Anteil verloren geht."""
    key = ("W4", "standby_loss")
    hours = sum(b - a for a, b, _, _ in windows) / 3600
    prog = progress(len(windows), MIN_QUIET_WINDOWS, "nights", RATE, since)
    if not volume_l:
        return CheckResult(*key, NOT_ASSESSABLE, text="Stammdaten fehlen: Inhalt des Warmwasserspeichers.",
                           origin=PHYSICAL)
    if len(windows) < MIN_QUIET_WINDOWS or hours < MIN_QUIET_H:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"{count(len(windows), 'ruhige Nacht', 'ruhige Nächte')} "
                           f"({num(hours, '.0f')} h), nötig {MIN_QUIET_WINDOWS} und {num(MIN_QUIET_H, 'g')} h.",
                           origin=PHYSICAL, progress=prog)
    loss_w, tank_mean = standby_w(windows, volume_l)
    delta = tank_mean - ERP_AMBIENT_C
    if delta < MIN_TANK_DELTA_K:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"Speicher nachts nur {num(tank_mean, '.0f')} °C warm; zu wenig "
                           "Unterschied zum Raum für eine Umrechnung.", origin=PHYSICAL, progress=prog)
    loss_45 = loss_w * ERP_DELTA_K / delta
    label, limit = erp_class(loss_45, volume_l), erp_limit_w(volume_l, ERP_OK_CLASS)
    hint_limit = erp_limit_w(volume_l, ERP_HINT_ABOVE_CLASS)
    kwh_day = loss_w * 24 / 1000
    share = 100 * kwh_day / charged_kwh_day if charged_kwh_day else None
    text = (f"Speicher verliert ≈ {num(loss_w, '.0f')} W bei {num(tank_mean, '.0f')} °C, ≈ {num(kwh_day, '.1f')} kWh "
            "Wärme am Tag")
    text += f" – ≈ {num(share, '.0f')} % dessen, was die Wärmepumpe in den Speicher lädt. " if share else ". "
    text += (f"Umgerechnet auf die Prüfbedingung des Energielabels {num(loss_45, '.0f')} W, etwa Klasse {label}. ")
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
                        "hint_above_w": round(hint_limit), "share_pct": None if share is None else round(share, 1),
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


def morning_showers(persons: list[hh.Person], on: date) -> bool:
    """Duscht der Haushalt überwiegend morgens? Gewichtet nach Duschen pro Woche."""
    weights: dict[str, float] = {}
    for p in persons:
        showers, _ = p.habits(on)
        weights[p.shower_time] = weights.get(p.shower_time, 0.0) + showers * (p.share_pct / 100
                                                                              if p.presence == "share" else 1)
    total_w = sum(weights.values())
    return bool(total_w) and weights.get("morning", 0.0) > total_w / 2


def check_dhw_timing(charges: list[Charge], outdoor: Series, since: float, tz: str,
                     persons: list[hh.Person] | None = None) -> CheckResult:
    """W5: Einbuße, weil bei kälterer Luft geladen wird als in den wärmsten drei Stunden desselben Tages (Carnot).

    Ein festes Ladefenster passt nicht zu jedem Haushalt: Wird morgens geduscht, muss der Speicher vom Nachmittag
    bis zum nächsten Morgen reichen. Der Text sagt das, das Urteil bleibt die physikalische Einbuße."""
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
    loss = round(100 * sum(r[0] * r[1] for r in rows) / heat, 1)  # Urteil mit dem angezeigten Wert
    colder = sum(r[0] * r[2] for r in rows) / heat
    text = (f"Geladen wird im Mittel {num(colder, '.1f')} K kälter als in den wärmsten drei Stunden des Tages; das "
            f"kostet beim Warmwasser ≈ {num(loss, '.0f')} % Effizienz (nach Carnot). ")
    if loss >= TIMING_HINT_PCT:
        verdict = HINT
        text += ("Zu einer wärmeren Tageszeit zu laden würde Strom sparen – aber nur, wenn der Vorrat bis zum "
                 "nächsten Duschen reicht (W6).")
    else:
        verdict = OK
        text += ("Kaum Spielraum." if loss < TIMING_HINT_PCT / 2 else
                 "Ein Ladefenster zur wärmeren Tageszeit brächte etwas, die Einbuße ist aber klein.")
    if verdict == HINT and persons and morning_showers(persons, date.fromtimestamp(since)):
        text += (" Bei euch wird überwiegend morgens geduscht: Ein Fenster am Nachmittag geht nur, wenn ein voller "
                 "Speicher bis zum nächsten Morgen reicht; sonst lieber am späten Vormittag nachladen.")
    return CheckResult(*key, verdict, loss, "%", text, DERIVED,
                       {"colder_k": round(colder, 1), "charges": len(rows)}, progress=prog)


@dataclass
class Draw:
    """Was der Haushalt im Mittel pro Tag zapft, aus den geladenen Wärmemengen abzüglich Bereitschaftsverlust."""

    days: float
    charged_kwh_day: float
    standby_kwh_day: float | None
    drawn_kwh_day: float
    mixed_l_day: float  # Mischwasser 40 °C
    tank_l_day: float | None  # Liter, die bei Speichertemperatur aus dem Speicher fließen
    turnover_days: float | None  # so lange dauert es, bis der Speicherinhalt einmal ausgetauscht ist
    tank_c: float | None
    trigger_c: float | None  # Speichertemperatur, bei der nachgeladen wird (Median)
    charge_kw: float | None  # mittlere Ladeleistung der Wärmepumpe


def draw_of(charges: list[Charge], since: float, end: float, volume_l: float | None, standby: float | None,
            cold_c: float = hh.COLD_WATER_C) -> Draw | None:
    """Zapfmenge im Mittel über den Zeitraum. standby: Bereitschaftsverlust in W (W4), ohne ihn zählt alles."""
    span = (end - since) / 86400
    if span <= 0 or not charges:
        return None
    charged = sum(c.heat_kwh for c in charges) / span
    standby_day = standby * 24 / 1000 if standby else None
    drawn = max(0.0, charged - (standby_day or 0.0))
    tanks = [c.tank_after for c in charges if c.tank_after is not None and not c.disinfection]
    tank_c = _median(tanks) if tanks else None
    tank_l_day = hh.tank_l(drawn, tank_c, cold_c) if tank_c is not None else None
    triggers = [c.tank_before for c in charges if c.tank_before is not None]
    duration_h = sum(c.end - c.start for c in charges) / 3600
    return Draw(span, charged, standby_day, drawn, hh.mixed_l(drawn, cold_c), tank_l_day,
                volume_l / tank_l_day if volume_l and tank_l_day else None, tank_c,
                _median(triggers) if triggers else None,
                sum(c.heat_kwh for c in charges) / duration_h if duration_h else None)


def check_dhw_draw(draw: Draw | None, volume_l: float | None, persons: list[hh.Person], dates: list[date],
                   since: float, end: float, cold_c: float = hh.COLD_WATER_C) -> CheckResult:
    """W6: Wie viel Warmwasser der Haushalt braucht, wie oft der Speicherinhalt ausgetauscht wird und wie viele
    Duschen ein voller Speicher hergibt. Urteil nur über den Austausch (Hygiene); der Rest ist Information."""
    key = ("W6", "dhw_draw")
    days_ = (end - since) / 86400
    prog = progress(days_ * 24, MIN_DRAW_DAYS * 24, "hours", ELAPSED, since)
    if not volume_l:
        return CheckResult(*key, NOT_ASSESSABLE, text="Stammdaten fehlen: Inhalt des Warmwasserspeichers.",
                           origin=SOURCED)
    if days_ < 1 or draw is None or draw.turnover_days is None:
        return CheckResult(*key, NOT_ASSESSABLE, text="Wert ab dem ersten vollen Tag mit Ladungen.",
                           origin=SOURCED, progress=prog)
    text = (f"Ihr zapft im Mittel ≈ {num(draw.mixed_l_day, '.0f')} l Duschwasser (40 °C) am Tag; damit ist der "
            f"Speicher etwa alle {num(draw.turnover_days, '.1f')} Tage einmal ausgetauscht. ")
    if days_ < FULL_PATTERN_DAYS:
        text += (f"Vorläufig aus {num(days_, '.1f')} Tagen; Wochentage und Wochenende gleichen sich erst nach "
                 f"{FULL_PATTERN_DAYS} Tagen aus. ")
    expected = hh.expected_mixed_l(persons, dates)
    if expected:
        text += (f"Üblich für Ø {num(hh.persons_mean(persons, dates), '.1f')} Personen im Haushalt wären ≈ "
                 f"{num(expected, '.0f')} l. ")
    else:
        text += "Mit den Personen des Haushalts in den Stammdaten vergleicht das Audit mit dem üblichen Bedarf. "
    if draw.standby_kwh_day is None:
        text += "Bereitschaftsverlust noch unbekannt (W4), die Menge ist daher etwas zu hoch. "
    temps = sorted({round(draw.tank_c or 45.0), 50, 55})
    temps = [x for x in temps if x >= round(draw.tank_c or 45.0)]
    reserve = {x: hh.reserve_mixed_l(volume_l, x, cold_c) for x in temps}
    parts = [f"{num(reserve[x], '.0f')} l bei {x} °C" + (" (heute)" if i == 0 else "")
             for i, x in enumerate(temps)]
    text += (f"Ein voll geladener Speicher gibt ≈ {', '.join(parts)} Duschwasser her, eine Dusche braucht ≈ "
             f"{num(hh.SHOWER_L, 'g')} l. ")
    if draw.trigger_c is not None and draw.charge_kw:
        shower_kw = SHOWER_LPM * RHO_CP_KJ_PER_L_K * (hh.MIXED_C - cold_c) / 60
        text += (f"Nachgeladen wird erst, wenn der Fühler ≈ {num(draw.trigger_c, '.1f')} °C zeigt; dann heizt die "
                 f"Wärmepumpe mit ≈ {num(draw.charge_kw, '.0f')} kW nach, eine laufende Dusche zieht ≈ "
                 f"{num(shower_kw, '.0f')} kW. Mehrere Duschen kurz hintereinander leeren den Speicher deshalb "
                 "schneller, als er nachlädt. ")
    if days_ < MIN_DRAW_DAYS:
        verdict = NOT_ASSESSABLE
        text += f"Ob das Wasser länger als 72 h steht, ist erst nach {MIN_DRAW_DAYS} Tagen bewertbar."
    elif draw.turnover_days <= STAGNATION_MAX_DAYS:
        verdict = OK
    else:
        verdict = HINT
        text += (f"Länger als {num(STAGNATION_MAX_DAYS * 24, '.0f')} h steht Trinkwasser nach den Regeln nicht mehr "
                 "bestimmungsgemäß: regelmäßig auf 60 °C aufheizen; bleibt der Verbrauch dauerhaft so klein, beim nächsten "
                 "Tausch einen kleineren Speicher wählen.")
    details = {"mixed_l_day": round(draw.mixed_l_day), "tank_l_day": None if draw.tank_l_day is None else
               round(draw.tank_l_day), "charged_kwh_day": round(draw.charged_kwh_day, 2),
               "standby_kwh_day": None if draw.standby_kwh_day is None else round(draw.standby_kwh_day, 2),
               "expected_l_day": None if expected is None else round(expected),
               "persons_mean": round(hh.persons_mean(persons, dates), 2) if persons else None,
               "reserve_l": {str(k): round(v) for k, v in reserve.items()},
               "trigger_c": None if draw.trigger_c is None else round(draw.trigger_c, 1),
               "charge_kw": None if draw.charge_kw is None else round(draw.charge_kw, 1)}
    return CheckResult(*key, verdict, round(draw.turnover_days, 1), "d", text.strip(), SOURCED, details,
                       progress=prog)


def daily_point(charges: list[Charge], a: float, b: float, offset_robust: bool) -> dict:
    """Zeitstrahl: Gütegrad der Ladungen eines Tages, mit derselben Ampel wie W1."""
    result = efficiency_of([c for c in charges if a <= c.start < b])
    if result is None:
        return {"value": None, "verdict": NOT_ASSESSABLE}
    eta, cop = result
    return {"value": round(eta, 3), "verdict": carnot_verdict(eta, offset_robust), "cop": round(cop, 2)}
