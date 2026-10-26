"""Rechnet die zugeschalteten Audits für einen Zeitraum aus fertigen Zeitreihen je Rolle.

Gemeinsam genutzt vom Prototyp (InfluxDB) und von der HA-Integration (Recorder). Welche Audits es gibt und was sie
brauchen, steht in der Registry (`audits.REGISTRY`); hier wird nur abgearbeitet. Fehlt eine Rolle, wird eine leere
Zeitreihe angenommen; die betroffenen Prüfungen enden dann in „nicht bewertbar“.
"""

from __future__ import annotations

from . import days
from . import readiness as rd
from . import timeline as tl
from .actions import attach_actions
from .audits import BY_ID, REGISTRY
from .context import HEATER_ROLES, ROLE_KEYS, Context, data_quality, section_start  # noqa: F401 (Schnittstelle)
from .registry import AuditSpec
from .result import overall
from .series import Series

DATA_BASIS, EFFICIENCY, FLOW_TEMPERATURE, CAPACITY = "data_basis", "efficiency", "flow_temperature", "capacity"


def selected(audit_ids: list[str] | None) -> list[AuditSpec]:
    """Zugeschaltete Audits in Registry-Reihenfolge; None = alle."""
    return list(REGISTRY) if audit_ids is None else [a for a in REGISTRY if a.audit_id in set(audit_ids)]


def roles_for(audit_ids: list[str] | None) -> set[str]:
    """Rollen, die die zugeschalteten Audits lesen; nur diese muss die Datenquelle laden."""
    return {r for a in selected(audit_ids) for r in a.roles}


def run_audits(s: dict[str, Series], start: float, end: float, *, recorder_keep_days: float | None,
               long_term_days: float | None, heater_kw: dict[str, float | None], master: dict | None = None,
               events: list[dict] | None = None, controls: dict[str, dict] | None = None,
               tz: str = days.DEFAULT_TZ, audits: list[str] | None = None) -> dict:
    """master: Stammdaten (Spezifikation 1.4). events: Änderungen an der Anlage ({time, kind, note}); Audits mit
    `section == "section"` rechnen nur ab dem letzten Ereignis, damit nie über eine Änderung hinweg gemittelt wird.
    controls: heutiger Zustand der Stellgrößen-Rollen (actions.CONTROL_ROLES); daraus entstehen Vorschläge.
    audits: IDs der zugeschalteten Audits, None = alle.
    """
    ctx = Context(s, start, end, recorder_keep_days=recorder_keep_days, long_term_days=long_term_days,
                  heater_kw=heater_kw, master=master, events=events, controls=controls, tz=tz)
    specs = selected(audits)
    report_audits, readiness = {}, {}
    for spec in specs:
        results = [c.run(ctx) for c in spec.checks]
        if spec.finish:
            spec.finish(ctx, results)
        since = ctx.since(spec.section)
        readiness[spec.audit_id] = rd.audit_readiness(since, results, end, tz)
        report_audits[spec.audit_id] = {"verdict": overall(results), "dq": ctx.dq,
                                        "checks": [r.as_dict() for r in attach_actions(results, ctx.controls)]}
    with_timeline = [a for a in specs if a.timeline]
    report = {
        "period": {"start": start, "end": end},
        "timeline": {"days": tl.daily_points(ctx, with_timeline),
                     "scales": {a.audit_id: a.timeline.scale(ctx.master) for a in with_timeline}},
        "section": {"start": ctx.section_start, "event": ctx.event},
        "readiness": readiness,
        "audits": report_audits,
    }
    if DATA_BASIS in report_audits:
        report["heat"] = ctx.heat_summary
    if CAPACITY in report_audits:
        report["cycles"] = [vars(c) | {"duration_min": round(c.duration / 60, 1)} for c in ctx.cycles]
    return report


__all__ = ["BY_ID", "REGISTRY", "ROLE_KEYS", "HEATER_ROLES", "run_audits", "roles_for", "selected", "data_quality",
           "section_start", "DATA_BASIS", "EFFICIENCY", "FLOW_TEMPERATURE", "CAPACITY"]
