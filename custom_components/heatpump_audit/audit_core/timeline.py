"""Zeitstrahl: je vollem Tag ein echter Messwert pro Audit, dazu die Ampel-Bänder (Entscheid F100).

Kein Gesamt-Score: Jede Linie ist eine Kennzahl, die es auch in der Tabelle gibt, mit denselben Schwellen. Tageswerte
hängen nicht von Ereignissen ab; Ereignisse zeichnet die Karte als senkrechte Linien darüber.
"""

from __future__ import annotations

from . import cycles as c3
from . import days
from . import efficiency as e1
from . import flow_temp as t2
from .data_basis import check_coverage
from .result import HINT, INFO, NOT_ASSESSABLE, OK, WARN
from .series import Interval, Series, intersect

DATA_BASIS, EFFICIENCY, FLOW_TEMPERATURE, CAPACITY = "data_basis", "efficiency", "flow_temperature", "capacity"
KEEP_DAYS = 400  # so viele Tage hält die Integration gespeichert, auch wenn die Rohdaten älter sind


def scales(heating_hours: float | None) -> dict[str, dict]:
    """Darstellung je Audit: Einheit, Wertebereich und Ampel-Bänder [von, bis, Urteil] aus denselben Schwellen wie die
    Prüfungen. Die Beschriftungen liefert die Karte (übersetzt)."""
    starts_ok = c3.STARTS_PER_YEAR_OK * 24 / heating_hours if heating_hours else None
    return {
        DATA_BASIS: {"metric": "coverage", "unit": "%", "min": 0, "max": 100, "strip": True,
                     "bands": [[98, 100, OK], [90, 98, HINT], [0, 90, WARN]]},
        EFFICIENCY: {"metric": "carnot_efficiency", "unit": "", "min": 0, "max": 0.7, "decimals": 2,
                     "bands": [[0, e1.CARNOT_WARN_BELOW, WARN], [e1.CARNOT_WARN_BELOW, e1.CARNOT_OK_MIN, HINT],
                               [e1.CARNOT_OK_MIN, e1.CARNOT_PLAUSIBLE_MAX, OK], [e1.CARNOT_PLAUSIBLE_MAX, 0.7, INFO]]},
        FLOW_TEMPERATURE: {"metric": "buffer_flow_loss", "unit": "K", "min": 0, "max": 8, "decimals": 1,
                           "bands": [[0, t2.LOSS_OK_K, OK], [t2.LOSS_OK_K, t2.LOSS_HINT_K, HINT],
                                     [t2.LOSS_HINT_K, 8, WARN]]},
        # Starts pro Tag; Grenze aus C1 (Starts/Jahr ÷ Heizstunden × 24). Ohne Heizstunden keine Bänder.
        CAPACITY: {"metric": "starts_per_day", "unit": "1/d", "min": 0, "max": None, "decimals": 0,
                   "bands": [[0, round(starts_ok, 1), OK], [round(starts_ok, 1), None, HINT]] if starts_ok else []},
    }


def _point(value, verdict: str, **extra) -> dict:
    return {"value": value, "verdict": verdict} | extra


def daily_points(s: dict[str, Series], cycles: list[c3.Cycle], artifacts: list[Interval], eff_rows: list[dict],
                 circuit_offset, master: dict, offset_robust: bool, start: float, end: float,
                 tz: str = days.DEFAULT_TZ) -> list[dict]:
    """Ein Eintrag je vollem lokalen Tag in [start, end].

    cycles und eff_rows müssen über den ganzen Zeitraum gerechnet sein, nicht nur ab dem letzten Ereignis.
    """
    rows_by_day = {r["day"]: r for r in eff_rows}
    heating_hours = master.get("heating_hours")
    out = []
    for a, b in days.full_days(start, end, tz):
        label = days.label(a, tz)
        coverage = check_coverage(s["heartbeat"], a, b)
        entry = {"day": label, "start": a, "end": b,
                 DATA_BASIS: _point(coverage.value, coverage.verdict)}

        row = rows_by_day.get(label)
        if row and row["electricity_kwh"]:
            eta = row["ideal_kwh"] / row["electricity_kwh"]
            entry[EFFICIENCY] = _point(round(eta, 3), e1.carnot_verdict(eta, offset_robust), cop=row["cop"],
                                       cop_raw=row["cop_raw"], electricity_kwh=row["electricity_kwh"],
                                       heat_kwh=row["heat_kwh"], outdoor_mean=row["outdoor_mean"])
        else:
            entry[EFFICIENCY] = _point(None, NOT_ASSESSABLE)

        day_cycles = [c for c in cycles if c.start < b and c.end > a]
        win, used = t2.heating_windows(day_cycles, s["defrost"], s["dhw_active"], s["circuit_pump_running"],
                                       artifacts, a, b)
        loss = t2.check_buffer_flow_loss(s["flow_temp"], s["circuit_flow_temp"], master.get("hydraulic_separation"),
                                         intersect(win, [(a, b)]), used, circuit_offset, a, b)
        entry[FLOW_TEMPERATURE] = _point(loss.value, loss.verdict) if loss.value is not None \
            else _point(None, NOT_ASSESSABLE)

        if coverage.verdict == OK:
            n = sum(1 for t in c3.starts(cycles) if a <= t < b)
            verdict = c3.starts_per_year_verdict(n / ((b - a) / 3600) * heating_hours) if heating_hours else \
                NOT_ASSESSABLE
            entry[CAPACITY] = _point(n, verdict)
        else:
            entry[CAPACITY] = _point(None, NOT_ASSESSABLE)
        out.append(entry)
    return out


def merge(stored: list[dict], fresh: list[dict], keep_days: int = KEEP_DAYS) -> list[dict]:
    """Gespeicherte Tage um neu gerechnete ergänzen; ein neu gerechneter Tag ersetzt den gespeicherten."""
    by_day = {d["day"]: d for d in stored} | {d["day"]: d for d in fresh}
    return [by_day[k] for k in sorted(by_day)][-keep_days:]
