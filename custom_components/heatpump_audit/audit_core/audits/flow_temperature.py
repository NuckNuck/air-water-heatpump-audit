"""Audit 2 – Vorlauf so niedrig wie möglich: Wo geht zwischen Wärmepumpe und Heizkörpern Temperatur verloren?"""

from __future__ import annotations

from .. import flow_temp as t2
from ..context import Context
from ..registry import SECTION, AuditSpec, CheckSpec, TimelineSpec
from ..result import HINT, NOT_ASSESSABLE, OK, WARN, CheckResult
from ..series import intersect


def _finish(ctx: Context, results: list[CheckResult]) -> None:
    """Gemeinsame Mindestmenge stationärer Heizbetrieb für T1, T3–T5 (Datenreife)."""
    windows, used = ctx.heating
    prog = t2.heating_progress(windows, used, ctx.section_start)
    for r in results:
        if r.check_id in t2.HEATING_GATED and not (r.details.get("missing_input") or r.details.get("not_applicable")):
            r.progress = prog


def _point(ctx: Context, a: float, b: float, day: str) -> dict:
    s = ctx.s
    day_cycles = [c for c in ctx.cycles_window if c.start < b and c.end > a]
    win, used = t2.heating_windows(day_cycles, s["defrost"], s["dhw_active"], s["circuit_pump_running"],
                                   ctx.artifacts, a, b)
    loss = t2.check_buffer_flow_loss(s["flow_temp"], s["circuit_flow_temp"], ctx.master.get("hydraulic_separation"),
                                     intersect(win, [(a, b)]), used, ctx.circuit_offset, a, b)
    return {"value": loss.value, "verdict": loss.verdict} if loss.value is not None \
        else {"value": None, "verdict": NOT_ASSESSABLE}


def _scale(master: dict) -> dict:
    return {"metric": "buffer_flow_loss", "unit": "K", "min": 0, "max": 8, "decimals": 1,
            "bands": [[0, t2.LOSS_OK_K, OK], [t2.LOSS_OK_K, t2.LOSS_HINT_K, HINT], [t2.LOSS_HINT_K, 8, WARN]]}


def _t1(ctx: Context):
    windows, used = ctx.heating
    return t2.check_buffer_flow_loss(ctx.s["flow_temp"], ctx.s["circuit_flow_temp"],
                                     ctx.master.get("hydraulic_separation"), windows, used, ctx.circuit_offset,
                                     ctx.section_start, ctx.end)


def _t3(ctx: Context):
    s, (windows, used) = ctx.s, ctx.heating
    return t2.check_flow_ratio(s["flow_temp"], s["return_temp"], s["circuit_flow_temp"], s["circuit_return_temp"],
                               s["flow_rate"], windows, used, ctx.section_start, ctx.end,
                               ctx.master.get("circuit_flow_max_lpm"))


def _t4(ctx: Context):
    s, (windows, used) = ctx.s, ctx.heating
    return t2.check_heat_pump_spread(s["flow_temp"], s["return_temp"], s["flow_rate"],
                                     ctx.master.get("flow_rate_min_lpm"), windows, used, ctx.section_start, ctx.end)


def _t5(ctx: Context):
    s, (windows, used) = ctx.s, ctx.heating
    return t2.check_flow_vs_setpoint(s["flow_temp"], s["circuit_flow_temp"], s["flow_setpoint"], windows, used,
                                     ctx.section_start, ctx.end)


def _t6(ctx: Context):
    windows, _ = ctx.heating
    return t2.check_heating_curve_headroom(ctx.s["room_temp"], ctx.master.get("room_temp_target"), windows,
                                           ctx.section_start, ctx.end, ctx.tz)


AUDIT = AuditSpec(
    audit_id="flow_temperature", order=2, color="#00897b", section=SECTION,
    roles=("flow_temp", "return_temp", "flow_rate", "circuit_flow_temp", "circuit_return_temp",
           "circuit_pump_running", "flow_setpoint", "room_temp", "compressor_running", "pump_running", "defrost",
           "dhw_active", "heartbeat",
           "electricity_meter"),  # nur für die Datenqualität (D8), die an jedem Audit steht
    required_roles=("flow_temp", "compressor_running"),
    master_keys=("hydraulic_separation", "flow_rate_min_lpm", "circuit_flow_max_lpm", "room_temp_target"),
    names={"de": "Vorlauf", "en": "Flow temperature"},
    checks=(
        CheckSpec("T1", "buffer_flow_loss", _t1),
        CheckSpec("T2", "circuit_sensor_offset", lambda ctx: ctx.circuit_offset),
        CheckSpec("T3", "flow_ratio", _t3),
        CheckSpec("T4", "heat_pump_spread", _t4),
        CheckSpec("T5", "flow_vs_setpoint", _t5),
        CheckSpec("T6", "heating_curve_headroom", _t6),
    ),
    timeline=TimelineSpec(scale=_scale, point=_point),
    finish=_finish,
)
