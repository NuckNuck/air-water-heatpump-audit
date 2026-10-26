"""Audit 1 – Effizienz: Wie gut arbeitet die Wärmepumpe? Einziges Urteil ist der Gütegrad E3 (Spezifikation 4.2)."""

from __future__ import annotations

from .. import efficiency as e1
from ..context import Context
from ..registry import SECTION, AuditSpec, CheckSpec, TimelineSpec
from ..result import FULL_DAYS, INFO, NOT_ASSESSABLE, WARN, HINT, OK, CheckResult, progress


def _finish(ctx: Context, results: list[CheckResult]) -> None:
    """Gültige volle Tage (Heartbeat, Mindeststrom): E1 braucht einen, E2–E4 eine Woche."""
    for r in results:
        r.progress = progress(len(ctx.daily_rows), 1 if r.check_id == "E1" else e1.WEEK_DAYS, "days", FULL_DAYS,
                              ctx.section_start)


def _point(ctx: Context, a: float, b: float, day: str) -> dict:
    row = next((r for r in ctx.daily_rows_window if r["day"] == day), None)
    if not row or not row["electricity_kwh"]:
        return {"value": None, "verdict": NOT_ASSESSABLE}
    eta = row["ideal_kwh"] / row["electricity_kwh"]
    return {"value": round(eta, 3), "verdict": e1.carnot_verdict(eta, ctx.offset_robust), "cop": row["cop"],
            "cop_raw": row["cop_raw"], "electricity_kwh": row["electricity_kwh"], "heat_kwh": row["heat_kwh"],
            "outdoor_mean": row["outdoor_mean"]}


def _scale(master: dict) -> dict:
    return {"metric": "carnot_efficiency", "unit": "", "min": 0, "max": 0.7, "decimals": 2,
            "bands": [[0, e1.CARNOT_WARN_BELOW, WARN], [e1.CARNOT_WARN_BELOW, e1.CARNOT_OK_MIN, HINT],
                      [e1.CARNOT_OK_MIN, e1.CARNOT_PLAUSIBLE_MAX, OK], [e1.CARNOT_PLAUSIBLE_MAX, 0.7, INFO]]}


AUDIT = AuditSpec(
    audit_id="efficiency", order=1, color="#8e24aa", section=SECTION,
    roles=("electricity_meter", "flow_temp", "return_temp", "flow_rate", "outdoor_temp", "dhw_active", "heartbeat",
           # Grundgrößen Fühler-Offset (D4) und Datenqualität (D2, D8)
           "compressor_running", "pump_running", "defrost"),
    required_roles=("electricity_meter", "flow_temp", "return_temp", "flow_rate", "outdoor_temp"),
    master_keys=(),
    names={"de": "Effizienz", "en": "Efficiency"},
    checks=(
        CheckSpec("E1", "daily_cop", lambda ctx: e1.check_daily_cop(ctx.daily_rows, ctx.offset_robust,
                                                                     ctx.meter_step)),
        CheckSpec("E2", "weekly_cop", lambda ctx: e1.check_weekly_cop(ctx.daily_rows)),
        CheckSpec("E3", "carnot_efficiency", lambda ctx: e1.check_carnot_efficiency(ctx.daily_rows, ctx.dq,
                                                                                     ctx.offset_robust)),
        CheckSpec("E4", "dhw_share", lambda ctx: e1.check_dhw_share(ctx.daily_rows)),
    ),
    timeline=TimelineSpec(scale=_scale, point=_point),
    finish=_finish,
)
