"""Audit 0 – Datenbasis (Spezifikation: docs/heatpump_audit_spec.md, Abschnitt 2)."""

from __future__ import annotations

from . import days
from .heat import time_mean
from .result import (DERIVED, FULL_DAYS, INFO, NOT_ASSESSABLE, OK, HINT, RATE, WARN, PHYSICAL, SOURCED, CheckResult,
                     grade, num, progress)
from .series import (Interval, Series, clip, combine, dedupe, intersect, intervals_where, normalize, subtract,
                     total, value_at, weighted_values)

HEARTBEAT_MAX_GAP_S = 180
ARTIFACT_MARGIN_S = 30
OFFSET_SETTLE_S = 300
OFFSET_MIN_WINDOW_S = 180
OFFSET_MIN_WINDOWS = 3
OFFSET_ROBUST_WINDOWS = 20  # ab hier gilt der Offset als belastbar (Entscheid F74)
RESOLUTION_LABELS = {"flow_temp": "Vorlauf {} K", "return_temp": "Rücklauf {} K", "flow_rate": "Durchfluss {} l/min",
                     "outdoor_temp": "Außentemperatur {} K"}
RESOLUTION_STEPS = (0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0)


def heartbeat_gaps(heartbeat: Series, start: float, end: float, max_gap: float = HEARTBEAT_MAX_GAP_S) -> list[Interval]:
    """Zeiträume ohne Lebenszeichen länger als max_gap, inklusive Anfang und Ende des Fensters."""
    times = [start] + [t for t, _ in heartbeat if start < t < end] + [end]
    return [(a, b) for a, b in zip(times, times[1:]) if b - a > max_gap]


def restarts(uptime: Series) -> list[Interval]:
    """Neustarts des Datensammlers: Betriebszeit fällt. Liefert je Neustart (geschätzter Boot, erster neuer Wert)."""
    out: list[Interval] = []
    for (t0, v0), (t1, v1) in zip(uptime, uptime[1:]):
        if float(v1) < float(v0):
            out.append((t1 - float(v1), t1))
    return out


def artifact_windows(uptime: Series, start: float, end: float) -> list[Interval]:
    """Zeiträume, in denen Zustandswechsel unzuverlässig sind: Neustarts und Heartbeat-Lücken, je ±30 s."""
    raw = restarts(uptime) + heartbeat_gaps(uptime, start, end)
    return normalize((a - ARTIFACT_MARGIN_S, b + ARTIFACT_MARGIN_S) for a, b in raw)


def check_coverage(uptime: Series, start: float, end: float) -> CheckResult:
    """D2: Anteil des Zeitraums mit lückenlosem Heartbeat."""
    gaps = heartbeat_gaps(uptime, start, end)
    share = 1 - total(gaps) / (end - start)
    verdict = OK if share >= 0.98 else HINT if share >= 0.90 else WARN
    return CheckResult("D2", "coverage", verdict, round(share * 100, 1), "%",
                       f"{len(gaps)} Lücke(n) > {HEARTBEAT_MAX_GAP_S} s, zusammen {num(total(gaps) / 60, '.0f')} min.",
                       DERIVED, {"gaps": gaps})


def resolution(series: Series, share: float = 0.98) -> float | None:
    """Größte Schrittweite aus RESOLUTION_STEPS, auf die mindestens `share` der Werte fallen."""
    values = [float(v) for _, v in series]
    if not values:
        return None
    for step in sorted(RESOLUTION_STEPS, reverse=True):
        on_grid = sum(1 for v in values if abs(v / step - round(v / step)) < 1e-6)
        if on_grid / len(values) >= share:
            return step
    return None


def check_resolution(inputs: dict[str, Series], flow: Series, ret: Series, running: list[Interval],
                     start: float, end: float, min_values: int = 50) -> CheckResult:
    """D3: tatsächliche Auflösung je Eingang; Quantisierungsfehler von ΔT relativ zur mittleren Spreizung.

    HA speichert nur Änderungen; ruhige Eingänge (Durchfluss) erreichen min_values erst nach Tagen und fehlen bis dahin.
    """
    steps = {name: resolution(s) for name, s in inputs.items() if len(s) >= min_values}
    if not steps:
        return CheckResult("D3", "resolution", NOT_ASSESSABLE, text=f"Weniger als {min_values} Werte je Eingang.",
                           origin=PHYSICAL)
    details: dict = {"steps": steps}
    text = "Auflösung " + ", ".join(RESOLUTION_LABELS.get(k, k + " {}").format(num(v, "g"))
                                    for k, v in steps.items() if v is not None)
    step_t = max(steps.get("flow_temp") or 0, steps.get("return_temp") or 0)
    dt_pairs = weighted_values(combine(flow, ret, lambda a, b: float(a) - float(b), start, end), running)
    weight = sum(w for _, w in dt_pairs)
    if step_t and weight:
        mean_dt = sum(float(v) * w for v, w in dt_pairs) / weight
        if mean_dt > 0:
            # Zwei Fühler mit je ±step/2 → ΔT bis ±step je Einzelwert.
            details["mean_delta_t_running"] = round(mean_dt, 2)
            details["heat_uncertainty_pct"] = round(100 * step_t / mean_dt, 1)
            text += (f". Mittlere Spreizung bei laufendem Verdichter {num(mean_dt, '.1f')} K → "
                     f"Wärme je Einzelwert bis ±{num(details['heat_uncertainty_pct'], '.0f')} %.")
    return CheckResult("D3", "resolution", INFO, steps, "", text, PHYSICAL, details)


def check_sensor_offset(flow: Series, ret: Series, compressor: Series, pump: Series, defrost: Series,
                        dhw: Series, start: float, end: float) -> CheckResult:
    """D4: Offset Vorlauf − Rücklauf bei laufender Pumpe und seit ≥ 5 min stehendem Verdichter."""
    on = lambda v: v in (1, 1.0, True, "on")
    comp_off = intervals_where(compressor, lambda v: not on(v), start, end)
    settled = [(a + OFFSET_SETTLE_S, b) for a, b in comp_off if b - a > OFFSET_SETTLE_S]
    windows = intersect(settled, intervals_where(pump, on, start, end))
    windows = subtract(windows, intervals_where(defrost, on, start, end) + intervals_where(dhw, on, start, end))
    windows = [w for w in windows if w[1] - w[0] >= OFFSET_MIN_WINDOW_S]
    diff = combine(flow, ret, lambda a, b: float(a) - float(b), start, end)
    per_window = [time_mean(diff, [w]) for w in windows]
    details = {"windows": windows, "per_window": per_window}
    # Datenreife erst mit belastbarem Offset (Entscheid F74), nicht schon mit dem ersten Wert
    prog = progress(len(windows), OFFSET_ROBUST_WINDOWS, "windows", RATE, start)
    if len(windows) < OFFSET_MIN_WINDOWS:
        return CheckResult("D4", "sensor_offset", NOT_ASSESSABLE,
                           text=f"{len(windows)} geeignete Fenster, nötig {OFFSET_MIN_WINDOWS}.",
                           origin=DERIVED, details=details, progress=prog)
    # Zeitmittel statt Median: die Fühler melden in 0,5-K-Schritten, ein Median rastet auf 0 oder 0,5 K ein.
    offset = round(time_mean(diff, windows), 2)
    verdict = grade(abs(offset), 0.5, 1.0)
    details["robust"] = len(windows) >= OFFSET_ROBUST_WINDOWS
    text = f"Mittel Vorlauf − Rücklauf in {len(windows)} Fenstern ohne Verdichter: {num(offset, '+.2f')} K."
    if not details["robust"]:
        text += f" Vorläufig, belastbar ab {OFFSET_ROBUST_WINDOWS} Fenstern."
    return CheckResult("D4", "sensor_offset", verdict, offset, "K", text, DERIVED, details, progress=prog)


def check_meter_resolution(meter: Series, min_values: int = 10) -> CheckResult:
    """D8: Schrittweite der Zählerstände."""
    if len(meter) < min_values:
        return CheckResult("D8", "meter_resolution", NOT_ASSESSABLE, text=f"Weniger als {min_values} Zählerstände.",
                           origin=PHYSICAL)
    step = resolution(meter)
    verdict = OK if step is not None and step <= 0.1 else HINT
    text = f"Zählerstände in Schritten von {num(step, 'g')} kWh."
    if verdict == HINT:
        text += " Tageswerte sind auf ±1 Schritt unsicher (viele Zähler liefern ohne Freischaltung per PIN nur ganze kWh)."
    return CheckResult("D8", "meter_resolution", verdict, step, "kWh", text, PHYSICAL)


def check_restarts(uptime: Series, start: float, end: float) -> CheckResult:
    """D9: Neustarts des Datensammlers je Tag."""
    found = [r for r in restarts(clip(uptime, start, end)) if start <= r[1] < end]
    days = (end - start) / 86400
    per_day = len(found) / days
    # Unter einem Tag wird nicht hochgerechnet: ein einzelner Neustart ergäbe sonst eine hohe Tagesrate.
    verdict = HINT if days >= 1 and per_day > 3 else INFO
    return CheckResult("D9", "restart_artifacts", verdict, round(per_day, 2), "1/d",
                       f"{len(found)} Neustart(s) im Zeitraum; Zustandswechsel ±{ARTIFACT_MARGIN_S} s darum werden verworfen.",
                       DERIVED, {"restarts": found})


def check_history_depth(recorder_keep_days: float | None, long_term_days: float | None) -> CheckResult:
    """D1: Rohdatentiefe. long_term_days = Tage in einer Langzeitquelle (InfluxDB), None ohne Anbindung."""
    best = round(long_term_days if long_term_days is not None else (recorder_keep_days or 0), 1)
    if long_term_days is not None or (recorder_keep_days or 0) >= 30:
        verdict, text = OK, "Langzeitdaten vorhanden."
    elif (recorder_keep_days or 0) >= 7:
        verdict, text = HINT, (f"Nur Recorder mit {num(recorder_keep_days, 'g')} Tagen Rohdaten. Für Monatsvergleiche "
                               "Aufbewahrung erhöhen; dafür Datenträger (USB-SSD) statt Speicherkarte/Stick.")
    else:
        verdict, text = WARN, "Weniger als 7 Tage Rohdaten, Audit 3 nicht rechenbar."
    return CheckResult("D1", "history_depth", verdict, best, "d", text, DERIVED,
                       {"recorder_keep_days": recorder_keep_days, "long_term_days": long_term_days})


def check_meter_vs_controller(meter: Series, controller_consumed: list[Series], uptime: Series, start: float, end: float,
                       tz: str = days.DEFAULT_TZ, min_days: int = 7) -> CheckResult:
    """D5: Strom laut Steuerung ÷ Zählerstrom über volle Tage mit lückenlosem Heartbeat.

    Rolle = Verbrauch des Vortags, wie ihn die Steuerung um ihre Mitternacht meldet; der für Tag D gültige Wert steht
    deshalb sicher erst am Mittag von D+1.
    """
    rows = []
    for a, b in days.full_days(start, end, tz):
        if check_coverage(uptime, a, b).verdict != OK:
            continue
        m_a, m_b = value_at(meter, a), value_at(meter, b)
        ctrl = [value_at(s, b + 12 * 3600) for s in controller_consumed]
        if None in (m_a, m_b) or None in ctrl or b + 12 * 3600 > end:
            continue
        rows.append({"day": days.label(a, tz), "meter_kwh": round(float(m_b) - float(m_a), 2),
                     "controller_kwh": round(sum(float(x) for x in ctrl), 2)})
    # Der Wert der Steuerung für einen Tag steht erst am Mittag danach: ein Tag wird 12 h nach seiner Mitternacht zählbar.
    prog = progress(len(rows), min_days, "days", FULL_DAYS, start, lag_h=12)
    if len(rows) < min_days:
        return CheckResult("D5", "meter_vs_controller", NOT_ASSESSABLE, text=f"{len(rows)} vergleichbare Tage, nötig {min_days}.",
                           origin=DERIVED, details={"days": rows}, progress=prog)
    meter_sum = sum(r["meter_kwh"] for r in rows)
    ctrl_sum = sum(r["controller_kwh"] for r in rows)
    ratio = ctrl_sum / meter_sum if meter_sum else float("inf")
    verdict = OK if 0.95 <= ratio <= 1.20 else WARN if ratio < 0.80 or ratio > 1.50 else HINT
    return CheckResult("D5", "meter_vs_controller", verdict, round(ratio, 3), "",
                       f"Steuerung {num(ctrl_sum, '.1f')} kWh gegen Zähler {num(meter_sum, '.1f')} kWh an {len(rows)} Tagen.",
                       DERIVED,
                       {"days": rows}, progress=prog)


def check_controller_day_boundary(controller_date: Series, start: float, end: float,
                           tz: str = days.DEFAULT_TZ, window_s: float = 3 * 3600) -> CheckResult:
    """D6: Wechselt das Datum der Steuerung zur lokalen Mitternacht? Versatz = Wechselzeit − Mitternacht."""
    changes = [t for t, _ in dedupe(controller_date)[1:]]
    offsets = []
    for m in days.midnights(start, end, tz):
        near = [t for t in changes if abs(t - m) <= window_s]
        if near:
            offsets.append(round((near[0] - m) / 60, 1))
    if not offsets:
        return CheckResult("D6", "controller_day_boundary", NOT_ASSESSABLE,
                           text="Noch kein Tageswechsel der Steuerung im Zeitraum.",
                           origin=SOURCED)
    worst = max(offsets, key=abs)
    verdict = OK if abs(worst) <= 15 else HINT
    text = f"Datum der Steuerung wechselt {num(worst, '+.0f')} min gegen lokale Mitternacht ({len(offsets)} Wechsel)."
    if verdict == HINT:
        text += " Uhr der Steuerung prüfen (manche Steuerungen stellen die Sommerzeit nicht selbst um)."
    return CheckResult("D6", "controller_day_boundary", verdict, worst, "min", text, SOURCED, {"offsets_min": offsets})


def check_outdoor_sensor(outdoor: Series, reference: Series, defrost: Series, start: float, end: float,
                         tz: str = days.DEFAULT_TZ, min_days: int = 3) -> CheckResult:
    """D10: Tagesmittel des Außenfühlers der Wärmepumpe gegen Wetterdienst; Tage mit > 10 % Abtauzeit fallen heraus."""
    rows = []
    for a, b in days.full_days(start, end, tz):
        if total(intervals_where(defrost, lambda v: v in (1, 1.0, True, "on"), a, b)) > 0.1 * (b - a):
            continue
        own, ref = time_mean(outdoor, [(a, b)]), time_mean(reference, [(a, b)])
        if own is not None and ref is not None:
            rows.append({"day": days.label(a, tz), "own": round(own, 2), "reference": round(ref, 2),
                         "diff": round(own - ref, 2)})
    prog = progress(len(rows), min_days, "days", FULL_DAYS, start)
    if len(rows) < min_days:
        return CheckResult("D10", "outdoor_sensor", NOT_ASSESSABLE, text=f"{len(rows)} Tage, nötig {min_days}.",
                           origin=DERIVED, details={"days": rows}, progress=prog)
    bias = sum(r["diff"] for r in rows) / len(rows)
    return CheckResult("D10", "outdoor_sensor", grade(abs(bias), 1.5, 3.0), round(bias, 2), "K",
                       f"Außenfühler im Mittel {num(bias, '+.1f')} K gegen Wetterdienst ({len(rows)} Tage).", DERIVED,
                       {"days": rows}, progress=prog)
