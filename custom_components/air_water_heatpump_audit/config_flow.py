"""Config Flow: zuerst Profile wählen (Schnittstelle, Modell), dann fünf Schritte Rollen (Betriebssignale, Messwerte,
Werte der Steuerung, Heizkreis, Stellgrößen). Options Flow für Stammdaten, Untereinträge für Ereignisse.
Reconfigure geht die Rollen-Schritte mit den gespeicherten Zuordnungen durch.

Jede Rolle ist optional: fehlt sie, enden die abhängigen Prüfungen in „nicht bewertbar“. Vorbelegt wird aus dem
gewählten Schnittstellen-Profil, aber nur mit Entitäten, die es in dieser HA-Instanz gibt.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (ConfigEntry, ConfigFlow, ConfigFlowResult, ConfigSubentryFlow, OptionsFlow,
                                          SubentryFlowResult)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .audit_core.heat import parse_capacity_table
from .const import (CONF_BOOSTER_HEATER_2_KW, CONF_BOOSTER_HEATER_KW, CONF_CAPACITY_MIN_TABLE,
                    CONF_CIRCUIT_FLOW_MAX_LPM, CONF_DATA_SINCE, CONF_DATA_SOURCE, CONF_EVENT_KIND, CONF_EVENT_NOTE,
                    CONF_EVENT_TIME, CONF_FLOW_RATE_MIN_LPM, CONF_HEATING_HOURS, CONF_HYDRAULIC_SEPARATION, CONF_IMMERSION_HEATER_KW, CONF_ROOM_TEMP_TARGET,
                    CONF_WINDOW_DAYS, DATA_SOURCES, DEFAULT_OPTIONS, DOMAIN, EVENT_KIND_LABELS, EVENT_KINDS,
                    HYDRAULIC_SEPARATIONS, OPTION_SECTIONS, OPTIONAL_OPTIONS, ROLE_DOMAINS, ROLE_STEPS,
                    SUBENTRY_EVENT)
from .profiles import COMMON_ROLE_SUGGESTIONS, INTERFACE_PROFILES, MODEL_PROFILES

STEP_ORDER = list(ROLE_STEPS)
NO_PROFILE = "none"
CONF_INTERFACE_PROFILE = "interface_profile"
CONF_MODEL_PROFILE = "model_profile"


def _kw() -> selector.NumberSelector:
    return selector.NumberSelector(selector.NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kW",
                                                                 mode=selector.NumberSelectorMode.BOX))


class AirWaterAuditConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._reconfigure = False

    def _suggestions(self) -> dict[str, str]:
        return COMMON_ROLE_SUGGESTIONS | INTERFACE_PROFILES.get(self._data.get(CONF_INTERFACE_PROFILE, NO_PROFILE), {})

    def _role_schema(self, step: str) -> vol.Schema:
        fields = {}
        suggestions = self._suggestions()
        for role in ROLE_STEPS[step]:
            default = suggestions.get(role)
            if self._reconfigure:
                suggested = self._data.get(role) or None  # bewusst geleerte Rollen nicht neu vorbelegen
                if role not in self._data and default and self.hass.states.get(default):
                    suggested = default  # neu hinzugekommene Rolle
            else:
                suggested = self._data.get(role) or (default if default and self.hass.states.get(default) else None)
            key = vol.Optional(role, description={"suggested_value": suggested} if suggested else None)
            fields[key] = selector.EntitySelector(selector.EntitySelectorConfig(domain=ROLE_DOMAINS.get(role, ["sensor"])))
        return vol.Schema(fields)

    async def _role_step(self, step: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id=step, data_schema=self._role_schema(step))
        self._data.update({r: user_input.get(r, "") for r in ROLE_STEPS[step]})
        following = STEP_ORDER[STEP_ORDER.index(step) + 1:]
        if following:
            return await getattr(self, f"async_step_{following[0]}")()
        if self._reconfigure:
            return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data=self._data)
        await self.async_set_unique_id(self._data.get("compressor_running") or DOMAIN)
        self._abort_if_unique_id_configured()
        model = MODEL_PROFILES.get(self._data.get(CONF_MODEL_PROFILE, NO_PROFILE), {})
        return self.async_create_entry(title="Luft-Wasser-Wärmepumpen-Audit", data=self._data, options=DEFAULT_OPTIONS | model)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Profile: Vorschläge für die Rollen (Schnittstelle) und für die Stammdaten (Modell). „Keins“ ist erlaubt."""
        if user_input is not None:
            self._data.update(user_input)
            return await self._role_step("signals", None)
        def choice(key: str, options: list[str]) -> selector.SelectSelector:
            return selector.SelectSelector(selector.SelectSelectorConfig(
                options=[NO_PROFILE, *options], translation_key=key, mode=selector.SelectSelectorMode.DROPDOWN))
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required(CONF_INTERFACE_PROFILE, default=NO_PROFILE): choice(CONF_INTERFACE_PROFILE,
                                                                             list(INTERFACE_PROFILES)),
            vol.Required(CONF_MODEL_PROFILE, default=NO_PROFILE): choice(CONF_MODEL_PROFILE, list(MODEL_PROFILES)),
        }))

    async def async_step_signals(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._role_step("signals", user_input)

    async def async_step_measurements(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._role_step("measurements", user_input)

    async def async_step_controller(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._role_step("controller", user_input)

    async def async_step_circuit(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._role_step("circuit", user_input)

    async def async_step_controls(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._role_step("controls", user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._reconfigure = True
        self._data = dict(self._get_reconfigure_entry().data)
        return await self._role_step("signals", None)

    @staticmethod
    def async_get_options_flow(config_entry) -> AirWaterAuditOptionsFlow:
        return AirWaterAuditOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_EVENT: EventSubentryFlow}


def _option_selectors() -> dict[str, Any]:
    return {
        CONF_HYDRAULIC_SEPARATION: selector.SelectSelector(selector.SelectSelectorConfig(
            options=HYDRAULIC_SEPARATIONS, translation_key=CONF_HYDRAULIC_SEPARATION,
            mode=selector.SelectSelectorMode.DROPDOWN)),
        CONF_FLOW_RATE_MIN_LPM: selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=200, step=0.1, unit_of_measurement="l/min", mode=selector.NumberSelectorMode.BOX)),
        CONF_CIRCUIT_FLOW_MAX_LPM: selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=500, step=0.1, unit_of_measurement="l/min", mode=selector.NumberSelectorMode.BOX)),
        CONF_CAPACITY_MIN_TABLE: selector.ObjectSelector(),
        CONF_IMMERSION_HEATER_KW: _kw(),
        CONF_BOOSTER_HEATER_KW: _kw(),
        CONF_BOOSTER_HEATER_2_KW: _kw(),
        CONF_HEATING_HOURS: selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=8760, step=1, unit_of_measurement="h", mode=selector.NumberSelectorMode.BOX)),
        CONF_ROOM_TEMP_TARGET: selector.NumberSelector(selector.NumberSelectorConfig(
            min=15, max=26, step=0.5, unit_of_measurement="°C", mode=selector.NumberSelectorMode.BOX)),
        CONF_WINDOW_DAYS: selector.NumberSelector(selector.NumberSelectorConfig(
            min=1, max=365, step=1, unit_of_measurement="d", mode=selector.NumberSelectorMode.BOX)),
        CONF_DATA_SINCE: selector.DateTimeSelector(),
        CONF_DATA_SOURCE: selector.SelectSelector(selector.SelectSelectorConfig(
            options=DATA_SOURCES, translation_key=CONF_DATA_SOURCE, mode=selector.SelectSelectorMode.LIST)),
    }


class AirWaterAuditOptionsFlow(OptionsFlow):
    """Stammdaten (Spezifikation 1.4) in drei Abschnitten: Anlage, Standort und Komfort, Auswertung.

    Kein OptionsFlowWithReload: Das Neuladen übernimmt der Update-Listener, der auch auf Ereignisse reagiert.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = DEFAULT_OPTIONS | dict(self.config_entry.options)
        if user_input is not None:
            flat = {k: v for section in user_input.values() for k, v in section.items()}
            # Ein geleertes optionales Feld fehlt in user_input; dann gilt „kein Wert“, nicht der alte.
            flat = {k: None for k in OPTIONAL_OPTIONS} | flat
            try:
                parse_capacity_table(flat[CONF_CAPACITY_MIN_TABLE])
            except ValueError:
                errors["base"] = "invalid_capacity_table"
            else:
                return self.async_create_entry(data=flat)
            current |= flat
        selectors = _option_selectors()
        schema = {}
        for name, keys in OPTION_SECTIONS.items():
            fields = {}
            for key in keys:
                if key in OPTIONAL_OPTIONS:
                    value = current.get(key)
                    fields[vol.Optional(key, description={"suggested_value": value} if value else None)] = selectors[key]
                else:
                    fields[vol.Required(key, default=current[key])] = selectors[key]
            schema[vol.Required(name)] = section(vol.Schema(fields), {"collapsed": name == "evaluation"})
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema), errors=errors)


class EventSubentryFlow(ConfigSubentryFlow):
    """Ereignis (Spezifikation 1.5): Änderung an der Anlage mit Zeitpunkt. Audits 1–3 rechnen ab dem letzten."""

    def _schema(self, data: dict[str, Any]) -> vol.Schema:
        note = data.get(CONF_EVENT_NOTE)
        return vol.Schema({
            vol.Required(CONF_EVENT_TIME, default=data.get(CONF_EVENT_TIME) or dt_util.now().strftime(
                "%Y-%m-%d %H:%M:00")): selector.DateTimeSelector(),
            vol.Required(CONF_EVENT_KIND, default=data.get(CONF_EVENT_KIND, "heating_curve")): selector.SelectSelector(
                selector.SelectSelectorConfig(options=EVENT_KINDS, translation_key=CONF_EVENT_KIND,
                                              mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(CONF_EVENT_NOTE, description={"suggested_value": note} if note else None):
                selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
        })

    def _title(self, data: dict[str, Any]) -> str:
        labels = EVENT_KIND_LABELS["de" if (self.hass.config.language or "en").startswith("de") else "en"]
        when = dt_util.parse_datetime(data[CONF_EVENT_TIME])
        stamp = when.strftime("%d.%m.%Y %H:%M") if when else data[CONF_EVENT_TIME]
        return f"{stamp} · {labels.get(data[CONF_EVENT_KIND], data[CONF_EVENT_KIND])}"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            data = {CONF_EVENT_NOTE: ""} | user_input
            return self.async_create_entry(title=self._title(data), data=data)
        return self.async_show_form(step_id="user", data_schema=self._schema({}))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            data = {CONF_EVENT_NOTE: ""} | user_input
            return self.async_update_and_abort(self._get_entry(), subentry, title=self._title(data), data=data)
        return self.async_show_form(step_id="reconfigure", data_schema=self._schema(dict(subentry.data)))
