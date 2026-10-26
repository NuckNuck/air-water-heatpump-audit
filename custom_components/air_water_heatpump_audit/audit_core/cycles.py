"""Audit 3 – Leistung passt zum Bedarf: Zykluserkennung und Taktprüfungen (Spezifikation Abschnitt 3)."""

from __future__ import annotations

from dataclasses import dataclass

from . import days
from .data_basis import check_coverage
from .heat import CapacityTable, energy_kwh, min_capacity_kw, time_mean
from .result import (DERIVED, DESCRIPTIVE, ELAPSED, FULL_DAYS, HINT, INFO, NOT_ASSESSABLE, OK, PHYSICAL, RATE, SOURCED,
                     WARN, CheckResult, count, grade, num, progress)
from .series import Interval, Series, intersect, intervals_where, overlaps, subtract, total, weighted_values

MIN_OFF_S = 30
DEFROST_MARGIN_S = 120
DHW_MIN_S = 60
SHORT_CYCLE_S = 600
VERY_SHORT_CYCLE_S = 180
LOW_FREQUENCY_HZ = 20
VERY_SHORT_MIN_DAYS = 2  # C3: sehr kurze Heizläufe an mindestens 2 verschiedenen Tagen → hint
DEFROST_WARM_C = 5.0  # C6: über +5 °C sollte kaum Reif entstehen (Abtaubereich −2…+5 °C, BFE-AT)
DEFROST_WARM_MAX_PER_H = 2.0  # C6: mehr Abtauungen je Laufstunde über +5 °C → hint (derived)
DEFROST_WARM_MIN_RUN_H = 5.0  # C6: erst ab 5 h Lauf über +5 °C bewerten, sonst entscheidet eine einzelne Stunde

STARTS_PER_YEAR_OK, STARTS_PER_YEAR_HINT = 2000, 5500  # C1, WPQS: ⅓ der Anlagen ≤ 2.000, 90 % < 5.500

HEATING, DHW, MIXED = "heating", "dhw", "mixed"


def _on(v) -> bool:
    return v in (1, 1.0, True, "on")


@dataclass
class Cycle:
    start: float
    end: float
    open_start: bool = False
    open_end: bool = False
    kind: str = HEATING
    pause_before: float | None = None
    defrost_stops: int = 0

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def closed(self) -> bool:
        return not (self.open_start or self.open_end)


def detect_cycles(compressor: Series, start: float, end: float, artifacts: list[Interval] = (),
                  defrost: Series = (), dhw: Series = ()) -> list[Cycle]:
    """Verdichterläufe aus dem Ein/Aus-Signal.

    Stopps unter 30 s, Stopps in Artefakt-Fenstern (Neustart, Lücke) und Stopps an einer Abtauung werden überbrückt.
    """
    runs = intervals_where(compressor, _on, start, end)
    defrost_iv = [(a - DEFROST_MARGIN_S, b + DEFROST_MARGIN_S) for a, b in intervals_where(defrost, _on, start, end)]
    cycles: list[Cycle] = []
    for a, b in runs:
        if cycles:
            gap = (cycles[-1].end, a)
            if gap[1] - gap[0] < MIN_OFF_S or overlaps(gap, artifacts):
                cycles[-1].end = b
                continue
            if overlaps(gap, defrost_iv):
                cycles[-1].end = b
                cycles[-1].defrost_stops += 1
                continue
        cycles.append(Cycle(a, b, pause_before=(a - cycles[-1].end) if cycles else None))
    if cycles:
        # Ohne bekannten Zustand vor dem ersten Datenpunkt ist unklar, ob der erste Lauf dort wirklich begann.
        known_from = max(start, compressor[0][0]) if compressor else start
        cycles[0].open_start = cycles[0].start <= known_from
        cycles[-1].open_end = cycles[-1].end >= end
    dhw_iv = intervals_where(dhw, _on, start, end)
    for c in cycles:
        t_dhw = total(intersect([(c.start, c.end)], dhw_iv))
        if t_dhw >= DHW_MIN_S:
            c.kind = DHW if c.duration - t_dhw < DHW_MIN_S else MIXED
    return cycles


def starts(cycles: list[Cycle]) -> list[float]:
    """Startzeitpunkte; ein Lauf, der schon vor dem Zeitraum lief, ist kein Start."""
    return [c.start for c in cycles if not c.open_start]


def check_max_starts_per_hour(cycles: list[Cycle], start: float, end: float) -> CheckResult:
    """C2: höchste Startzahl in einem gleitenden 60-min-Fenster."""
    ts = starts(cycles)
    prog = progress((end - start) / 3600, 1, "hours", ELAPSED, start)
    if end - start < 3600:
        return CheckResult("C2", "max_starts_per_hour", NOT_ASSESSABLE, text="Zeitraum kürzer als 1 h.",
                           origin=SOURCED, progress=prog)
    peak = max((sum(1 for u in ts if t <= u < t + 3600) for t in ts), default=0)
    return CheckResult("C2", "max_starts_per_hour", grade(peak, 6, 12), peak, "1/h",
                       f"Höchstens {count(peak, 'Start', 'Starts')} in einer Stunde. Herstellergrenzen 6–12/h (WPQS S. 98, Danfoss).",
                       SOURCED, progress=prog)


def check_short_cycles(cycles: list[Cycle], min_cycles: int = 20, since: float = 0.0,
                       tz: str = days.DEFAULT_TZ) -> CheckResult:
    """C3: Anteil kurzer Heizzyklen (< 10 min), dazu Zyklen unter 3 min und an wie vielen Tagen sie vorkamen."""
    heating = [c for c in cycles if c.kind == HEATING and c.closed]
    details = {"heating_cycles": len(heating), "durations_min": [round(c.duration / 60, 1) for c in heating]}
    prog = progress(len(heating), min_cycles, "cycles", RATE, since)
    if len(heating) < min_cycles:
        return CheckResult("C3", "short_cycles", NOT_ASSESSABLE,
                           text=f"{count(len(heating), 'abgeschlossener Heizzyklus', 'abgeschlossene Heizzyklen')}, nötig {min_cycles}.", origin=DESCRIPTIVE,
                           details=details, progress=prog)
    short = sum(1 for c in heating if c.duration < SHORT_CYCLE_S)
    very_short_cycles = [c for c in heating if c.duration < VERY_SHORT_CYCLE_S]
    very_short = len(very_short_cycles)
    very_short_days = sorted({days.label(c.start, tz) for c in very_short_cycles})
    details["very_short"] = very_short
    details["very_short_days"] = very_short_days
    share = 100 * short / len(heating)
    # Spezifikation 3.2: Läufe < 3 min an ≥ 2 Tagen → hint; ein einzelner schlechter Tag (z. B. Wartung) reicht nicht.
    verdict = HINT if len(very_short_days) >= VERY_SHORT_MIN_DAYS else INFO
    text = f"{short} von {len(heating)} Heizzyklen kürzer als 10 min, {very_short} kürzer als 3 min"
    if very_short:
        text += f" (an {count(len(very_short_days), 'Tag', 'Tagen')})"
    return CheckResult("C3", "short_cycles", verdict, round(share, 1), "%", text + ".", DESCRIPTIVE, details)


def check_starts_per_year(cycles: list[Cycle], start: float, end: float, heating_hours: float | None,
                          min_days: float = 14) -> CheckResult:
    """C1: Hochrechnung Starts/Jahr = Starts je Stunde × Heizstunden des Standorts. Obergrenze, daher höchstens hint."""
    if not heating_hours:
        return CheckResult("C1", "starts_per_year", NOT_ASSESSABLE,
                           text="Stammdaten fehlen: Heizstunden pro Jahr am Standort.", origin=SOURCED)
    hours = (end - start) / 3600
    prog = progress(hours, min_days * 24, "hours", ELAPSED, start)
    n = len(starts(cycles))
    projection = round(n / hours * heating_hours) if hours else 0
    text = (f"{n} Starts in {num(hours, '.1f')} h → Obergrenze {num(projection, ',')} Starts/Jahr "
            f"(WPQS: ⅓ ≤ 2.000, 90 % < 5.500).")
    if hours < min_days * 24:
        return CheckResult("C1", "starts_per_year", NOT_ASSESSABLE, projection, "1/a",
                           text + f" Bewertung ab {num(min_days, 'g')} Tagen.", SOURCED, progress=prog)
    return CheckResult("C1", "starts_per_year", starts_per_year_verdict(projection), projection, "1/a", text, SOURCED,
                       progress=prog)


def starts_per_year_verdict(projection: float) -> str:
    """C1 (auch Tageswerte im Zeitstrahl): Hochrechnung ist eine Obergrenze, daher höchstens gelb."""
    verdict = grade(projection, STARTS_PER_YEAR_OK, STARTS_PER_YEAR_HINT)
    return HINT if verdict == WARN else verdict


def check_backup_heater(heaters: dict[str, Series], power_kw: dict[str, float | None], electricity_kwh: float | None,
                        start: float, end: float, min_days: float = 7) -> CheckResult:
    """C5: Heizstab-Anteil am Strom ≈ Einschaltdauer × Nennleistung ÷ Zählerstrom.

    Ein Heizstab, der lief, dessen Leistung aber nicht in den Stammdaten steht, macht die Prüfung nicht bewertbar.
    """
    hours = {k: total(intervals_where(s, _on, start, end)) / 3600 for k, s in heaters.items()}
    unknown = [k for k, h in hours.items() if h > 0 and power_kw.get(k) is None]
    if unknown:
        return CheckResult("C5", "backup_heater_share", NOT_ASSESSABLE,
                           text="Stammdaten fehlen: Leistung von Heizstab bzw. Zusatzheizung.", origin=DERIVED,
                           details={"on_hours": hours, "missing_power": unknown})
    heater_kwh = sum(hours[k] * float(power_kw.get(k) or 0.0) for k in hours)
    details = {"on_hours": hours, "heater_kwh": round(heater_kwh, 2)}
    prog = progress((end - start) / 3600, min_days * 24, "hours", ELAPSED, start)
    if (end - start) < min_days * 86400 or not electricity_kwh:
        return CheckResult("C5", "backup_heater_share", NOT_ASSESSABLE,
                           text=f"Heizstab {num(heater_kwh, '.1f')} kWh; Bewertung ab {num(min_days, 'g')} Tagen.",
                           origin=DERIVED,
                           details=details, progress=prog)
    share = 100 * heater_kwh / electricity_kwh
    return CheckResult("C5", "backup_heater_share", grade(share, 2, 4), round(share, 2), "%",
                       f"Heizstab ≈ {num(heater_kwh, '.1f')} kWh von {num(electricity_kwh, '.0f')} kWh Zählerstrom.",
                       DERIVED,
                       details, progress=prog)


def check_defrost(defrost: Series, cycles: list[Cycle], start: float, end: float,
                  outdoor: Series = ()) -> CheckResult:
    """C6: Abtauungen je Laufstunde; gelb, wenn sie auch über +5 °C außen häufig sind.

    outdoor: möglichst die Außentemperatur eines Wetterdienstes – der Außenfühler der Wärmepumpe wird beim Abtauen
    verfälscht (Spezifikation 2, D10).
    """
    events = intervals_where(defrost, _on, start, end)
    runs = [(c.start, c.end) for c in cycles]
    run_h = total(runs) / 3600
    rate = len(events) / run_h if run_h else 0.0
    details = {"events": events, "minutes": round(total(events) / 60, 1)}
    text = f"{count(len(events), 'Abtauung', 'Abtauungen')} in {num(run_h, '.1f')} h Verdichterlauf."
    verdict = INFO
    if outdoor:
        warm = intersect(runs, intervals_where(outdoor, lambda v: float(v) > DEFROST_WARM_C, start, end))
        warm_h = total(warm) / 3600
        warm_events = sum(1 for a, _ in events if overlaps((a, a + 1), warm))
        details |= {"warm_run_h": round(warm_h, 1), "warm_events": warm_events}
        if warm_h >= DEFROST_WARM_MIN_RUN_H:
            warm_rate = warm_events / warm_h
            details["warm_rate_per_h"] = round(warm_rate, 2)
            text += (f" Über {num(DEFROST_WARM_C, 'g')} °C außen: {count(warm_events, 'Abtauung', 'Abtauungen')} in "
                     f"{num(warm_h, '.1f')} h Lauf ({num(warm_rate, '.1f')}/h).")
            if warm_rate > DEFROST_WARM_MAX_PER_H:
                verdict = HINT
                text += " Bei diesen Temperaturen sollte kaum Reif entstehen."
    return CheckResult("C6", "defrost", verdict, round(rate, 2), "1/h Lauf", text, DERIVED, details)


def check_modulation(frequency: Series, cycles: list[Cycle], low_hz: float = LOW_FREQUENCY_HZ) -> CheckResult:
    """C7: Laufzeitanteil im unteren Frequenzband und Verteilung in 10-Hz-Klassen."""
    pairs = [(float(v), w) for v, w in weighted_values(frequency, [(c.start, c.end) for c in cycles])
             if float(v) > 0]
    run = sum(w for _, w in pairs)
    if not run:
        return CheckResult("C7", "modulation", NOT_ASSESSABLE, text="Keine Laufzeit mit Frequenzwerten.",
                           origin=DESCRIPTIVE)
    low = sum(w for v, w in pairs if v <= low_hz)
    bins: dict[str, float] = {}
    for v, w in pairs:
        lo = int(v // 10) * 10
        key = f"{lo}-{lo + 9}"
        bins[key] = bins.get(key, 0) + w
    hist = {k: round(100 * w / run, 1) for k, w in sorted(bins.items(), key=lambda kv: int(kv[0].split('-')[0]))}
    return CheckResult("C7", "modulation", INFO, round(100 * low / run, 1), "%",
                       f"{num(100 * low / run, '.0f')} % der Laufzeit bei ≤ {num(low_hz, 'g')} Hz.", DESCRIPTIVE,
                       {"histogram_pct": hist})


def check_load_vs_min_capacity(power: Series, outdoor: Series, flow: Series, compressor: Series, dhw: Series,
                               uptime: Series, start: float, end: float, table: CapacityTable | None,
                               tz: str = days.DEFAULT_TZ) -> CheckResult:
    """C4: mittlere Heizlast je vollem Tag gegen Mindestleistung laut Datenblatt (erklärt das Takten, urteilt nicht)."""
    if not table:
        return CheckResult("C4", "load_vs_min_capacity", NOT_ASSESSABLE,
                           text="Stammdaten fehlen: Mindestleistung laut Datenblatt.", origin=PHYSICAL)
    rows = []
    for a, b in days.full_days(start, end, tz):
        if check_coverage(uptime, a, b).verdict != OK:
            continue
        heating_time = subtract([(a, b)], intervals_where(dhw, _on, a, b))
        heat = energy_kwh(power, heating_time)
        running = intersect(intervals_where(compressor, _on, a, b), heating_time)
        t_out, t_flow = time_mean(outdoor, [(a, b)]), time_mean(flow, running)
        if t_out is None or t_flow is None:
            continue
        load = heat / ((b - a) / 3600)
        p_min = min_capacity_kw(t_out, t_flow, table)
        rows.append({"day": days.label(a, tz), "heat_kwh": round(heat, 1), "load_kw": round(load, 2),
                     "outdoor_c": round(t_out, 1), "flow_c": round(t_flow, 1), "min_capacity_kw": round(p_min, 2),
                     "ratio": round(load / p_min, 2)})
    prog = progress(len(rows), 1, "days", FULL_DAYS, start)
    if not rows:
        return CheckResult("C4", "load_vs_min_capacity", NOT_ASSESSABLE,
                           text="Kein voller Tag mit lückenlosen Daten.", origin=PHYSICAL, progress=prog)
    last = rows[-1]
    if last["ratio"] < 1:
        text = (f"{days.display(last['day'])}: Last {num(last['load_kw'], '.1f')} kW unter kleinster Stufe "
                f"{num(last['min_capacity_kw'], '.1f')} kW "
                f"(Verhältnis {num(last['ratio'], '.2f')}) → Takten physikalisch unvermeidbar.")
    else:
        text = (f"{days.display(last['day'])}: Last {num(last['load_kw'], '.1f')} kW über kleinster Stufe "
                f"{num(last['min_capacity_kw'], '.1f')} kW "
                f"(Verhältnis {num(last['ratio'], '.2f')}) → häufiges Takten wäre nicht durch die Last erklärt.")
    return CheckResult("C4", "load_vs_min_capacity", INFO, last["ratio"], "", text, PHYSICAL, {"days": rows},
                       progress=prog)
