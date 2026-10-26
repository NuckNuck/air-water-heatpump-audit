"""Audit 3 – Leistung passt zum Bedarf: Taktet die Wärmepumpe, und springt der Heizstab ein?"""

from __future__ import annotations

from .. import cycles as c3
from .. import data_basis as d0
from .. import heat
from ..context import HEATER_ROLES, Context, meter_delta
from ..registry import SECTION, AuditSpec, CheckSpec, TimelineSpec
from ..result import HINT, NOT_ASSESSABLE, OK


def _point(ctx: Context, a: float, b: float, day: str) -> dict:
    if d0.check_coverage(ctx.s["heartbeat"], a, b).verdict != OK:
        return {"value": None, "verdict": NOT_ASSESSABLE}
    heating_hours = ctx.master.get("heating_hours")
    n = sum(1 for t in c3.starts(ctx.cycles_window) if a <= t < b)
    verdict = c3.starts_per_year_verdict(n / ((b - a) / 3600) * heating_hours) if heating_hours else NOT_ASSESSABLE
    return {"value": n, "verdict": verdict}


def _scale(master: dict) -> dict:
    """Starts pro Tag; Grenze aus C1 (Starts/Jahr ÷ Heizstunden × 24). Ohne Heizstunden keine Bänder."""
    heating_hours = master.get("heating_hours")
    starts_ok = c3.STARTS_PER_YEAR_OK * 24 / heating_hours if heating_hours else None
    return {"metric": "starts_per_day", "unit": "1/d", "min": 0, "max": None, "decimals": 0,
            "bands": [[0, round(starts_ok, 1), OK], [round(starts_ok, 1), None, HINT]] if starts_ok else []}


def _c4(ctx: Context):
    s = ctx.s
    table = heat.parse_capacity_table(ctx.master.get("capacity_min_table"))
    return c3.check_load_vs_min_capacity(ctx.heat_corrected, s["outdoor_temp"], s["flow_temp"],
                                         s["compressor_running"], s["dhw_active"], s["heartbeat"], ctx.section_start,
                                         ctx.end, table, ctx.tz)


def _c5(ctx: Context):
    return c3.check_backup_heater({k: ctx.s[k] for k in HEATER_ROLES}, ctx.heater_kw,
                                  meter_delta(ctx.s["electricity_meter"], ctx.section_start, ctx.end),
                                  ctx.section_start, ctx.end)


AUDIT = AuditSpec(
    audit_id="capacity", order=3, color="#d81b60", section=SECTION,
    roles=("compressor_running", "compressor_frequency", "defrost", "dhw_active", "heartbeat", *HEATER_ROLES,
           "electricity_meter", "outdoor_temp", "flow_temp", "return_temp", "flow_rate", "pump_running"),
    required_roles=("compressor_running",),
    master_keys=("capacity_min_table", "heating_hours", "immersion_heater_kw", "booster_heater_kw",
                 "booster_heater_2_kw"),
    names={"de": "Leistung", "en": "Capacity"},
    checks=(
        CheckSpec("C1", "starts_per_year", lambda ctx: c3.check_starts_per_year(
            ctx.cycles, ctx.section_start, ctx.end, ctx.master.get("heating_hours"))),
        CheckSpec("C2", "max_starts_per_hour", lambda ctx: c3.check_max_starts_per_hour(ctx.cycles,
                                                                                         ctx.section_start, ctx.end)),
        CheckSpec("C3", "short_cycles", lambda ctx: c3.check_short_cycles(ctx.cycles, since=ctx.section_start)),
        CheckSpec("C4", "load_vs_min_capacity", _c4),
        CheckSpec("C5", "backup_heater_share", _c5),
        CheckSpec("C6", "defrost", lambda ctx: c3.check_defrost(ctx.s["defrost"], ctx.cycles, ctx.section_start,
                                                                ctx.end)),
        CheckSpec("C7", "modulation", lambda ctx: c3.check_modulation(ctx.s["compressor_frequency"], ctx.cycles)),
    ),
    timeline=TimelineSpec(scale=_scale, point=_point, metric_names={"de": "Starts pro Tag", "en": "Starts per day"}),
)
