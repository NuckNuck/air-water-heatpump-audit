"""Config Flow: zuerst Profile und Audits wählen, dann sieben Schritte Rollen (Betriebssignale, Messwerte, Werte der
Steuerung, Heizkreis, Warmwasser, Tarif, Stellgrößen). Gibt es noch einen Eintrag der Vorgänger-Integration „WP-Audit“, lässt er sich
stattdessen übernehmen. Options Flow für Stammdaten; Untereinträge für Audits („Audit hinzufügen“), Ereignisse und
Personen im Haushalt.
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
from .audit_core.household import PRESENCE_MODES, SHOWER_TIMES, WEEKDAYS
from .audit_core.audits import BY_ID, REGISTRY
from .const import (CONF_AUDIT, CONF_AUDITS, CONF_IMPORT_TIMELINE_FROM, LEGACY_DOMAIN, SUBENTRY_AUDIT, audit_title,
                    language, migrate_roles)
from .const import (CONF_BATHS_PER_WEEK, CONF_BIRTH_YEAR, CONF_COLD_WATER_C, CONF_DHW_DISINFECTION_INTERVAL_DAYS,
                    CONF_EVERY_N_WEEKS, CONF_LIVING_AREA_M2, CONF_PERSON_NAME, CONF_PRESENCE, CONF_ROTATION_START, CONF_SHARE_PCT,
                    CONF_SHOWER_TIME, CONF_SHOWERS_PER_WEEK, CONF_WEEKDAYS, CONF_WEEKS_ABSENT, CONF_WEEKS_PRESENT,
                    PRESENCE_FIELDS, SUBENTRY_PERSON)
from .const import (CONF_BOOSTER_HEATER_2_KW, CONF_BOOSTER_HEATER_KW, CONF_CAPACITY_MIN_TABLE,
                    CONF_CIRCUIT_FLOW_MAX_LPM, CONF_DATA_SINCE, CONF_DATA_SOURCE, CONF_DHW_TANK_VOLUME_L,
                    CONF_EVENT_KIND, CONF_EVENT_NOTE, CONF_EVENT_TIME, CONF_FLOW_RATE_MIN_LPM,
                    CONF_HEATING_DEGREE_DAYS, CONF_HEATING_HOURS, CONF_HOUSEHOLD_PRICE, CONF_HYDRAULIC_SEPARATION,
                    CONF_IMMERSION_HEATER_KW, CONF_REFERENCE_EFFICIENCY, CONF_REFERENCE_FUEL_PRICE,
                    CONF_ROOM_TEMP_TARGET, CONF_TARIFF_BASE_FEE, CONF_TARIFF_PRICE, CONF_WINDOW_DAYS, DATA_SOURCES, DEFAULT_OPTIONS, DOMAIN, EVENT_KIND_LABELS, EVENT_KINDS,
                    HYDRAULIC_SEPARATIONS, OPTION_SECTIONS, OPTIONAL_OPTIONS, ROLE_DOMAINS, ROLE_STEPS,
                    SUBENTRY_EVENT)
from .profiles import COMMON_ROLE_SUGGESTIONS, INTERFACE_PROFILES, MODEL_PROFILES, role_candidates

STEP_ORDER = list(ROLE_STEPS)
NO_PROFILE = "none"
CONF_INTERFACE_PROFILE = "interface_profile"
CONF_MODEL_PROFILE = "model_profile"


def _kw() -> selector.NumberSelector:
    return selector.NumberSelector(selector.NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="kW",
                                                                 mode=selector.NumberSelectorMode.BOX))


def _number(maximum: float, step: float, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(selector.NumberSelectorConfig(min=0, max=maximum, step=step, unit_of_measurement=unit,
                                                                 mode=selector.NumberSelectorMode.BOX))


async def energy_price(hass, meter: str | None) -> float | None:
    """Arbeitspreis aus dem Energie-Dashboard, wenn dort der Stromzähler der Wärmepumpe als Netzbezug steht."""
    if not meter:
        return None
    try:
        from homeassistant.components.energy.data import async_get_manager
        manager = await async_get_manager(hass)
    except Exception:  # noqa: BLE001 – ohne Energie-Dashboard gibt es keinen Vorschlag
        return None
    for source in (manager.data or {}).get("energy_sources", []):
        if source.get("type") != "grid":
            continue
        # bis HA 2025: Liste flow_from; danach eine Quelle je Zähler
        for flow in source.get("flow_from") or [source]:
            if flow.get("stat_energy_from") == meter and flow.get("number_energy_price"):
                return float(flow["number_energy_price"])
    return None


def _audit_selector(options: list[str], multiple: bool) -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(
        options=options, multiple=multiple, translation_key=CONF_AUDITS, mode=selector.SelectSelectorMode.LIST))


def _audit_subentries(audit_ids: list[str], lang: str) -> list[dict]:
    return [{"subentry_type": SUBENTRY_AUDIT, "data": {CONF_AUDIT: a}, "title": audit_title(a, lang), "unique_id": a}
            for a in audit_ids]


class AirWaterAuditConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._audits: list[str] = []
        self._reconfigure = False

    def _suggestions(self) -> dict[str, str]:
        """Je Rolle der Vorschlag des Profils: die erste Schreibweise, die es in dieser Instanz gibt."""
        out = dict(COMMON_ROLE_SUGGESTIONS)
        for role, candidates in role_candidates(self._data.get(CONF_INTERFACE_PROFILE, NO_PROFILE)).items():
            out[role] = next((eid for eid in candidates if self.hass.states.get(eid)), candidates[0])
        return out

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
            # Neu laden plant der Update-Listener (__init__.py); ein zweites Neuladen hier warnt HA ab 2026.10
            return self.async_update_and_abort(self._get_reconfigure_entry(), data=self._data)
        await self.async_set_unique_id(self._data.get("compressor_running") or DOMAIN)
        self._abort_if_unique_id_configured()
        model = MODEL_PROFILES.get(self._data.get(CONF_MODEL_PROFILE, NO_PROFILE), {})
        return self.async_create_entry(title="Luft-Wasser-Wärmepumpen-Audit", data=self._data,
                                       options=DEFAULT_OPTIONS | model,
                                       subentries=_audit_subentries(self._audits, language(self.hass)))

    def _legacy_entries(self) -> list[ConfigEntry]:
        return self.hass.config_entries.async_entries(LEGACY_DOMAIN)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Gibt es noch die Vorgänger-Integration, zuerst fragen: übernehmen oder neu einrichten."""
        if self._legacy_entries():
            return self.async_show_menu(step_id="user", menu_options=["import_legacy", "setup"])
        return await self.async_step_setup()

    async def async_step_import_legacy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Rollen, Stammdaten, Ereignisse und Zeitstrahl aus „WP-Audit“ übernehmen; alle Audits zuschalten."""
        old = self._legacy_entries()[0]
        if user_input is None:
            return self.async_show_form(step_id="import_legacy", description_placeholders={"title": old.title})
        data = migrate_roles(dict(old.data))
        ecodan = role_candidates("esphome_ecodan")
        if any(data.get(role) in eids for role, eids in ecodan.items()):
            data.setdefault(CONF_INTERFACE_PROFILE, "esphome_ecodan")  # die Vorgängerin belegte so vor
        data[CONF_IMPORT_TIMELINE_FROM] = old.entry_id
        await self.async_set_unique_id(data.get("compressor_running") or DOMAIN)
        self._abort_if_unique_id_configured()
        events = [{"subentry_type": SUBENTRY_EVENT, "data": dict(sub.data), "title": sub.title}
                  for sub in old.subentries.values() if sub.subentry_type == SUBENTRY_EVENT]
        return self.async_create_entry(
            title="Luft-Wasser-Wärmepumpen-Audit", data=data, options=DEFAULT_OPTIONS | dict(old.options),
            subentries=_audit_subentries([a.audit_id for a in REGISTRY], language(self.hass)) + events)

    async def async_step_setup(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Profile (Vorschläge für Rollen und Stammdaten, „Keins“ ist erlaubt) und die gewünschten Audits."""
        if user_input is not None:
            chosen = set(user_input.pop(CONF_AUDITS, []))
            self._audits = [a.audit_id for a in REGISTRY if a.audit_id in chosen]
            self._data.update(user_input)
            return await self._role_step("signals", None)
        def choice(key: str, options: list[str]) -> selector.SelectSelector:
            return selector.SelectSelector(selector.SelectSelectorConfig(
                options=[NO_PROFILE, *options], translation_key=key, mode=selector.SelectSelectorMode.DROPDOWN))
        return self.async_show_form(step_id="setup", data_schema=vol.Schema({
            vol.Required(CONF_INTERFACE_PROFILE, default=NO_PROFILE): choice(CONF_INTERFACE_PROFILE,
                                                                             list(INTERFACE_PROFILES)),
            vol.Required(CONF_MODEL_PROFILE, default=NO_PROFILE): choice(CONF_MODEL_PROFILE, list(MODEL_PROFILES)),
            vol.Required(CONF_AUDITS, default=[a.audit_id for a in REGISTRY if a.recommended]):
                _audit_selector([a.audit_id for a in REGISTRY], multiple=True),
        }))

    async def async_step_signals(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._role_step("signals", user_input)

    async def async_step_measurements(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._role_step("measurements", user_input)

    async def async_step_controller(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._role_step("controller", user_input)

    async def async_step_circuit(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._role_step("circuit", user_input)

    async def async_step_dhw(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._role_step("dhw", user_input)

    async def async_step_tariff(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._role_step("tariff", user_input)

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
        return {SUBENTRY_AUDIT: AuditSubentryFlow, SUBENTRY_EVENT: EventSubentryFlow,
                SUBENTRY_PERSON: PersonSubentryFlow}


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
        CONF_DHW_TANK_VOLUME_L: _number(5000, 1, "l"),
        CONF_COLD_WATER_C: _number(25, 0.5, "°C"),
        CONF_LIVING_AREA_M2: _number(2000, 1, "m²"),
        CONF_DHW_DISINFECTION_INTERVAL_DAYS: selector.NumberSelector(selector.NumberSelectorConfig(
            min=1, max=60, step=1, unit_of_measurement="d", mode=selector.NumberSelectorMode.BOX)),
        CONF_HEATING_DEGREE_DAYS: _number(8000, 1, "Kd"),
        CONF_TARIFF_PRICE: _number(2, 0.001, "€/kWh"),
        CONF_TARIFF_BASE_FEE: _number(1000, 0.01, "€/a"),
        CONF_HOUSEHOLD_PRICE: _number(2, 0.001, "€/kWh"),
        CONF_REFERENCE_FUEL_PRICE: _number(2, 0.001, "€/kWh"),
        CONF_REFERENCE_EFFICIENCY: _number(1.2, 0.01, ""),
        CONF_ROOM_TEMP_TARGET: selector.NumberSelector(selector.NumberSelectorConfig(
            min=15, max=26, step=0.5, unit_of_measurement="°C", mode=selector.NumberSelectorMode.BOX)),
        CONF_WINDOW_DAYS: selector.NumberSelector(selector.NumberSelectorConfig(
            min=1, max=365, step=1, unit_of_measurement="d", mode=selector.NumberSelectorMode.BOX)),
        CONF_DATA_SINCE: selector.DateTimeSelector(),
        CONF_DATA_SOURCE: selector.SelectSelector(selector.SelectSelectorConfig(
            options=DATA_SOURCES, translation_key=CONF_DATA_SOURCE, mode=selector.SelectSelectorMode.LIST)),
    }


class AirWaterAuditOptionsFlow(OptionsFlow):
    """Stammdaten (Spezifikation 1.4) in Abschnitten: Anlage, Warmwasser, Standort und Komfort, Kosten, Auswertung.

    Kein OptionsFlowWithReload: Das Neuladen übernimmt der Update-Listener, der auch auf Ereignisse reagiert.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = DEFAULT_OPTIONS | dict(self.config_entry.options)
        if current.get(CONF_TARIFF_PRICE) is None:  # nur Vorschlag; gespeichert wird erst beim Absenden
            current[CONF_TARIFF_PRICE] = await energy_price(self.hass, self.config_entry.data.get("electricity_meter"))
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
                    fields[vol.Optional(key, description={"suggested_value": value} if value is not None else None)] = selectors[key]
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


class AuditSubentryFlow(ConfigSubentryFlow):
    """Audit zuschalten. Abschalten = Untereintrag löschen; HA entfernt dann auch seine Entitäten."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        present = {sub.data.get(CONF_AUDIT) for sub in entry.subentries.values() if sub.subentry_type == SUBENTRY_AUDIT}
        free = [a.audit_id for a in REGISTRY if a.audit_id not in present]
        if not free:
            return self.async_abort(reason="all_audits_added")
        if user_input is not None:
            audit = user_input[CONF_AUDIT]
            missing = [r for r in BY_ID[audit].required_roles if not entry.data.get(r)]
            if missing and not user_input.get("confirmed"):
                # Pflicht-Messwerte fehlen: Hinweis zeigen, mit dem zweiten Absenden trotzdem zuschalten
                return self.async_show_form(
                    step_id="user", errors={"base": "missing_roles"},
                    description_placeholders={"missing": "\n\n" + ", ".join(missing)},
                    data_schema=vol.Schema({vol.Required(CONF_AUDIT, default=audit): _audit_selector(free, False),
                                            vol.Optional("confirmed", default=True): selector.BooleanSelector()}))
            return self.async_create_entry(title=audit_title(audit, language(self.hass)), data={CONF_AUDIT: audit},
                                           unique_id=audit)
        return self.async_show_form(step_id="user", description_placeholders={"missing": ""},
                                    data_schema=vol.Schema({vol.Required(CONF_AUDIT, default=free[0]):
                                                            _audit_selector(free, False)}))


def _select(key: str, options: tuple[str, ...] | list[str], multiple: bool = False) -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(
        options=list(options), translation_key=key, multiple=multiple, mode=selector.SelectSelectorMode.DROPDOWN))


def _optional(key: str, data: dict[str, Any]):
    value = data.get(key)
    return vol.Optional(key, description={"suggested_value": value} if value not in (None, "", []) else None)


class PersonSubentryFlow(ConfigSubentryFlow):
    """Person im Haushalt: Alter, Anwesenheit und Duschgewohnheiten (Warmwasserbedarf, Spezifikation 6.6).

    Zwei Schritte: zuerst Person und Muster, dann – nur wenn nötig – die Angaben zum Muster (z. B. Wechselwochen bei
    Kindern, die abwechselnd in zwei Haushalten wohnen). Leere Gewohnheiten ersetzt das Audit durch typische Werte."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def _person_schema(self, data: dict[str, Any]) -> vol.Schema:
        return vol.Schema({
            vol.Required(CONF_PERSON_NAME, default=data.get(CONF_PERSON_NAME, "")): selector.TextSelector(),
            _optional(CONF_BIRTH_YEAR, data): selector.NumberSelector(selector.NumberSelectorConfig(
                min=1900, max=2100, step=1, mode=selector.NumberSelectorMode.BOX)),
            vol.Required(CONF_PRESENCE, default=data.get(CONF_PRESENCE, "always")): _select(CONF_PRESENCE,
                                                                                            PRESENCE_MODES),
            _optional(CONF_SHOWERS_PER_WEEK, data): _number(28, 0.5, ""),
            _optional(CONF_BATHS_PER_WEEK, data): _number(14, 0.5, ""),
            vol.Required(CONF_SHOWER_TIME, default=data.get(CONF_SHOWER_TIME, "varied")): _select(CONF_SHOWER_TIME,
                                                                                                SHOWER_TIMES),
        })

    def _presence_schema(self, data: dict[str, Any]) -> vol.Schema:
        fields = {
            CONF_WEEKS_PRESENT: vol.Required(CONF_WEEKS_PRESENT, default=data.get(CONF_WEEKS_PRESENT, 1)),
            CONF_WEEKS_ABSENT: vol.Required(CONF_WEEKS_ABSENT, default=data.get(CONF_WEEKS_ABSENT, 1)),
            CONF_ROTATION_START: vol.Required(CONF_ROTATION_START, default=data.get(CONF_ROTATION_START)
                                              or dt_util.now().date().isoformat()),
            CONF_WEEKDAYS: vol.Required(CONF_WEEKDAYS, default=data.get(CONF_WEEKDAYS, ["sat", "sun"])),
            CONF_EVERY_N_WEEKS: vol.Required(CONF_EVERY_N_WEEKS, default=data.get(CONF_EVERY_N_WEEKS, 1)),
            CONF_SHARE_PCT: vol.Required(CONF_SHARE_PCT, default=data.get(CONF_SHARE_PCT, 50)),
        }
        weeks = selector.NumberSelector(selector.NumberSelectorConfig(min=0, max=12, step=1,
                                                                      mode=selector.NumberSelectorMode.BOX))
        selectors = {CONF_WEEKS_PRESENT: weeks, CONF_WEEKS_ABSENT: weeks, CONF_ROTATION_START: selector.DateSelector(),
                     CONF_WEEKDAYS: _select(CONF_WEEKDAYS, WEEKDAYS, multiple=True),
                     CONF_EVERY_N_WEEKS: selector.NumberSelector(selector.NumberSelectorConfig(
                         min=1, max=4, step=1, mode=selector.NumberSelectorMode.BOX)),
                     CONF_SHARE_PCT: _number(100, 1, "%")}
        return vol.Schema({fields[k]: selectors[k] for k in PRESENCE_FIELDS[data.get(CONF_PRESENCE, "always")]})

    def _clean(self, data: dict[str, Any]) -> dict[str, Any]:
        """Nur die Felder des gewählten Musters behalten; Zahlen als int, wo sie ganzzahlig sind."""
        keep = {CONF_PERSON_NAME, CONF_BIRTH_YEAR, CONF_PRESENCE, CONF_SHOWERS_PER_WEEK, CONF_BATHS_PER_WEEK,
                CONF_SHOWER_TIME, *PRESENCE_FIELDS[data.get(CONF_PRESENCE, "always")]}
        out = {k: v for k, v in data.items() if k in keep and v not in (None, "")}
        for k in (CONF_BIRTH_YEAR, CONF_WEEKS_PRESENT, CONF_WEEKS_ABSENT, CONF_EVERY_N_WEEKS):
            if k in out:
                out[k] = int(out[k])
        return out

    async def _person(self, step_id: str, user_input: dict[str, Any] | None, next_step: str):
        if user_input is None:
            return self.async_show_form(step_id=step_id, data_schema=self._person_schema(self._data))
        # Geleerte optionale Felder fehlen in user_input: dann „typisch fürs Alter“, nicht der alte Wert
        for k in (CONF_BIRTH_YEAR, CONF_SHOWERS_PER_WEEK, CONF_BATHS_PER_WEEK):
            self._data.pop(k, None)
        self._data.update(user_input)
        if PRESENCE_FIELDS[self._data[CONF_PRESENCE]]:
            return self.async_show_form(step_id=next_step, data_schema=self._presence_schema(self._data))
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._person("user", user_input, "presence") or self._create()

    async def async_step_presence(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._data.update(user_input or {})
        return self._create()

    def _create(self) -> SubentryFlowResult:
        data = self._clean(self._data)
        return self.async_create_entry(title=data[CONF_PERSON_NAME], data=data)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is None:
            self._data = dict(self._get_reconfigure_subentry().data)
        return await self._person("reconfigure", user_input, "reconfigure_presence") or self._update()

    async def async_step_reconfigure_presence(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._data.update(user_input or {})
        return self._update()

    def _update(self) -> SubentryFlowResult:
        data = self._clean(self._data)
        return self.async_update_and_abort(self._get_entry(), self._get_reconfigure_subentry(),
                                           title=data[CONF_PERSON_NAME], data=data)
