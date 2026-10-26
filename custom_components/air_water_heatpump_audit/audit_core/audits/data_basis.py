"""Audit 0 – Datenbasis: Kann man den Messwerten trauen? Bewertet die Messung, nicht die Wärmepumpe."""

from __future__ import annotations

from .. import data_basis as d0
from ..context import Context
from ..registry import WINDOW, AuditSpec, CheckSpec, TimelineSpec
from ..result import HINT, OK, WARN


def _point(ctx: Context, a: float, b: float, day: str) -> dict:
    coverage = d0.check_coverage(ctx.s["heartbeat"], a, b)
    return {"value": coverage.value, "verdict": coverage.verdict}


def _scale(master: dict) -> dict:
    return {"metric": "coverage", "unit": "%", "min": 0, "max": 100, "strip": True,
            "bands": [[98, 100, OK], [90, 98, HINT], [0, 90, WARN]]}


def _resolution(ctx: Context):
    s = ctx.s
    return d0.check_resolution({k: s[k] for k in ("flow_temp", "return_temp", "flow_rate", "outdoor_temp")},
                               s["flow_temp"], s["return_temp"], ctx.running, ctx.start, ctx.end)


AUDIT = AuditSpec(
    audit_id="data_basis", order=0, color="#6d4c41", section=WINDOW,
    roles=("heartbeat", "flow_temp", "return_temp", "flow_rate", "outdoor_temp", "outdoor_temp_reference",
           "compressor_running", "pump_running", "defrost", "dhw_active", "electricity_meter",
           "controller_heating_consumed", "controller_dhw_consumed", "controller_date"),
    required_roles=("heartbeat",),
    master_keys=(),
    names={"de": "Datenbasis", "en": "Data basis"},
    checks=(
        CheckSpec("D1", "history_depth", lambda ctx: d0.check_history_depth(ctx.recorder_keep_days,
                                                                             ctx.long_term_days)),
        CheckSpec("D2", "coverage", lambda ctx: ctx.coverage),
        CheckSpec("D3", "resolution", _resolution),
        CheckSpec("D4", "sensor_offset", lambda ctx: ctx.sensor_offset),
        CheckSpec("D5", "meter_vs_controller", lambda ctx: d0.check_meter_vs_controller(
            ctx.s["electricity_meter"], [ctx.s["controller_heating_consumed"], ctx.s["controller_dhw_consumed"]],
            ctx.s["heartbeat"], ctx.start, ctx.end, ctx.tz)),
        CheckSpec("D6", "controller_day_boundary", lambda ctx: d0.check_controller_day_boundary(
            ctx.s["controller_date"], ctx.start, ctx.end, ctx.tz)),
        CheckSpec("D8", "meter_resolution", lambda ctx: ctx.meter_resolution),
        CheckSpec("D9", "restart_artifacts", lambda ctx: d0.check_restarts(ctx.s["heartbeat"], ctx.start, ctx.end)),
        CheckSpec("D10", "outdoor_sensor", lambda ctx: d0.check_outdoor_sensor(
            ctx.s["outdoor_temp"], ctx.s["outdoor_temp_reference"], ctx.s["defrost"], ctx.start, ctx.end, ctx.tz)),
    ),
    timeline=TimelineSpec(scale=_scale, point=_point, metric_names={"de": "Abdeckung", "en": "Coverage"}),
)
