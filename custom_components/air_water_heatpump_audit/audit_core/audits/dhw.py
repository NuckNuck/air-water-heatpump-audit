"""Audit 4 – Warmwasser: Wie effizient, wie warm und wann lädt die Wärmepumpe den Speicher?"""

from __future__ import annotations

from .. import dhw as w1
from .. import efficiency as e1
from ..context import Context
from ..registry import DHW_SECTION, AuditSpec, CheckSpec, TimelineSpec
from ..result import HINT, INFO, OK, WARN
from ..series import intervals_where


def _point(ctx: Context, a: float, b: float, day: str) -> dict:
    return w1.daily_point(ctx.dhw_charges_window, a, b, ctx.offset_robust)


def _scale(master: dict) -> dict:
    """Dieselben Bänder wie der Gütegrad beim Heizen (E3), weil W1 dieselben Schwellen nutzt."""
    return {"metric": "dhw_efficiency", "unit": "", "min": 0, "max": 0.7, "decimals": 2,
            "bands": [[0, e1.CARNOT_WARN_BELOW, WARN], [e1.CARNOT_WARN_BELOW, e1.CARNOT_OK_MIN, HINT],
                      [e1.CARNOT_OK_MIN, e1.CARNOT_PLAUSIBLE_MAX, OK], [e1.CARNOT_PLAUSIBLE_MAX, 0.7, INFO]]}


def _w3(ctx: Context):
    heater = intervals_where(ctx.s["immersion_heater"], w1._on, ctx.dhw_section_start, ctx.end)
    return w1.check_disinfection(ctx.dhw_charges, heater, ctx.heater_kw.get("immersion_heater"), ctx.dhw_section_start,
                                 ctx.end)


def _w2(ctx: Context):
    draw = ctx.dhw_draw
    return w1.check_dhw_temperature(ctx.dhw_charges, ctx.dhw_section_start, ctx.end, ctx.s["dhw_setpoint"],
                                    ctx.dhw_charges_window, ctx.start, ctx.master.get("dhw_disinfection_interval_days"),
                                    draw.turnover_days if draw and ctx.end - ctx.dhw_section_start >= w1.MIN_DRAW_DAYS * 86400
                                    else None)


def _w4(ctx: Context):
    draw = ctx.dhw_draw
    return w1.check_standby_loss(ctx.dhw_quiet_windows, ctx.master.get("dhw_tank_volume_l"), ctx.dhw_section_start,
                                 draw.charged_kwh_day if draw else None)


def _w6(ctx: Context):
    return w1.check_dhw_draw(ctx.dhw_draw, ctx.master.get("dhw_tank_volume_l"), ctx.persons, ctx.dhw_dates,
                             ctx.dhw_section_start, ctx.end, ctx.cold_water_c)


AUDIT = AuditSpec(
    audit_id="dhw", order=4, color="#3949ab", section=DHW_SECTION,
    roles=("dhw_active", "dhw_tank_temp", "dhw_setpoint", "electricity_meter", "flow_temp", "return_temp", "flow_rate",
           "outdoor_temp", "outdoor_temp_reference", "immersion_heater", "heartbeat",
           # Grundgrößen Fühler-Offset (D4) und Datenqualität (D2, D8)
           "compressor_running", "pump_running", "defrost"),
    required_roles=("dhw_active", "dhw_tank_temp"),
    master_keys=("dhw_tank_volume_l", "immersion_heater_kw", "cold_water_c", "dhw_disinfection_interval_days",
                 "household"),
    names={"de": "Warmwasser", "en": "Hot water"},
    checks=(
        CheckSpec("W1", "dhw_efficiency", lambda ctx: w1.check_dhw_efficiency(
            ctx.dhw_charges, ctx.dq, ctx.offset_robust, ctx.meter_step, ctx.dhw_section_start)),
        CheckSpec("W2", "dhw_temperature", _w2),
        CheckSpec("W3", "disinfection", _w3),
        CheckSpec("W4", "standby_loss", _w4),
        CheckSpec("W5", "dhw_timing", lambda ctx: w1.check_dhw_timing(ctx.dhw_charges, ctx.outdoor_daily,
                                                                       ctx.dhw_section_start, ctx.tz, ctx.persons)),
        CheckSpec("W6", "dhw_draw", _w6),
    ),
    timeline=TimelineSpec(scale=_scale, point=_point,
                          metric_names={"de": "Gütegrad Warmwasser", "en": "Hot water Carnot efficiency"}),
)
