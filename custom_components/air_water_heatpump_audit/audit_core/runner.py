"""Rechnet die zugeschalteten Audits für einen Zeitraum aus fertigen Zeitreihen je Rolle.

Gemeinsam genutzt vom Prototyp (InfluxDB) und von der HA-Integration (Recorder). Welche Audits es gibt und was sie
brauchen, steht in der Registry (`audits.REGISTRY`); hier wird nur abgearbeitet. Fehlt eine Rolle, wird eine leere
Zeitreihe angenommen; die betroffenen Prüfungen enden dann in „nicht bewertbar“.
"""

from __future__ import annotations

from collections.abc import Callable

from . import days
from . import readiness as rd
from . import timeline as tl
from .actions import attach_actions
from .impact import annotate
from .audits import BY_ID, REGISTRY
from .context import HEATER_ROLES, ROLE_KEYS, Context, data_quality, section_start  # noqa: F401 (Schnittstelle)
from .registry import AuditSpec
from .result import HINT, INFO, NOT_ASSESSABLE, OK, WARN, CheckResult, mark_provisional, overall
from .series import Series

DATA_BASIS, EFFICIENCY, FLOW_TEMPERATURE, CAPACITY = "data_basis", "efficiency", "flow_temperature", "capacity"
BEFORE_MAX_SECTIONS = 3  # so weit sucht attach_before() zurück
BEFORE_MIN_S = 3600  # kürzere Abschnitte (zwei Ereignisse kurz hintereinander) überspringt die Suche


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
    def context(until: float, upto: list[dict] | None, ctl: dict | None) -> Context:
        return Context(s, start, until, recorder_keep_days=recorder_keep_days, long_term_days=long_term_days,
                       heater_kw=heater_kw, master=master, events=upto, controls=ctl, tz=tz)

    ctx = context(end, events, controls)
    prior: dict[float, Context] = {}  # Ereigniszeit → Lauf bis zu diesem Ereignis, für attach_before()

    def until(t: float) -> Context:
        if t not in prior:
            prior[t] = context(t, [e for e in events or [] if e["time"] < t], None)
        return prior[t]

    specs = selected(audits)
    report_audits, readiness = {}, {}
    for spec in specs:
        results = run_spec(spec, ctx)
        attach_before(spec, ctx, results, until)
        since = ctx.since(spec.section)
        readiness[spec.audit_id] = rd.audit_readiness(since, results, end, tz)
        with_actions = attach_actions(results, ctx.controls)
        annotate(with_actions, ctx.year_basis)  # Wirkung in €/Jahr und Zielkonflikte (Spezifikation 1.10)
        report_audits[spec.audit_id] = {"verdict": overall(results), "dq": ctx.dq, "event": ctx.event_of(spec.section),
                                        "checks": [r.as_dict() for r in with_actions]}
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


def run_spec(spec: AuditSpec, ctx: Context) -> list[CheckResult]:
    results = [c.run(ctx) for c in spec.checks]
    if spec.finish:
        spec.finish(ctx, results)
    for r in results:
        mark_provisional(r)
    return results


def attach_before(spec: AuditSpec, ctx: Context, results: list[CheckResult],
                  until: Callable[[float], Context]) -> None:
    """Vorläufige und nicht bewertbare Prüfungen bekommen das letzte belastbare Urteil vor dem Ereignis (F239).

    Gesucht wird abschnittsweise rückwärts, höchstens BEFORE_MAX_SECTIONS weit; ein vorläufiges Urteil davor gilt
    nur, wenn kein belastbares kommt. until(t) liefert den Laufkontext bis zum Zeitpunkt t.
    """
    open_ids = {r.check_id for r in results if r.provisional or r.verdict == NOT_ASSESSABLE}
    event = ctx.event_of(spec.section)
    if not open_ids or event is None:
        return
    found: dict[str, dict] = {}
    t = event["time"]
    for _ in range(BEFORE_MAX_SECTIONS):
        pc = until(t)
        sec_start = pc.since(spec.section)
        if t - sec_start >= BEFORE_MIN_S:
            for r in run_spec(spec, pc):
                if r.check_id not in open_ids or r.verdict not in (OK, HINT, WARN, INFO):
                    continue
                if r.check_id not in found or (found[r.check_id]["provisional"] and not r.provisional):
                    found[r.check_id] = {"verdict": r.verdict, "value": r.value, "unit": r.unit, "text": r.text,
                                         "provisional": r.provisional, "start": sec_start, "end": t,
                                         "event": pc.event_of(spec.section)}
        if all(i in found and not found[i]["provisional"] for i in open_ids) or sec_start <= ctx.start:
            break
        t = sec_start
    for r in results:
        r.before = found.get(r.check_id) if r.check_id in open_ids else None



__all__ = ["BY_ID", "REGISTRY", "ROLE_KEYS", "HEATER_ROLES", "run_audits", "roles_for", "selected", "data_quality",
           "section_start", "DATA_BASIS", "EFFICIENCY", "FLOW_TEMPERATURE", "CAPACITY"]
