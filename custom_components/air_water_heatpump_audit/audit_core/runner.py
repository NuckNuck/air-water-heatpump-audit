"""Rechnet die zugeschalteten Audits für einen Zeitraum aus fertigen Zeitreihen je Rolle.

Gemeinsam genutzt vom Prototyp (InfluxDB) und von der HA-Integration (Recorder). Welche Audits es gibt und was sie
brauchen, steht in der Registry (`audits.REGISTRY`); hier wird nur abgearbeitet. Fehlt eine Rolle, wird eine leere
Zeitreihe angenommen; die betroffenen Prüfungen enden dann in „nicht bewertbar“.
"""

from __future__ import annotations

from . import cost, days
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


def selected(audit_ids: list[str] | None) -> list[AuditSpec]:
    """Zugeschaltete Audits in Registry-Reihenfolge; None = alle."""
    return list(REGISTRY) if audit_ids is None else [a for a in REGISTRY if a.audit_id in set(audit_ids)]


def roles_for(audit_ids: list[str] | None) -> set[str]:
    """Rollen, die die zugeschalteten Audits lesen; nur diese muss die Datenquelle laden."""
    return {r for a in selected(audit_ids) for r in a.roles}


def run_audits(s: dict[str, Series], start: float, end: float, *, recorder_keep_days: float | None,
               long_term_days: float | None, heater_kw: dict[str, float | None], master: dict | None = None,
               events: list[dict] | None = None, controls: dict[str, dict] | None = None,
               tz: str = days.DEFAULT_TZ, audits: list[str] | None = None,
               price_refs: list[dict] | None = None, statistics: dict | None = None,
               configured_roles: set[str] | None = None) -> dict:
    """master: Stammdaten (Spezifikation 1.4). events: Änderungen an der Anlage ({time, kind, note}). Sie sind nur
    Markierungen (Spezifikation 1.5, #39): Jedes Audit rechnet über sein volles Fenster, ein Ereignis setzt nichts
    zurück. Ob sich seitdem etwas verschlechtert, zeigt der Zeitstrahl.
    configured_roles: zugeordnete Rollen; Prüfungen mit `needs_role` außerhalb davon entfallen. None = alle zeigen.
    controls: heutiger Zustand der Stellgrößen-Rollen (actions.CONTROL_ROLES); daraus entstehen Vorschläge.
    audits: IDs der zugeschalteten Audits, None = alle.
    price_refs: Preis-Sensoren anderer Heizsysteme für den Kosten-Zeitstrahl (heating_prices), None = abgeschaltet.
    Arbeitspreise in master dürfen in ct/kWh stehen (`<feld>_unit`); die Audits sehen sie in €/kWh.
    statistics: Tageswerte der Langzeitstatistik für die Statistik-Tage (long_term.py, Spezifikation 1.11), None = keine.
    """
    master = None if master is None else cost.prices_in_euro(master)
    def context(until: float, upto: list[dict] | None, ctl: dict | None) -> Context:
        return Context(s, start, until, recorder_keep_days=recorder_keep_days, long_term_days=long_term_days,
                       heater_kw=heater_kw, master=master, events=upto, controls=ctl, tz=tz,
                       price_refs=price_refs, statistics=statistics)

    ctx = context(end, events, controls)
    specs = selected(audits)
    report_audits, readiness = {}, {}
    for spec in specs:
        results = run_spec(spec, ctx, configured_roles)
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
                     "scales": {a.audit_id: a.timeline.scale(ctx.timeline_master) for a in with_timeline}},
        "section": {"start": ctx.section_start, "event": ctx.event},
        "readiness": readiness,
        "audits": report_audits,
    }
    if DATA_BASIS in report_audits:
        report["heat"] = ctx.heat_summary
    if CAPACITY in report_audits:
        report["cycles"] = [vars(c) | {"duration_min": round(c.duration / 60, 1)} for c in ctx.cycles]
    return report


def applies(check, configured_roles: set[str] | None) -> bool:
    """Prüfung mit vorausgesetzter Rolle nur, wenn die Rolle zugeordnet ist (z. B. K4 nur mit dynamischem Tarif, #40)."""
    return check.needs_role is None or configured_roles is None or check.needs_role in configured_roles


def run_spec(spec: AuditSpec, ctx: Context, configured_roles: set[str] | None = None) -> list[CheckResult]:
    results = [c.run(ctx) for c in spec.checks if applies(c, configured_roles)]
    if spec.finish:
        spec.finish(ctx, results)
    for r in results:
        mark_provisional(r)
    return results





__all__ = ["BY_ID", "REGISTRY", "ROLE_KEYS", "HEATER_ROLES", "run_audits", "roles_for", "selected", "data_quality",
           "section_start", "DATA_BASIS", "EFFICIENCY", "FLOW_TEMPERATURE", "CAPACITY"]
