"""Rechnet alle umgesetzten Audits für einen Zeitraum aus fertigen Zeitreihen je Rolle.

Gemeinsam genutzt vom Prototyp (InfluxDB) und von der HA-Integration (Recorder). Fehlt eine Rolle, wird eine leere
Zeitreihe angenommen; die betroffenen Prüfungen enden dann in „nicht bewertbar“.
"""

from __future__ import annotations

from . import cycles as c3
from . import data_basis as d0
from . import efficiency as e1
from . import flow_temp as t2
from . import days, heat
from . import readiness as rd
from . import timeline as tl
from .actions import attach_actions
from .result import FULL_DAYS, HINT, NOT_ASSESSABLE, OK, CheckResult, overall, progress
from .series import Series, clip, intervals_where

# Rollen-Keys (Spezifikation 1.3); die FTC-Werte sind je Kreis eigene Rollen.
ROLE_KEYS = (
    "electricity_meter", "compressor_running", "compressor_frequency", "flow_temp", "return_temp", "flow_rate",
    "outdoor_temp", "outdoor_temp_reference", "pump_running", "defrost", "dhw_active", "immersion_heater",
    "booster_heater", "booster_heater_2", "heartbeat", "ftc_heating_consumed", "ftc_dhw_consumed",
    "ftc_controller_date", "flow_setpoint", "circuit_flow_temp", "circuit_return_temp", "circuit_pump_running",
    "room_temp",
)
HEATER_ROLES = ("immersion_heater", "booster_heater", "booster_heater_2")

DATA_BASIS, EFFICIENCY, FLOW_TEMPERATURE, CAPACITY = "data_basis", "efficiency", "flow_temperature", "capacity"


def data_quality(audit0: list[CheckResult]) -> str:
    """dq nach Spezifikation 2: high, wenn D2, D4, D8 ok; medium bei höchstens einer Abweichung; sonst low.

    Ein nicht bewertbares D4/D8 zählt wie ein hint (Qualität unbekannt, nicht belegt gut).
    """
    by_id = {r.check_id: r.verdict for r in audit0}
    verdicts = [by_id.get(cid, NOT_ASSESSABLE) for cid in ("D2", "D4", "D8")]
    if any(v not in (OK, HINT, NOT_ASSESSABLE) for v in verdicts):
        return "low"
    misses = sum(1 for v in verdicts if v != OK)
    return "high" if misses == 0 else "medium" if misses == 1 else "low"


def _meter_delta(meter: Series, start: float, end: float) -> float | None:
    values = [float(v) for _, v in clip(meter, start, end)]
    return (values[-1] - values[0]) if len(values) > 1 else None


def section_start(events: list[dict], start: float, end: float) -> tuple[float, dict | None]:
    """Beginn des aktuellen Abschnitts: letztes Ereignis im Fenster (Spezifikation 1.5), sonst Fensterbeginn."""
    inside = [e for e in events if start < e["time"] <= end]
    if not inside:
        return start, None
    last = max(inside, key=lambda e: e["time"])
    return last["time"], last


def run_audits(s: dict[str, Series], start: float, end: float, *, recorder_keep_days: float | None,
               long_term_days: float | None, heater_kw: dict[str, float], master: dict | None = None,
               events: list[dict] | None = None, controls: dict[str, dict] | None = None,
               tz: str = days.DEFAULT_TZ) -> dict:
    """master: Stammdaten (Spezifikation 1.4), u. a. hydraulic_separation, flow_rate_min_lpm, circuit_flow_max_lpm,
    room_temp_target,
    capacity_min_table, heating_hours.

    events: Änderungen an der Anlage ({time, kind, note}). Audit 0 prüft die Daten und nutzt das ganze Fenster;
    Audits 1–3 bewerten das Verhalten der Anlage und rechnen nur ab dem letzten Ereignis, damit nie über eine
    Änderung hinweg gemittelt wird.

    controls: heutiger Zustand der zugeordneten Stellgrößen-Rollen (actions.CONTROL_ROLES); daraus entstehen
    Vorschläge in den Aktionen, geschrieben wird hier nichts.
    """
    master = master or {}
    capacity_table = heat.parse_capacity_table(master.get("capacity_min_table"))
    s = {k: s.get(k) or [] for k in ROLE_KEYS}
    hb = s["heartbeat"]
    artifacts = d0.artifact_windows(hb, start, end)
    running = intervals_where(s["compressor_running"], lambda v: v in (1, 1.0, True, "on"), start, end)

    offset = d0.check_sensor_offset(s["flow_temp"], s["return_temp"], s["compressor_running"], s["pump_running"],
                                    s["defrost"], s["dhw_active"], start, end)
    audit0 = [
        d0.check_history_depth(recorder_keep_days, long_term_days),
        d0.check_coverage(hb, start, end),
        d0.check_resolution({k: s[k] for k in ("flow_temp", "return_temp", "flow_rate", "outdoor_temp")},
                            s["flow_temp"], s["return_temp"], running, start, end),
        offset,
        d0.check_meter_vs_ftc(s["electricity_meter"], [s["ftc_heating_consumed"], s["ftc_dhw_consumed"]], hb, start,
                              end, tz),
        d0.check_ftc_day_boundary(s["ftc_controller_date"], start, end, tz),
        d0.check_meter_resolution(s["electricity_meter"]),
        d0.check_restarts(hb, start, end),
        d0.check_outdoor_sensor(s["outdoor_temp"], s["outdoor_temp_reference"], s["defrost"], start, end, tz),
    ]
    # Wärme: roh und mit Fühler-Offset aus D4 (Spezifikation 1.1, Grundsatz 2; Entscheid F74)
    offset_k = offset.value if offset.verdict != NOT_ASSESSABLE else 0.0
    power = heat.heat_power(s["flow_rate"], s["flow_temp"], s["return_temp"], start, end, offset_k)
    raw = heat.heat_power(s["flow_rate"], s["flow_temp"], s["return_temp"], start, end)
    electricity = _meter_delta(s["electricity_meter"], start, end)
    heat_summary = {"raw_kwh": round(heat.energy_kwh(raw, [(start, end)]), 2), "offset_k": offset_k,
                    "offset_robust": bool(offset.details.get("robust")),
                    "corrected_kwh": round(heat.energy_kwh(power, [(start, end)]), 2),
                    "electricity_kwh": electricity}

    window_start = start
    start, event = section_start(events or [], start, end)
    cyc = c3.detect_cycles(s["compressor_running"], start, end, artifacts, s["defrost"], s["dhw_active"])
    audit3 = [
        c3.check_starts_per_year(cyc, start, end, master.get("heating_hours")),
        c3.check_max_starts_per_hour(cyc, start, end),
        c3.check_short_cycles(cyc, since=start),
        c3.check_load_vs_min_capacity(power, s["outdoor_temp"], s["flow_temp"], s["compressor_running"],
                                      s["dhw_active"], hb, start, end, capacity_table, tz),
        c3.check_backup_heater({k: s[k] for k in HEATER_ROLES}, heater_kw, _meter_delta(s["electricity_meter"], start, end),
                               start, end),
        c3.check_defrost(s["defrost"], cyc, start, end),
        c3.check_modulation(s["compressor_frequency"], cyc),
    ]
    heating, used = t2.heating_windows(cyc, s["defrost"], s["dhw_active"], s["circuit_pump_running"], artifacts,
                                       start, end)
    # Fühlerabgleich wie D4 über das ganze Fenster: Ereignisse ändern die Anlage, nicht die Fühler.
    pauses = t2.pause_windows(s["compressor_running"], s["pump_running"], s["defrost"], s["dhw_active"], window_start,
                              end)
    circuit_offset = t2.check_circuit_sensor_offset(s["flow_temp"], s["circuit_flow_temp"], pauses, window_start, end)
    audit2 = [
        t2.check_buffer_flow_loss(s["flow_temp"], s["circuit_flow_temp"], master.get("hydraulic_separation"), heating,
                                  used, circuit_offset, start, end),
        circuit_offset,
        t2.check_flow_ratio(s["flow_temp"], s["return_temp"], s["circuit_flow_temp"], s["circuit_return_temp"],
                            s["flow_rate"], heating, used, start, end, master.get("circuit_flow_max_lpm")),
        t2.check_heat_pump_spread(s["flow_temp"], s["return_temp"], s["flow_rate"], master.get("flow_rate_min_lpm"),
                                  heating, used, start, end),
        t2.check_flow_vs_setpoint(s["flow_temp"], s["circuit_flow_temp"], s["flow_setpoint"], heating, used, start, end),
        t2.check_heating_curve_headroom(s["room_temp"], master.get("room_temp_target"), heating, start, end, tz),
    ]
    # Datenreife der Prüfungen, deren Mindestmenge erst hier bekannt ist (gemeinsames Heizbetriebs-Kriterium)
    heating_prog = t2.heating_progress(heating, used, start)
    for r in audit2:
        if r.check_id in t2.HEATING_GATED and not (r.details.get("missing_input") or r.details.get("not_applicable")):
            r.progress = heating_prog
    dq = data_quality(audit0)
    meter_check = next(r for r in audit0 if r.check_id == "D8")
    meter_step = meter_check.value if meter_check.verdict != NOT_ASSESSABLE else None
    offset_robust = heat_summary["offset_robust"]
    ideal = e1.carnot_power(power, s["flow_temp"], s["return_temp"], s["outdoor_temp"], window_start, end)
    rows = e1.daily_rows(s["electricity_meter"], raw, power, ideal, s["outdoor_temp"], s["dhw_active"], hb, start,
                         end, tz)
    audit1 = [
        e1.check_daily_cop(rows, offset_robust, meter_step),
        e1.check_weekly_cop(rows),
        e1.check_carnot_efficiency(rows, dq, offset_robust),
        e1.check_dhw_share(rows),
    ]
    for r in audit1:  # gültige volle Tage (Heartbeat, Mindeststrom), E1 braucht einen, E2–E4 eine Woche
        r.progress = progress(len(rows), 1 if r.check_id == "E1" else e1.WEEK_DAYS, "days", FULL_DAYS, start)
    # Zeitstrahl: Tageswerte über das ganze Fenster, unabhängig vom letzten Ereignis
    if start > window_start:
        cyc_all = c3.detect_cycles(s["compressor_running"], window_start, end, artifacts, s["defrost"],
                                   s["dhw_active"])
        rows_all = e1.daily_rows(s["electricity_meter"], raw, power, ideal, s["outdoor_temp"], s["dhw_active"], hb,
                                 window_start, end, tz)
    else:
        cyc_all, rows_all = cyc, rows
    timeline = tl.daily_points(s, cyc_all, artifacts, rows_all, circuit_offset, master, offset_robust, window_start,
                               end, tz)
    return {
        "period": {"start": window_start, "end": end},
        "timeline": {"days": timeline, "scales": tl.scales(master.get("heating_hours"))},
        "section": {"start": start, "event": event},
        "heat": heat_summary,
        # Datenreife je Audit (Hochrechnung): Audit 0 zählt ab Fensterbeginn, Audits 1–3 ab dem letzten Ereignis
        "readiness": {
            DATA_BASIS: rd.audit_readiness(window_start, audit0, end, tz),
            EFFICIENCY: rd.audit_readiness(start, audit1, end, tz),
            FLOW_TEMPERATURE: rd.audit_readiness(start, audit2, end, tz),
            CAPACITY: rd.audit_readiness(start, audit3, end, tz),
        },
        "audits": {
            DATA_BASIS: {"verdict": overall(audit0), "dq": dq, "checks": [r.as_dict() for r in attach_actions(audit0, controls)]},
            # Gesamturteil nur aus E3 (Spezifikation 4.2); E1, E2, E4 sind info und zählen ohnehin nicht
            EFFICIENCY: {"verdict": overall(audit1), "dq": dq, "checks": [r.as_dict() for r in attach_actions(audit1, controls)]},
            FLOW_TEMPERATURE: {"verdict": overall(audit2), "dq": dq, "checks": [r.as_dict() for r in attach_actions(audit2, controls)]},
            CAPACITY: {"verdict": overall(audit3), "dq": dq, "checks": [r.as_dict() for r in attach_actions(audit3, controls)]},
        },
        "cycles": [vars(c) | {"duration_min": round(c.duration / 60, 1)} for c in cyc],
    }
