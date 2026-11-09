"""Reparaturen: fehlende feste Kosten der Wärmepumpe direkt aus „Einstellungen → Reparaturen“ nachtragen.

Das Issue entsteht beim Laden des Eintrags, wenn das Kosten-Audit aktiv ist und Zählerart, Grundpreis des WP-Tarifs
oder Messstellenentgelt fehlen (audit_core.cost.heat_pump_fixed_costs). Der Fix-Flow zeigt nur diese drei Felder und
schreibt sie in die Optionen; das Neuladen räumt das Issue dann ab.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir, selector

from .audit_core.cost import FIXED_COST_LABELS, heat_pump_fixed_costs
from .const import (CONF_HEAT_PUMP_METER, CONF_METER_FEE, CONF_TARIFF_BASE_FEE, DEFAULT_OPTIONS, DOMAIN,
                    FIXED_COST_KEYS, HEAT_PUMP_METERS)

ISSUE_FIXED_COSTS = "fixed_costs_missing"
COST_AUDIT = "cost"


def issue_id(entry_id: str) -> str:
    return f"{ISSUE_FIXED_COSTS}_{entry_id}"


def update_fixed_cost_issue(hass: HomeAssistant, entry, audits: list[str]) -> None:
    """Issue anlegen oder entfernen, je nachdem ob für das Kosten-Audit feste Kosten fehlen."""
    options = DEFAULT_OPTIONS | dict(entry.options)
    missing = heat_pump_fixed_costs(options)[1] if COST_AUDIT in audits else ()
    if not missing:
        ir.async_delete_issue(hass, DOMAIN, issue_id(entry.entry_id))
        return
    ir.async_create_issue(hass, DOMAIN, issue_id(entry.entry_id), is_fixable=True, is_persistent=False,
                          severity=ir.IssueSeverity.WARNING, translation_key=ISSUE_FIXED_COSTS,
                          translation_placeholders={"missing": ", ".join(FIXED_COST_LABELS[k] for k in missing)},
                          data={"entry_id": entry.entry_id})


def _fee() -> selector.NumberSelector:
    return selector.NumberSelector(selector.NumberSelectorConfig(min=0, max=1000, step=0.01, unit_of_measurement="€/a",
                                                                 mode=selector.NumberSelectorMode.BOX))


class FixedCostsRepairFlow(RepairsFlow):
    """Ein Formular mit Zählerart, Grundpreis des WP-Tarifs und Messstellenentgelt."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        # HA übergibt hier {"issue_id": …}; das ist keine Formulareingabe.
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_missing")
        current = DEFAULT_OPTIONS | dict(entry.options)
        if user_input is not None:
            # Geleerte Felder fehlen in user_input: „nicht eingetragen“, nicht der alte Wert.
            new = {k: None for k in FIXED_COST_KEYS} | {k: v for k, v in user_input.items() if k in FIXED_COST_KEYS}
            # „issue_id“ stammt aus 0.18.0b2/b3, als der erste Schritt diese Übergabe als Eingabe gespeichert hat
            kept = {k: v for k, v in entry.options.items() if k != "issue_id"}
            self.hass.config_entries.async_update_entry(entry, options=kept | new)
            return self.async_create_entry(data={})
        fields = {}
        for key, sel in ((CONF_HEAT_PUMP_METER, selector.SelectSelector(selector.SelectSelectorConfig(
                options=HEAT_PUMP_METERS, translation_key=CONF_HEAT_PUMP_METER,
                mode=selector.SelectSelectorMode.LIST))), (CONF_TARIFF_BASE_FEE, _fee()), (CONF_METER_FEE, _fee())):
            value = current.get(key)
            fields[vol.Optional(key, description={"suggested_value": value} if value is not None else None)] = sel
        missing = heat_pump_fixed_costs(current)[1]
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema(fields), description_placeholders={
            "missing": ", ".join(FIXED_COST_LABELS[k] for k in missing) or "–"})


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None) -> RepairsFlow:
    return FixedCostsRepairFlow((data or {})["entry_id"])
