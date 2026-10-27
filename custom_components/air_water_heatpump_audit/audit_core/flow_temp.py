"""Audit 2 – Vorlauf so niedrig wie möglich (Spezifikation: docs/specification.md, Abschnitt 5).

Herstellerneutral: Alle Prüfungen arbeiten auf Rollen und Stammdaten (Spezifikation 1.6). Fehlt ein Eingang, ist das
Ergebnis „nicht bewertbar“ mit Grund.
"""

from __future__ import annotations

from . import days
from .cycles import Cycle
from .data_basis import resolution
from .heat import time_mean
from .result import (DERIVED, DESCRIPTIVE, FULL_DAYS, HINT, INFO, NOT_ASSESSABLE, OK, PHYSICAL, RATE, SOURCED, WARN,
                     CheckResult, count, grade, num, progress)
from .series import (Interval, Series, combine, intersect, intervals_where, normalize, subtract, total,
                     weighted_values)

SETTLE_S = 600  # Heizbetrieb gilt ab 10 min nach Verdichterstart als eingeschwungen (5.1)
PAUSE_SETTLE_S = 300  # wie D4
PAUSE_MIN_WINDOW_S = 180
MIN_HEATING_S = 3 * 3600
MIN_HEATING_CYCLES = 3
MIN_PAUSE_WINDOWS = 3
ROBUST_PAUSE_WINDOWS = 20  # wie D4 (Entscheid F74)

# T1: Fühlertoleranz ±0,5–1 K je Fühler (SIKA VVX, Huba 210) → unter 1,5 K nicht unterscheidbar; ISE-HPC-2026 misst im
# Mittel bis 2,5 K; über 4 K ≈ 8–12 % Mehrverbrauch. Rot nur mit abgeglichenen Fühlern (T2 belastbar).
LOSS_OK_K, LOSS_HINT_K = 1.5, 4.0
COP_PER_K = (0.02, 0.03)  # 2–3 % COP je Kelvin (BINE-2013, MEDB, VDZ-Leitfaden S. 8)
OFFSET_HINT_K = 1.0  # T2, wie D4
RATIO_MIN_DIFF_K = 2.0  # T3: kleinere Differenzen gibt die Fühlerauflösung nicht her
RETURN_MATCH_K = 0.5  # T3: WP-Rücklauf ≈ Heizkreis-Rücklauf → Fall „Heizkreis fördert mehr“
SPREAD_FIELD_K = 5.5  # T4, ISE-WPsmart-2020 S. 67 (3,0–7,8 K); heatpumpmonitor.org Median 3,2 K
SPREAD_HINT_K = 10.0  # T4, VDI 4645 laut VDZ-Leitfaden Tab. T6; kleine Spreizung ist kein Mangel
FLOW_MIN_MARGIN_LPM, FLOW_MIN_MARGIN_SHARE = 1.5, 0.10  # T4: Messtoleranz Durchflusssensoren (SIKA, Huba)
ROOM_ABOVE_K, ROOM_BELOW_K = 1.0, 0.5  # T6: Regelgenauigkeit Raumregler 0,5 K (EN 15500)
ROOM_ABOVE_SHARE = 5 / 7  # T6: an ≥ 5 von 7 Heiztagen
MIN_ROOM_DAYS = 5
HEATING_DAY_MIN_S = 3600  # ein Tag zählt als Heiztag ab 1 h Heizbetrieb
ROOM_DAY_MIN_SHARE = 0.9  # T6: Raumfühler misst seit mindestens 90 % des Tags (sonst nur Teil des Tagesgangs)

SEPARATING = ("parallel_buffer", "hydraulic_separator")
NOT_SEPARATING = ("none", "series_buffer")


def _on(v) -> bool:
    return v in (1, 1.0, True, "on")


def _missing(check_id: str, key: str, what: str) -> CheckResult:
    return CheckResult(check_id, key, NOT_ASSESSABLE, text=f"Eingang fehlt: {what}.", origin=DESCRIPTIVE,
                       details={"missing_input": True})


def heating_windows(cycles: list[Cycle], defrost: Series, dhw: Series, circuit_pump: Series, artifacts: list[Interval],
                    start: float, end: float) -> tuple[list[Interval], int]:
    """Stationärer Heizbetrieb: Verdichter ≥ 10 min an, kein Warmwasser, keine Abtauung, keine Artefakte.

    Liefert die Intervalle und die Zahl der Zyklen, die etwas beitragen.
    """
    exclude = intervals_where(defrost, _on, start, end) + intervals_where(dhw, _on, start, end) + list(artifacts)
    pump = intervals_where(circuit_pump, _on, start, end) if circuit_pump else None
    out: list[Interval] = []
    used = 0
    for c in cycles:
        if c.open_start or c.end - c.start <= SETTLE_S:
            continue  # beim offenen Start ist unbekannt, wann der Verdichter anlief
        part = subtract([(c.start + SETTLE_S, c.end)], exclude)
        if pump is not None:
            part = intersect(part, pump)
        if total(part) > 0:
            used += 1
            out += part
    return normalize(out), used


def pause_windows(compressor: Series, pump: Series, defrost: Series, dhw: Series, start: float,
                  end: float) -> list[Interval]:
    """Verdichter seit ≥ 5 min aus, WP-Pumpe an, kein Warmwasser, keine Abtauung (wie D4)."""
    off = intervals_where(compressor, lambda v: not _on(v), start, end)
    settled = [(a + PAUSE_SETTLE_S, b) for a, b in off if b - a > PAUSE_SETTLE_S]
    windows = intersect(settled, intervals_where(pump, _on, start, end))
    windows = subtract(windows, intervals_where(defrost, _on, start, end) + intervals_where(dhw, _on, start, end))
    return [w for w in windows if w[1] - w[0] >= PAUSE_MIN_WINDOW_S]


def _diff(a: Series, b: Series, start: float, end: float) -> Series:
    return combine(a, b, lambda x, y: float(x) - float(y), start, end)


HEATING_GATED = ("T1", "T3", "T4", "T5")  # Prüfungen mit Mindestmenge stationärer Heizbetrieb (_heating_gate)


def heating_progress(windows: list[Interval], used: int, since: float) -> dict:
    """Datenreife für T1/T3–T5: die knappere der beiden Bedingungen (Stunden oder Zyklen)."""
    hours, cycles = total(windows) / 3600, used
    if hours / (MIN_HEATING_S / 3600) <= cycles / MIN_HEATING_CYCLES:
        return progress(hours, MIN_HEATING_S / 3600, "heating_hours", RATE, since)
    return progress(cycles, MIN_HEATING_CYCLES, "cycles", RATE, since)


def _heating_gate(windows: list[Interval], used: int) -> str | None:
    if total(windows) < MIN_HEATING_S or used < MIN_HEATING_CYCLES:
        return (f"{num(total(windows) / 3600, '.1f')} h stationärer Heizbetrieb aus {count(used, 'Zyklus', 'Zyklen')}, nötig "
                f"{num(MIN_HEATING_S / 3600, '.0f')} h aus {MIN_HEATING_CYCLES} Zyklen.")
    return None


def check_circuit_sensor_offset(flow: Series, circuit_flow: Series, pauses: list[Interval], start: float,
                                end: float) -> CheckResult:
    """T2: WP-Vorlauf − Heizkreis-Vorlauf in Pausen mit Umwälzung (beide Fühler sehen dann fast dasselbe Wasser)."""
    if not circuit_flow:
        return _missing("T2", "circuit_sensor_offset", "Heizkreis-Vorlauf")
    diff = _diff(flow, circuit_flow, start, end)
    details = {"windows": len(pauses), "robust": len(pauses) >= ROBUST_PAUSE_WINDOWS}
    prog = progress(len(pauses), ROBUST_PAUSE_WINDOWS, "windows", RATE, start)  # reif erst, wenn belastbar
    if len(pauses) < MIN_PAUSE_WINDOWS:
        return CheckResult("T2", "circuit_sensor_offset", NOT_ASSESSABLE,
                           text=f"{count(len(pauses), 'Pause', 'Pausen')} mit laufender Pumpe, nötig {MIN_PAUSE_WINDOWS}.",
                           origin=PHYSICAL, details=details, progress=prog)
    offset = time_mean(diff, pauses)  # Zeitmittel statt Median, wie D4 (0,5-K-Schritte)
    # Fühler melden in 0,5-K-Schritten und haben je ±0,5–1 K Toleranz → Unterschiede bis 1 K sind „gleich“
    shown = f"{num(offset, '+.1f')} K"
    if abs(offset) > OFFSET_HINT_K:
        verdict = HINT
        text = (f"In {len(pauses)} Verdichterpausen unterscheiden sich die beiden Vorlauffühler im Mittel um {shown}. "
                "Das ist mehr als die Fühlertoleranz: Fühler prüfen, der Pufferverlust (T1) ist unsicher.")
    else:
        verdict = OK
        text = (f"Die beiden Vorlauffühler stimmen überein (im Mittel {shown} in {len(pauses)} Verdichterpausen, "
                f"innerhalb der Fühlertoleranz).")
    if not details["robust"]:
        text += f" Vorläufig, belastbar ab {ROBUST_PAUSE_WINDOWS} Pausen."
    return CheckResult("T2", "circuit_sensor_offset", verdict, round(offset, 2), "K", text, PHYSICAL, details,
                       progress=prog)


def check_buffer_flow_loss(flow: Series, circuit_flow: Series, separation: str | None, windows: list[Interval],
                           used: int, sensor_offset: CheckResult, start: float, end: float) -> CheckResult:
    """T1: Wie viel wärmer erzeugt die WP, als im Heizkreis ankommt?"""
    if separation in NOT_SEPARATING:
        return CheckResult("T1", "buffer_flow_loss", INFO, text="Trifft für diese Hydraulik nicht zu "
                           "(kein paralleler Puffer und keine hydraulische Weiche).", origin=DESCRIPTIVE,
                           details={"not_applicable": True})
    if not circuit_flow:
        return _missing("T1", "buffer_flow_loss", "Heizkreis-Vorlauf (Fühler hinter Puffer oder Weiche)")
    if not flow:
        return _missing("T1", "buffer_flow_loss", "Vorlauf der Wärmepumpe")
    if (reason := _heating_gate(windows, used)) is not None:
        return CheckResult("T1", "buffer_flow_loss", NOT_ASSESSABLE, text=reason, origin=DERIVED)
    raw = time_mean(_diff(flow, circuit_flow, start, end), windows)
    robust = bool(sensor_offset.details.get("robust")) and sensor_offset.value is not None
    correction = sensor_offset.value if robust else 0.0
    loss = raw - correction
    verdict = grade(loss, LOSS_OK_K, LOSS_HINT_K)
    capped = verdict == WARN and not robust
    if capped:
        verdict = HINT  # ohne Fühlerabgleich könnte ein Teil der Differenz Messfehler sein
    lo, hi = (max(loss, 0) * k * 100 for k in COP_PER_K)
    text = (f"Im Heizbetrieb liegt der Vorlauf der Wärmepumpe im Mittel {num(loss, '.1f')} K über dem Vorlauf im "
            f"Heizkreis. Die Wärmepumpe arbeitet damit wärmer als nötig, das kostet grob "
            f"{num(lo, '.0f')}–{num(hi, '.0f')} % Effizienz.")
    if verdict != OK:
        text += " Häufige Ursache: Die Heizkreispumpe fördert mehr Wasser als die Wärmepumpe (siehe T3)."
    if robust:
        text += f" Fühlerunterschied aus T2 ({num(correction, '+.1f')} K) abgezogen, die Fühler sind abgeglichen."
    elif sensor_offset.verdict != NOT_ASSESSABLE:
        text += " Fühlerunterschied (T2) noch vorläufig, nicht abgezogen."
    if capped:
        text += " Höchstens gelb, bis die Fühler über T2 abgeglichen sind."
    details = {"raw_k": round(raw, 2), "correction_k": correction, "heating_h": round(total(windows) / 3600, 1),
               "cycles": used, "cop_loss_pct": [round(lo, 1), round(hi, 1)]}
    return CheckResult("T1", "buffer_flow_loss", verdict, round(loss, 2), "K", text, DERIVED, details)


def check_flow_ratio(flow: Series, ret: Series, circuit_flow: Series, circuit_ret: Series, flow_rate: Series,
                     windows: list[Interval], used: int, start: float, end: float,
                     circuit_max_lpm: float | None = None) -> CheckResult:
    """T3: Volumenstromverhältnis Heizkreis ÷ WP aus der Mischungsbilanz (research_flow_temp.md 2.2).

    Mit `circuit_max_lpm` (größter Förderstrom der Heizkreispumpe) wird die Schätzung auf das physikalisch
    Mögliche gekappt: Bei kleiner Heizkreis-Spreizung überschätzt die Mischungsbilanz leicht.
    """
    if not circuit_flow or not circuit_ret:
        return _missing("T3", "flow_ratio", "Heizkreis-Vorlauf und -Rücklauf")
    if (reason := _heating_gate(windows, used)) is not None:
        return CheckResult("T3", "flow_ratio", NOT_ASSESSABLE, text=reason, origin=PHYSICAL)
    hk_spread = time_mean(_diff(circuit_flow, circuit_ret, start, end), windows)
    lift = time_mean(_diff(flow, circuit_ret, start, end), windows)
    ret_diff = time_mean(_diff(ret, circuit_ret, start, end), windows)
    details = {"circuit_spread_k": round(hk_spread, 2), "flow_minus_circuit_return_k": round(lift, 2),
               "return_minus_circuit_return_k": round(ret_diff, 2)}
    if ret_diff > RETURN_MATCH_K:
        return CheckResult("T3", "flow_ratio", INFO, None, "", "Der Rücklauf der Wärmepumpe ist wärmer als der des "
                           "Heizkreises: Die Wärmepumpe fördert mehr Wasser als der Heizkreis, ein Teil ihres Vorlaufs "
                           "fließt direkt zurück.", PHYSICAL, details)
    if lift < RATIO_MIN_DIFF_K or hk_spread <= 0:
        return CheckResult("T3", "flow_ratio", NOT_ASSESSABLE, text="Die Temperaturunterschiede sind zu klein für die "
                           "Auflösung der Fühler.", origin=PHYSICAL, details=details)
    ratio = lift / hk_spread  # V_HK / V_WP
    wp_lpm = time_mean(flow_rate, windows) if flow_rate else None
    capped_from = None
    if circuit_max_lpm and wp_lpm and wp_lpm * ratio > circuit_max_lpm:
        capped_from = wp_lpm * ratio
        ratio = circuit_max_lpm / wp_lpm
        details |= {"estimate_lpm": round(capped_from), "circuit_max_lpm": circuit_max_lpm}
    text = (f"Der Heizkreis fördert {'höchstens' if capped_from else 'etwa'} {num(ratio, '.1f')}-mal so viel Wasser "
            "wie die Wärmepumpe")
    if wp_lpm:
        details["heat_pump_lpm"] = round(wp_lpm, 1)
        details["circuit_lpm"] = round(wp_lpm * ratio)
        text += f" ({'höchstens' if capped_from else '≈'} {num(wp_lpm * ratio, '.0f')} statt {num(wp_lpm, '.0f')} l/min)"
    text += "."
    if ratio > 1:
        if wp_lpm:
            text += (f" Die Wärmepumpe liefert {num(wp_lpm, '.0f')} l/min warmes Wasser in den Puffer, der Heizkreis "
                     f"zieht {'bis zu' if capped_from else 'etwa'} {num(wp_lpm * ratio, '.0f')} l/min ab; "
                     f"{'bis zu ' if capped_from else 'die fehlenden '}{num(wp_lpm * (ratio - 1), '.0f')} l/min strömen als kühles Rücklaufwasser im Puffer nach "
                     "oben und mischen sich in den Vorlauf.")
        else:
            text += " Dabei wird kühles Rücklaufwasser in den Vorlauf gemischt."
        text += " Das erklärt den Pufferverlust (T1)."
        if capped_from:
            text += (f" Die Mischungsbilanz ergäbe ≈ {num(capped_from, '.0f')} l/min, mehr als die Heizkreispumpe "
                     f"schafft ({num(circuit_max_lpm, 'g')} l/min laut Stammdaten); angezeigt ist diese Grenze. "
                     f"Die Spreizung im Heizkreis ist nur {num(hk_spread, '.1f')} K, die Fühler lösen in Schritten auf.")
        else:
            text += (" Sicher ist die Größenordnung, nicht die genaue Zahl: Die Spreizung im Heizkreis ist nur "
                     f"{num(hk_spread, '.1f')} K, die Fühler lösen in Schritten auf.")
    return CheckResult("T3", "flow_ratio", INFO, round(ratio, 1), "×", text, PHYSICAL, details)


def check_heat_pump_spread(flow: Series, ret: Series, flow_rate: Series, flow_rate_min: float | None,
                           windows: list[Interval], used: int, start: float, end: float) -> CheckResult:
    """T4: Spreizung und Durchfluss der Wärmepumpe im Heizbetrieb."""
    if not flow or not ret:
        return _missing("T4", "heat_pump_spread", "Vor- und Rücklauf der Wärmepumpe")
    if (reason := _heating_gate(windows, used)) is not None:
        return CheckResult("T4", "heat_pump_spread", NOT_ASSESSABLE, text=reason, origin=SOURCED)
    spread = time_mean(_diff(flow, ret, start, end), windows)
    verdict = OK
    notes = [f"Spreizung der Wärmepumpe im Heizbetrieb {num(spread, '.1f')} K (Feldmittel bei Bestandsanlagen "
             f"{num(SPREAD_FIELD_K, '.1f')} K)."]
    if spread > SPREAD_HINT_K:
        verdict = HINT
        notes.append(f"Über {num(SPREAD_HINT_K, '.0f')} K: zu wenig Durchfluss, die Wärmepumpe muss den Vorlauf "
                     "höher fahren.")
    details = {"spread_k": round(spread, 2)}
    if flow_rate:
        lpm = time_mean(flow_rate, windows)
        step = resolution(flow_rate) or 1.0
        details |= {"flow_lpm": round(lpm, 1), "flow_resolution_lpm": step}
        if flow_rate_min:
            details["flow_min_lpm"] = flow_rate_min
            margin = max(FLOW_MIN_MARGIN_LPM, FLOW_MIN_MARGIN_SHARE * flow_rate_min, step)
            details["flow_margin_lpm"] = round(margin, 1)
            if lpm < flow_rate_min - margin:
                verdict = HINT
                notes.append(f"Durchfluss {num(lpm, '.1f')} l/min liegt unter dem Herstellerminimum von "
                             f"{num(flow_rate_min, 'g')} "
                             "l/min: Filter, Schmutzfänger und Pumpenstufe prüfen lassen.")
            elif lpm < flow_rate_min:
                notes.append(f"Durchfluss {num(lpm, '.1f')} l/min liegt an der Untergrenze des Herstellers "
                             f"({num(flow_rate_min, 'g')} l/min), innerhalb der Messgenauigkeit der Durchflusssensoren "
                             f"(±{num(margin, '.1f')} l/min). Beobachten, kein Handlungsbedarf.")
            else:
                notes.append(f"Durchfluss {num(lpm, '.1f')} l/min (Herstellerminimum {num(flow_rate_min, 'g')} l/min).")
        else:
            notes.append(f"Durchfluss {num(lpm, '.1f')} l/min. Herstellerminimum nicht in den Stammdaten, "
                         "daher nicht bewertet.")
    return CheckResult("T4", "heat_pump_spread", verdict, round(spread, 2), "K", " ".join(notes), SOURCED, details)


def check_flow_vs_setpoint(flow: Series, circuit_flow: Series, setpoint: Series, windows: list[Interval], used: int,
                           start: float, end: float) -> CheckResult:
    """T5: Ist gegen Soll, getrennt für WP-Vorlauf und Heizkreis-Vorlauf."""
    if not setpoint:
        return _missing("T5", "flow_vs_setpoint", "Soll-Vorlauf")
    if (reason := _heating_gate(windows, used)) is not None:
        return CheckResult("T5", "flow_vs_setpoint", NOT_ASSESSABLE, text=reason, origin=DESCRIPTIVE)
    soll = time_mean(setpoint, windows)
    wp = time_mean(_diff(flow, setpoint, start, end), windows)
    details = {"setpoint_c": round(soll, 1), "heat_pump_minus_setpoint_k": round(wp, 2)}
    text = f"Soll-Vorlauf im Mittel {num(soll, '.1f')} °C. Die Wärmepumpe liefert {num(wp, '+.1f')} K dazu"
    if circuit_flow:
        hk = time_mean(_diff(circuit_flow, setpoint, start, end), windows)
        details["circuit_minus_setpoint_k"] = round(hk, 2)
        text += f", im Heizkreis kommen {num(hk, '+.1f')} K an"
        if abs(hk) < abs(wp):
            text += ". Die Steuerung regelt offenbar auf den Heizkreis-Fühler; den Aufschlag trägt die Wärmepumpe"
    text += "."
    return CheckResult("T5", "flow_vs_setpoint", INFO, round(wp, 2), "K", text, DESCRIPTIVE, details)


def check_heating_curve_headroom(room: Series, target: float | None, heating: list[Interval], start: float,
                                 end: float, tz: str = days.DEFAULT_TZ) -> CheckResult:
    """T6: Kritischster Raum gegen Ziel-Raumtemperatur an Heiztagen."""
    if not room:
        return CheckResult("T6", "heating_curve_headroom", NOT_ASSESSABLE,
                           text="Raumfühler fehlt. Ohne Raumtemperatur lässt sich nicht sagen, ob die Heizkurve "
                                "tiefer könnte.", origin=DERIVED)
    if target is None:
        return CheckResult("T6", "heating_curve_headroom", NOT_ASSESSABLE,
                           text="Ziel-Raumtemperatur fehlt in den Stammdaten.", origin=DERIVED)
    means = []
    first = room[0][0]  # HA speichert gleichbleibende Werte nicht neu → abgedeckt ist alles ab dem ersten Messwert
    for a, b in days.full_days(start, end, tz):
        if b - max(a, first) < ROOM_DAY_MIN_SHARE * (b - a):
            continue
        if total(intersect(heating, [(a, b)])) >= HEATING_DAY_MIN_S:
            m = time_mean(room, [(a, b)])
            if m is not None:
                means.append((days.label(a, tz), round(m, 1)))
    details = {"days": means, "target_c": target}
    prog = progress(len(means), MIN_ROOM_DAYS, "heating_days", FULL_DAYS, start)
    if len(means) < MIN_ROOM_DAYS:
        return CheckResult("T6", "heating_curve_headroom", NOT_ASSESSABLE,
                           text=f"{count(len(means), 'Heiztag', 'Heiztage')} mit Raumtemperatur, nötig {MIN_ROOM_DAYS}.", origin=DERIVED,
                           details=details, progress=prog)
    values = [m for _, m in means]
    lowest = min(values)
    warm = sum(1 for v in values if v >= target + ROOM_ABOVE_K)
    details["warm_days"] = warm
    if warm >= ROOM_ABOVE_SHARE * len(values) and lowest >= target - ROOM_BELOW_K:
        verdict, text = HINT, (f"Der Raum war an {warm} von {len(values)} Heiztagen mindestens "
                               f"{num(ROOM_ABOVE_K, 'g')} K wärmer als das Ziel {num(target, 'g')} °C "
                               f"(kältester Tag {num(lowest, '.1f')} °C). Die Heizkurve hat Reserve: "
                               "um 1 K absenken und ein bis zwei Tage beobachten.")
    elif any(v < target - ROOM_BELOW_K for v in values):
        verdict, text = INFO, (f"An einzelnen Tagen lag der Raum unter dem Ziel {num(target, 'g')} °C (kältester Tag "
                               f"{num(lowest, '.1f')} °C). Die Heizkurve ist knapp, nicht weiter absenken.")
    else:
        verdict, text = OK, (f"Der Raum liegt an Heiztagen nahe am Ziel {num(target, 'g')} °C "
                             f"(kältester Tag {num(lowest, '.1f')} °C).")
    return CheckResult("T6", "heating_curve_headroom", verdict, lowest, "°C", text, DERIVED, details, progress=prog)
