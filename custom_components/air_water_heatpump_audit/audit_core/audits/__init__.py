"""Alle Audits in Anzeige-Reihenfolge. Neues Audit: Modul mit `AUDIT` anlegen und hier eintragen."""

from __future__ import annotations

from ..context import ROLE_KEYS
from ..registry import AuditSpec, validate
from . import capacity, cost, data_basis, dhw, efficiency, flow_temperature

REGISTRY: list[AuditSpec] = sorted([data_basis.AUDIT, efficiency.AUDIT, flow_temperature.AUDIT, capacity.AUDIT, dhw.AUDIT,
                                    cost.AUDIT], key=lambda a: a.order)
BY_ID: dict[str, AuditSpec] = {a.audit_id: a for a in REGISTRY}
validate(REGISTRY, ROLE_KEYS)
