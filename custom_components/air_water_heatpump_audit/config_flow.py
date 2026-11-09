"""Config Flow: zuerst Profile und Audits wählen, dann sieben Schritte Rollen (Betriebssignale, Messwerte, Werte der
Steuerung, Heizkreis, Warmwasser, Tarif, Stellgrößen). Gibt es noch einen Eintrag der Vorgänger-Integration „WP-Audit“, lässt er sich
stattdessen übernehmen. Options Flow mit Menü: Anlagendaten (Stammdaten) und Haushalt (Personen). Untereinträge nur
für Audits („Audit hinzufügen“); Ereignisse verwaltet die Zeitstrahl-Karte (records.py).
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
from .audit_core.cost import heat_pump_fixed_costs
from .audit_core.heating_prices import NO_PREVIOUS_SYSTEM, consumption_kwh
from .audit_core.household import PRESENCE_MODES, SHOWER_TIMES, WEEKDAYS
from .audit_core.audits import BY_ID, REGISTRY
from .const import (CONF_AUDIT, CONF_AUDITS, CONF_IMPORT_TIMELINE_FROM, LEGACY_DOMAIN, SUBENTRY_AUDIT, audit_title,
                    language, migrate_roles)
from .const import (CONF_BATHS_PER_WEEK, CONF_BIRTH_YEAR, CONF_COLD_WATER_C, CONF_DHW_DISINFECTION_INTERVAL_DAYS,
                    CONF_EVERY_N_WEEKS, CONF_LIVING_AREA_M2, CONF_PERSON_NAME, CONF_PRESENCE, CONF_ROTATION_START, CONF_SHARE_PCT,
                    CONF_SHOWER_TIME, CONF_SHOWERS_PER_WEEK, CONF_WEEKDAYS, CONF_WEEKS_ABSENT, CONF_WEEKS_PRESENT,
                    PRESENCE_FIELDS)
from .const import (CONF_BOOSTER_HEATER_2_KW, CONF_BOOSTER_HEATER_KW, CONF_CAPACITY_MIN_TABLE,
                    CONF_CIRCUIT_FLOW_MAX_LPM, CONF_DATA_SINCE, CONF_DATA_SOURCE, CONF_DHW_TANK_VOLUME_L,
                    CONF_FLOW_RATE_MIN_LPM,
                    CONF_HEATING_DEGREE_DAYS, CONF_HEATING_HOURS, CONF_HOUSEHOLD_PRICE, CONF_HYDRAULIC_SEPARATION,
                    CONF_COMPARE_HEATING_SYSTEMS, CONF_IMMERSION_HEATER_KW, CONF_REFERENCE_EFFICIENCY, CONF_REFERENCE_FUEL_PRICE,
                    CONF_ROOM_TEMP_TARGET, CONF_TARIFF_BASE_FEE, CONF_TARIFF_PRICE, CONF_WINDOW_DAYS, DATA_SOURCES, DEFAULT_OPTIONS, DOMAIN,
                    HYDRAULIC_SEPARATIONS, OPTION_SECTIONS, OPTIONAL_OPTIONS, ROLE_DOMAINS, ROLE_STEPS)
from .const import CONF_HOUSEHOLD, RECORD_ID, RECORD_KEYS
from .records import RECORDS_MINOR_VERSION, records, subentries_to_records, with_id
from .const import (CONF_HOUSEHOLD_PRICE_UNIT, CONF_METER_FEE_PERIOD, CONF_REFERENCE_FUEL_PRICE_UNIT,
                    CONF_TARIFF_BASE_FEE_PERIOD, CONF_TARIFF_PRICE_UNIT, FEE_PERIOD_DEFAULTS, FEE_PERIOD_OF, FEE_PERIODS,
                    PRICE_UNIT_DEFAULT, PRICE_UNIT_OF, PRICE_UNITS)
from .const import (CONF_HEAT_PUMP_METER, CONF_METER_FEE, CONF_PREVIOUS_CONSUMPTION, CONF_PREVIOUS_CONSUMPTION_UNIT,
                    CONF_PREVIOUS_HEATING_SYSTEM, CONSUMPTION_UNITS, HEAT_PUMP_METERS, PREVIOUS_HEATING_SYSTEMS)
from .profiles import COMMON_ROLE_SUGGESTIONS, INTERFACE_PROFILES, MODEL_PROFILES, role_candidates

STEP_ORDER = list(ROLE_STEPS)
CONF_PERSON = "person"  # Auswahl im Schritt „Haushalt“: id einer Person oder NEW_PERSON
NEW_PERSON = "new"
CONF_DELETE = "delete"
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
    MINOR_VERSION = RECORDS_MINOR_VERSION

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
        moved, _ = subentries_to_records(old)
        return self.async_create_entry(
            title="Luft-Wasser-Wärmepumpen-Audit", data=data, options=DEFAULT_OPTIONS | dict(old.options) | moved,
            subentries=_audit_subentries([a.audit_id for a in REGISTRY], language(self.hass)))

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
        return {SUBENTRY_AUDIT: AuditSubentryFlow}


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
        CONF_TARIFF_PRICE: _price(),
        CONF_TARIFF_PRICE_UNIT: price_unit_selector(),
        CONF_HEAT_PUMP_METER: selector.SelectSelector(selector.SelectSelectorConfig(
            options=HEAT_PUMP_METERS, translation_key=CONF_HEAT_PUMP_METER, mode=selector.SelectSelectorMode.LIST)),
        CONF_TARIFF_BASE_FEE: _number(1000, 0.01, "€"),
        CONF_TARIFF_BASE_FEE_PERIOD: fee_period_selector(),
        CONF_METER_FEE: _number(1000, 0.01, "€"),
        CONF_METER_FEE_PERIOD: fee_period_selector(),
        CONF_PREVIOUS_HEATING_SYSTEM: selector.SelectSelector(selector.SelectSelectorConfig(
            options=PREVIOUS_HEATING_SYSTEMS, translation_key=CONF_PREVIOUS_HEATING_SYSTEM,
            mode=selector.SelectSelectorMode.DROPDOWN)),
        CONF_PREVIOUS_CONSUMPTION: _number(1_000_000, 1, ""),
        CONF_PREVIOUS_CONSUMPTION_UNIT: selector.SelectSelector(selector.SelectSelectorConfig(
            options=CONSUMPTION_UNITS, translation_key=CONF_PREVIOUS_CONSUMPTION_UNIT,
            mode=selector.SelectSelectorMode.DROPDOWN)),
        CONF_HOUSEHOLD_PRICE: _price(),
        CONF_HOUSEHOLD_PRICE_UNIT: price_unit_selector(),
        CONF_REFERENCE_FUEL_PRICE: _price(),
        CONF_REFERENCE_FUEL_PRICE_UNIT: price_unit_selector(),
        CONF_REFERENCE_EFFICIENCY: _number(1.2, 0.01, ""),
        CONF_COMPARE_HEATING_SYSTEMS: selector.BooleanSelector(),
        CONF_ROOM_TEMP_TARGET: selector.NumberSelector(selector.NumberSelectorConfig(
            min=15, max=26, step=0.5, unit_of_measurement="°C", mode=selector.NumberSelectorMode.BOX)),
        CONF_WINDOW_DAYS: selector.NumberSelector(selector.NumberSelectorConfig(
            min=1, max=365, step=1, unit_of_measurement="d", mode=selector.NumberSelectorMode.BOX)),
        CONF_DATA_SINCE: selector.DateTimeSelector(),
        CONF_DATA_SOURCE: selector.SelectSelector(selector.SelectSelectorConfig(
            options=DATA_SOURCES, translation_key=CONF_DATA_SOURCE, mode=selector.SelectSelectorMode.LIST)),
    }


def _price() -> selector.NumberSelector:
    """Arbeitspreis ohne feste Einheit: die steht im Auswahlfeld daneben (ct/kWh oder €/kWh)."""
    return _number(200, 0.001, "")


def price_unit_selector() -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(options=PRICE_UNITS, translation_key="price_unit",
                                                                 mode=selector.SelectSelectorMode.LIST))


def price_units(options: dict) -> dict:
    """Einheit je Arbeitspreis für das Formular: gespeichert, sonst €/kWh für alte Werte, sonst Vorauswahl ct/kWh."""
    return {unit: options.get(unit) or ("eur_per_kwh" if options.get(price) is not None else PRICE_UNIT_DEFAULT)
            for price, unit in PRICE_UNIT_OF.items()}


def fee_period_selector() -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(options=FEE_PERIODS, translation_key="fee_period",
                                                                 mode=selector.SelectSelectorMode.LIST))


def fee_periods(options: dict) -> dict:
    """Zeitraum je Betrag für das Formular: gespeicherter Wert, sonst pro Jahr für alte Beträge, sonst Vorauswahl."""
    return {period: options.get(period) or ("year" if options.get(fee) is not None else FEE_PERIOD_DEFAULTS[period])
            for fee, period in FEE_PERIOD_OF.items()}


def consumption_error(options: dict) -> bool:
    """True, wenn ein früherer Verbrauch eingetragen ist, der sich mit System und Einheit nicht umrechnen lässt."""
    amount = options.get(CONF_PREVIOUS_CONSUMPTION)
    system = options.get(CONF_PREVIOUS_HEATING_SYSTEM)
    if not amount or system in (None, NO_PREVIOUS_SYSTEM):
        return False
    return consumption_kwh(system, amount, options.get(CONF_PREVIOUS_CONSUMPTION_UNIT)) is None


class AirWaterAuditOptionsFlow(OptionsFlow):
    """Menü: Anlagendaten (Stammdaten, Spezifikation 1.4, in Abschnitten) und Haushalt (Personen, Spezifikation 6.6).

    Kein OptionsFlowWithReload: Das Neuladen übernimmt der Update-Listener, der auch auf Ereignisse reagiert.
    Ereignisse und Personen stehen als Listen in den Optionen; jedes Speichern hier behält sie bei.
    """

    def __init__(self) -> None:
        self._person: dict[str, Any] = {}

    def _save(self, changes: dict[str, Any]) -> ConfigFlowResult:
        kept = {k: self.config_entry.options[k] for k in RECORD_KEYS if k in self.config_entry.options}
        return self.async_create_entry(data=kept | changes)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["plant", "household"])

    async def async_step_household(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Person zum Ändern wählen oder eine neue anlegen."""
        persons = records(self.config_entry, CONF_HOUSEHOLD)
        if user_input is not None:
            chosen = next((p for p in persons if p[RECORD_ID] == user_input[CONF_PERSON]), None)
            self._person = dict(chosen) if chosen else {}
            return await self.async_step_person()
        new = {"de": "Neue Person anlegen", "en": "Add a person"}[language(self.hass)]
        choices = [selector.SelectOptionDict(value=p[RECORD_ID], label=p.get(CONF_PERSON_NAME) or "?") for p in persons]
        choices.append(selector.SelectOptionDict(value=NEW_PERSON, label=new))
        return self.async_show_form(step_id="household", data_schema=vol.Schema({
            vol.Required(CONF_PERSON, default=choices[0]["value"]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=choices, mode=selector.SelectSelectorMode.LIST))}),
            description_placeholders={"count": str(len(persons))})

    async def async_step_person(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        existing = RECORD_ID in self._person
        if user_input is None:
            schema = person_schema(self._person)
            if existing:
                schema = schema.extend({vol.Optional(CONF_DELETE, default=False): selector.BooleanSelector()})
            return self.async_show_form(step_id="person", data_schema=schema)
        if user_input.pop(CONF_DELETE, False):
            return self._save({CONF_HOUSEHOLD: [p for p in records(self.config_entry, CONF_HOUSEHOLD)
                                                if p[RECORD_ID] != self._person[RECORD_ID]]})
        # Geleerte optionale Felder fehlen in user_input: dann „typisch fürs Alter“, nicht der alte Wert
        for k in (CONF_BIRTH_YEAR, CONF_SHOWERS_PER_WEEK, CONF_BATHS_PER_WEEK):
            self._person.pop(k, None)
        self._person.update(user_input)
        if PRESENCE_FIELDS[self._person[CONF_PRESENCE]]:
            return self.async_show_form(step_id="person_presence", data_schema=presence_schema(self._person))
        return self._save_person()

    async def async_step_person_presence(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._person.update(user_input or {})
        return self._save_person()

    def _save_person(self) -> ConfigFlowResult:
        person = with_id({RECORD_ID: self._person.get(RECORD_ID)} | clean_person(self._person))
        persons = records(self.config_entry, CONF_HOUSEHOLD)
        if any(p[RECORD_ID] == person[RECORD_ID] for p in persons):
            persons = [person if p[RECORD_ID] == person[RECORD_ID] else p for p in persons]
        else:
            persons.append(person)
        return self._save({CONF_HOUSEHOLD: persons})

    async def async_step_plant(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
                if consumption_error(flat):
                    errors["base"] = "invalid_consumption_unit"
                else:
                    return self._save(flat)
            current |= flat
        current |= fee_periods(current) | price_units(current)
        selectors = _option_selectors()
        cost_missing = bool(heat_pump_fixed_costs(current)[1])
        schema = {}
        for name, keys in OPTION_SECTIONS.items():
            fields = {}
            for key in keys:
                if key in OPTIONAL_OPTIONS:
                    value = current.get(key)
                    fields[vol.Optional(key, description={"suggested_value": value} if value is not None else None)] = selectors[key]
                else:
                    fields[vol.Required(key, default=current[key])] = selectors[key]
            # Fehlen feste Kosten, ist nur „Kosten“ aufgeklappt: Der Link aus der Karte führt direkt dorthin.
            collapsed = name != "cost" if cost_missing else name == "evaluation"
            schema[vol.Required(name)] = section(vol.Schema(fields), {"collapsed": collapsed})
        return self.async_show_form(step_id="plant", data_schema=vol.Schema(schema), errors=errors)


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


# Person im Haushalt: Alter, Anwesenheit und Duschgewohnheiten (Warmwasserbedarf, Spezifikation 6.6). Zwei Schritte:
# zuerst Person und Muster, dann – nur wenn nötig – die Angaben zum Muster (z. B. Wechselwochen bei Kindern, die
# abwechselnd in zwei Haushalten wohnen). Leere Gewohnheiten ersetzt das Audit durch typische Werte.
def person_schema(data: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_PERSON_NAME, default=data.get(CONF_PERSON_NAME, "")): selector.TextSelector(),
        _optional(CONF_BIRTH_YEAR, data): selector.NumberSelector(selector.NumberSelectorConfig(
            min=1900, max=2100, step=1, mode=selector.NumberSelectorMode.BOX)),
        vol.Required(CONF_PRESENCE, default=data.get(CONF_PRESENCE, "always")): _select(CONF_PRESENCE, PRESENCE_MODES),
        _optional(CONF_SHOWERS_PER_WEEK, data): _number(28, 0.5, ""),
        _optional(CONF_BATHS_PER_WEEK, data): _number(14, 0.5, ""),
        vol.Required(CONF_SHOWER_TIME, default=data.get(CONF_SHOWER_TIME, "varied")): _select(CONF_SHOWER_TIME,
                                                                                            SHOWER_TIMES),
    })


def presence_schema(data: dict[str, Any]) -> vol.Schema:
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


def clean_person(data: dict[str, Any]) -> dict[str, Any]:
    """Nur die Felder des gewählten Musters behalten; Zahlen als int, wo sie ganzzahlig sind."""
    keep = {CONF_PERSON_NAME, CONF_BIRTH_YEAR, CONF_PRESENCE, CONF_SHOWERS_PER_WEEK, CONF_BATHS_PER_WEEK,
            CONF_SHOWER_TIME, *PRESENCE_FIELDS[data.get(CONF_PRESENCE, "always")]}
    out = {k: v for k, v in data.items() if k in keep and v not in (None, "")}
    for k in (CONF_BIRTH_YEAR, CONF_WEEKS_PRESENT, CONF_WEEKS_ABSENT, CONF_EVERY_N_WEEKS):
        if k in out:
            out[k] = int(out[k])
    return out
