"""Konstanten: Rollen, Stammdaten, Prüfungen."""

from __future__ import annotations

from datetime import timedelta

from .audit_core.actions import CONTROL_ROLES
from .audit_core.audits import BY_ID, REGISTRY
from .audit_core.runner import CAPACITY, DATA_BASIS, EFFICIENCY, FLOW_TEMPERATURE

DOMAIN = "air_water_heatpump_audit"
UPDATE_INTERVAL = timedelta(hours=1)

# Rollen je Config-Flow-Schritt (Spezifikation 1.3). Vorschläge für Entitäten kommen aus den Profilen (profiles.py).
ROLE_STEPS: dict[str, tuple[str, ...]] = {
    "signals": ("compressor_running", "compressor_frequency", "pump_running", "defrost", "dhw_active", "immersion_heater",
             "booster_heater", "booster_heater_2", "heartbeat"),
    "measurements": ("electricity_meter", "flow_temp", "return_temp", "flow_rate", "outdoor_temp",
                     "outdoor_temp_reference"),
    "controller": ("controller_heating_consumed", "controller_dhw_consumed", "controller_date", "controller_heat_today"),
    # Heizkreis hinter Puffer oder Weiche und Raum (Audit 2); bei Anlagen ohne Trennung leer lassen
    "circuit": ("flow_setpoint", "circuit_flow_temp", "circuit_return_temp", "circuit_pump_running", "room_temp"),
    # Warmwasserspeicher (Audit Warmwasser)
    "dhw": ("dhw_tank_temp", "dhw_setpoint"),
    # Tarif (Audit Kosten): nur bei dynamischem Strompreis bzw. Sperrsignal des Netzbetreibers
    "tariff": ("price_signal", "grid_lock"),
    # Stellgrößen (Spezifikation 1.8): Was die Schnittstelle zur Wärmepumpe schreiben kann. Nur zugeordnete Rollen
    # erscheinen als Vorschlag in der Spalte „Aktion“.
    "controls": tuple(CONTROL_ROLES),
}
ROLE_DOMAINS: dict[str, list[str]] = {
    role: ["binary_sensor"] for role in ROLE_STEPS["signals"] if role not in ("compressor_frequency", "heartbeat")
} | {"outdoor_temp_reference": ["sensor", "weather"], "circuit_pump_running": ["binary_sensor"],
     "price_signal": ["sensor", "input_number"], "grid_lock": ["binary_sensor", "input_boolean", "switch"]} | {
    role: list(spec.domains) for role, spec in CONTROL_ROLES.items()
}
# Umbenannte Rollen der Vorgänger-Integration (WP-Audit Version 1): herstellerneutral statt FTC (Mitsubishi).
ROLE_RENAMES = {"ftc_heating_consumed": "controller_heating_consumed", "ftc_dhw_consumed": "controller_dhw_consumed",
                "ftc_controller_date": "controller_date"}


def migrate_roles(data: dict) -> dict:
    """Rollen-Zuordnung eines älteren Eintrags auf die heutigen Rollen-Keys bringen."""
    return {ROLE_RENAMES.get(k, k): v for k, v in data.items()}


# Preis-Sensoren anderer Heizsysteme (audit_core.heating_prices): Attribute des Vertrags
PRICE_ATTR_SYSTEM = "heating_system"
PRICE_ATTR_SOURCE = "source"
PRICE_ATTR_SOURCE_KIND = "source_kind"
PRICE_ATTR_AS_OF = "as_of"
PRICE_ATTR_INCLUDES_FIXED = "includes_fixed_charges"  # Preis enthält Grundpreis/Messung schon (z. B. Eurostat)
PRICE_ATTR_BASE_FEE = "annual_base_fee"  # feste Kosten des Vergleichs in €/a, über die Jahreswärme verteilt
PRICE_ROLE_PREFIX = "price_reference:"  # Schlüssel der Zeitreihen beim Laden, damit sie keine Rolle verdecken

# Rollen mit Text-Zustand; alle anderen werden als Zahl gelesen (on/off → 1/0).
TEXT_ROLES = {"controller_date"}
# Bei einer weather-Entität wird dieses Attribut statt des Zustands gelesen.
WEATHER_ATTRIBUTE = "temperature"

# Stammdaten (Spezifikation 1.4) im Options Flow
CONF_IMMERSION_HEATER_KW = "immersion_heater_kw"
CONF_BOOSTER_HEATER_KW = "booster_heater_kw"
CONF_BOOSTER_HEATER_2_KW = "booster_heater_2_kw"
CONF_WINDOW_DAYS = "window_days"
CONF_DATA_SINCE = "data_since"
CONF_DATA_SOURCE = "data_source"
CONF_HYDRAULIC_SEPARATION = "hydraulic_separation"
CONF_FLOW_RATE_MIN_LPM = "flow_rate_min_lpm"
CONF_CIRCUIT_FLOW_MAX_LPM = "circuit_flow_max_lpm"
CONF_ROOM_TEMP_TARGET = "room_temp_target"
CONF_CAPACITY_MIN_TABLE = "capacity_min_table"
CONF_HEATING_HOURS = "heating_hours"
CONF_DHW_TANK_VOLUME_L = "dhw_tank_volume_l"
CONF_HEATING_DEGREE_DAYS = "heating_degree_days"
CONF_TARIFF_PRICE = "tariff_price"
CONF_HEAT_PUMP_METER = "heat_pump_meter"
CONF_TARIFF_BASE_FEE = "tariff_base_fee"
CONF_METER_FEE = "meter_fee"
# Zeitraum, auf den sich der eingetragene Betrag bezieht: wie er im Vertrag bzw. auf der Rechnung steht
CONF_TARIFF_BASE_FEE_PERIOD = "tariff_base_fee_period"
CONF_METER_FEE_PERIOD = "meter_fee_period"
FEE_PERIODS = ["month", "year"]
# Vorauswahl für neue Einträge: Grundpreise stehen meist pro Monat im Vertrag, Messstellenentgelte pro Jahr
FEE_PERIOD_DEFAULTS = {CONF_TARIFF_BASE_FEE_PERIOD: "month", CONF_METER_FEE_PERIOD: "year"}
FEE_PERIOD_OF = {CONF_TARIFF_BASE_FEE: CONF_TARIFF_BASE_FEE_PERIOD, CONF_METER_FEE: CONF_METER_FEE_PERIOD}
CONF_HOUSEHOLD_PRICE = "household_price"
CONF_REFERENCE_FUEL_PRICE = "reference_fuel_price"
# Einheit der Arbeitspreise, wie im Vertrag: ct/kWh oder €/kWh; leer = €/kWh (Einträge vor 0.18.0b6)
CONF_TARIFF_PRICE_UNIT = "tariff_price_unit"
CONF_HOUSEHOLD_PRICE_UNIT = "household_price_unit"
CONF_REFERENCE_FUEL_PRICE_UNIT = "reference_fuel_price_unit"
PRICE_UNITS = ["ct_per_kwh", "eur_per_kwh"]
PRICE_UNIT_DEFAULT = "ct_per_kwh"  # Vorauswahl für neue Einträge: Verträge nennen Arbeitspreise meist in ct/kWh
PRICE_UNIT_OF = {CONF_TARIFF_PRICE: CONF_TARIFF_PRICE_UNIT, CONF_HOUSEHOLD_PRICE: CONF_HOUSEHOLD_PRICE_UNIT,
                 CONF_REFERENCE_FUEL_PRICE: CONF_REFERENCE_FUEL_PRICE_UNIT}
CONF_REFERENCE_EFFICIENCY = "reference_efficiency"
CONF_PREVIOUS_HEATING_SYSTEM = "previous_heating_system"
CONF_PREVIOUS_CONSUMPTION = "previous_consumption"
CONF_PREVIOUS_CONSUMPTION_UNIT = "previous_consumption_unit"
CONF_COMPARE_HEATING_SYSTEMS = "compare_heating_systems"
CONF_REDUCED_GRID_FEE = "reduced_grid_fee"  # § 14a EnWG Modul 2, nur mit eigenem Zähler
CONF_COLD_WATER_C = "cold_water_c"
CONF_LIVING_AREA_M2 = "living_area_m2"
CONF_DHW_DISINFECTION_INTERVAL_DAYS = "dhw_disinfection_interval_days"
# Abschnitte des Options-Formulars; gespeichert werden die Optionen flach.
OPTION_SECTIONS: dict[str, tuple[str, ...]] = {
    "plant": (CONF_HYDRAULIC_SEPARATION, CONF_FLOW_RATE_MIN_LPM, CONF_CIRCUIT_FLOW_MAX_LPM, CONF_CAPACITY_MIN_TABLE, CONF_IMMERSION_HEATER_KW,
              CONF_BOOSTER_HEATER_KW, CONF_BOOSTER_HEATER_2_KW),
    "dhw": (CONF_DHW_TANK_VOLUME_L, CONF_COLD_WATER_C, CONF_DHW_DISINFECTION_INTERVAL_DAYS),
    "site": (CONF_HEATING_HOURS, CONF_HEATING_DEGREE_DAYS, CONF_ROOM_TEMP_TARGET, CONF_LIVING_AREA_M2),
    "cost": (CONF_TARIFF_PRICE, CONF_TARIFF_PRICE_UNIT, CONF_HEAT_PUMP_METER, CONF_TARIFF_BASE_FEE, CONF_TARIFF_BASE_FEE_PERIOD, CONF_METER_FEE,
             CONF_METER_FEE_PERIOD, CONF_REDUCED_GRID_FEE, CONF_HOUSEHOLD_PRICE, CONF_HOUSEHOLD_PRICE_UNIT,
             CONF_PREVIOUS_HEATING_SYSTEM, CONF_PREVIOUS_CONSUMPTION, CONF_PREVIOUS_CONSUMPTION_UNIT,
             CONF_REFERENCE_FUEL_PRICE, CONF_REFERENCE_FUEL_PRICE_UNIT, CONF_REFERENCE_EFFICIENCY,
             CONF_COMPARE_HEATING_SYSTEMS),
    "evaluation": (CONF_WINDOW_DAYS, CONF_DATA_SINCE, CONF_DATA_SOURCE),
}
# Optionale Stammdaten: leer heißt „unbekannt“, die abhängige Prüfung ist dann nicht bewertbar.
OPTIONAL_OPTIONS = (CONF_FLOW_RATE_MIN_LPM, CONF_CIRCUIT_FLOW_MAX_LPM, CONF_CAPACITY_MIN_TABLE, CONF_HEATING_HOURS,
                    CONF_IMMERSION_HEATER_KW, CONF_BOOSTER_HEATER_KW, CONF_BOOSTER_HEATER_2_KW, CONF_DATA_SINCE,
                    CONF_DHW_TANK_VOLUME_L, CONF_HEATING_DEGREE_DAYS, CONF_TARIFF_PRICE, CONF_TARIFF_BASE_FEE,
                    CONF_HOUSEHOLD_PRICE, CONF_REFERENCE_FUEL_PRICE, CONF_REFERENCE_EFFICIENCY, CONF_LIVING_AREA_M2,
                    CONF_HEAT_PUMP_METER, CONF_METER_FEE, CONF_PREVIOUS_HEATING_SYSTEM, CONF_PREVIOUS_CONSUMPTION,
                    CONF_PREVIOUS_CONSUMPTION_UNIT)
HEAT_PUMP_METERS = ["separate_meter", "household_meter"]
PREVIOUS_HEATING_SYSTEMS = ["natural_gas", "heating_oil", "wood_pellets", "district_heating", "direct_electric", "none"]
CONSUMPTION_UNITS = ["kWh", "MWh", "L", "kg", "t"]
# Stammdaten, die feste Kosten der Wärmepumpe bestimmen (Repairs-Issue „feste Kosten fehlen“)
FIXED_COST_KEYS = (CONF_HEAT_PUMP_METER, CONF_TARIFF_BASE_FEE, CONF_METER_FEE)
FIXED_COST_PERIOD_KEYS = (CONF_TARIFF_BASE_FEE_PERIOD, CONF_METER_FEE_PERIOD)
HYDRAULIC_SEPARATIONS = ["unknown", "none", "series_buffer", "parallel_buffer", "hydraulic_separator"]
# auto: InfluxDB 2, wenn die HA-Integration InfluxDB eingerichtet ist, sonst Recorder
DATA_SOURCES = ["auto", "influxdb", "recorder"]
SOURCE_INFLUXDB = "influxdb"
SOURCE_RECORDER = "recorder"
DEFAULT_OPTIONS = {
    CONF_IMMERSION_HEATER_KW: None,  # Datenblatt; ohne Wert ist C5 nicht bewertbar, sobald der Heizstab läuft
    CONF_BOOSTER_HEATER_KW: None,
    CONF_BOOSTER_HEATER_2_KW: None,
    CONF_WINDOW_DAYS: 30,  # mit Recorder wirkt höchstens dessen Aufbewahrung (Standard 10 Tage)
    CONF_DATA_SINCE: None,  # z. B. Einbau der Schnittstelle; ohne Wert gilt das ganze Fenster
    CONF_DATA_SOURCE: "auto",
    CONF_HYDRAULIC_SEPARATION: "unknown",
    CONF_FLOW_RATE_MIN_LPM: None,  # Herstellerangabe, ohne Wert wird der Durchfluss nicht gegen ein Minimum geprüft
    CONF_CIRCUIT_FLOW_MAX_LPM: None,  # größter Förderstrom der Heizkreispumpe; ohne Wert wird T3 nicht gekappt
    CONF_ROOM_TEMP_TARGET: 20.0,  # Norm-Innentemperatur Wohnräume (DIN EN 12831)
    CONF_CAPACITY_MIN_TABLE: None,  # Datenblatt, Vorschlag aus dem Modell-Profil (profiles.py)
    CONF_HEATING_HOURS: None,  # Klimakarte des Bundesverbands Wärmepumpe für den Standort
    CONF_DHW_TANK_VOLUME_L: None,  # Typenschild des Speichers; ohne Wert ist W4 nicht bewertbar
    CONF_HEATING_DEGREE_DAYS: None,  # langjähriges Mittel G20/15 am Standort; ohne Wert keine Jahreshochrechnung
    CONF_TARIFF_PRICE: None,  # Arbeitspreis in tariff_price_unit; Vorschlag aus dem Energie-Dashboard (config_flow.energy_price)
    # Zähler der Wärmepumpe: eigener Zähler mit WP-Tarif oder Haushaltszähler; leer = nicht angegeben (Hinweis)
    CONF_HEAT_PUMP_METER: None,
    CONF_TARIFF_BASE_FEE: None,  # Grundpreis des Wärmepumpentarifs in €; leer = nicht eingetragen, 0 = keiner
    CONF_METER_FEE: None,  # Messstellenentgelt des Wärmepumpenzählers in €; leer = nicht eingetragen, 0 = keins
    # Zeitraum der beiden Beträge (month/year). Leer = pro Jahr: so wurden Einträge vor 0.18.0b5 gespeichert.
    # Die Formulare wählen für neue Einträge FEE_PERIOD_DEFAULTS vor.
    CONF_TARIFF_BASE_FEE_PERIOD: None,
    CONF_METER_FEE_PERIOD: None,
    # Tarif mit reduziertem Netzentgelt nach § 14a EnWG (Modul 2); die wenigsten haben einen eigenen Zähler → aus
    CONF_REDUCED_GRID_FEE: False,
    CONF_TARIFF_PRICE_UNIT: None,  # Einheit der Arbeitspreise; die Formulare wählen PRICE_UNIT_DEFAULT vor
    CONF_HOUSEHOLD_PRICE_UNIT: None,
    CONF_REFERENCE_FUEL_PRICE_UNIT: None,
    # Frühere Heizung: System und Jahresverbrauch laut Abrechnung → Jahreswärme, solange K2 nicht hochrechnen kann
    CONF_PREVIOUS_HEATING_SYSTEM: None,
    CONF_PREVIOUS_CONSUMPTION: None,
    CONF_PREVIOUS_CONSUMPTION_UNIT: None,
    CONF_HOUSEHOLD_PRICE: None,
    CONF_REFERENCE_FUEL_PRICE: None,  # früherer Brennstoff je kWh inklusive Grundpreis-Anteil
    # Jahresnutzungsgrad der früheren Heizung, bezogen auf die abgerechnete Einheit: Feldmittel Gas-Brennwertkessel
    # 0,86 (DBU-Feldtest, 60 Anlagen). Gilt für den Vergleichsbrennstoff (K1, K2), für die Umrechnung des früheren
    # Verbrauchs und für die Vergleichslinie des früheren Heizsystems; alle anderen Systeme nutzen feste Werte.
    CONF_REFERENCE_EFFICIENCY: 0.86,
    # Kosten-Zeitstrahl: Wärmepreise anderer Heizsysteme aus Preis-Sensoren (Attribut `heating_system`)
    CONF_COMPARE_HEATING_SYSTEMS: True,
    CONF_LIVING_AREA_M2: None,  # K2: Verbrauch je m² und Klasse des Energieausweises
    CONF_COLD_WATER_C: 10.0,  # Kaltwasser im Jahresmittel (W6)
    CONF_DHW_DISINFECTION_INTERVAL_DAYS: 7,  # W2: Abstand der Aufheizungen auf 60 °C, wenn der Speicher kühler ist
}
MASTER_KEYS = (CONF_HYDRAULIC_SEPARATION, CONF_FLOW_RATE_MIN_LPM, CONF_CIRCUIT_FLOW_MAX_LPM, CONF_ROOM_TEMP_TARGET, CONF_CAPACITY_MIN_TABLE,
               CONF_HEATING_HOURS, CONF_DHW_TANK_VOLUME_L, CONF_HEATING_DEGREE_DAYS, CONF_TARIFF_PRICE,
               CONF_TARIFF_BASE_FEE, CONF_HOUSEHOLD_PRICE, CONF_REFERENCE_FUEL_PRICE, CONF_REFERENCE_EFFICIENCY,
               CONF_COLD_WATER_C, CONF_DHW_DISINFECTION_INTERVAL_DAYS, CONF_LIVING_AREA_M2, CONF_HEAT_PUMP_METER,
               CONF_METER_FEE, CONF_PREVIOUS_HEATING_SYSTEM, CONF_PREVIOUS_CONSUMPTION, CONF_PREVIOUS_CONSUMPTION_UNIT,
               CONF_TARIFF_BASE_FEE_PERIOD, CONF_METER_FEE_PERIOD, CONF_TARIFF_PRICE_UNIT, CONF_HOUSEHOLD_PRICE_UNIT,
               CONF_REFERENCE_FUEL_PRICE_UNIT, CONF_REDUCED_GRID_FEE)

# Ereignisse (Spezifikation 1.5) und Personen im Haushalt stehen als Listen in den Optionen (`events`, `household`),
# je Eintrag mit eigener `id`. Bis 0.18.0b6 waren es Untereinträge; die Migration (records.py) zieht sie um.
CONF_EVENTS = "events"
CONF_HOUSEHOLD = "household"
RECORD_ID = "id"
RECORD_KEYS = (CONF_EVENTS, CONF_HOUSEHOLD)
SUBENTRY_EVENT = "event"
CONF_EVENT_TIME = "time"
CONF_EVENT_KIND = "kind"
CONF_EVENT_NOTE = "note"
EVENT_KINDS = ["heating_curve", "valves", "hydraulic_balancing", "pump_setting", "dhw_setting", "hardware", "other"]
# Titel der Untereinträge entstehen im Flow und werden nicht übersetzt; daher hier je Sprache.
EVENT_KIND_LABELS = {
    "de": {"heating_curve": "Heizkurve geändert", "valves": "Heizkörperventile verstellt",
           "hydraulic_balancing": "Hydraulischer Abgleich", "pump_setting": "Pumpe verstellt",
           "dhw_setting": "Warmwasser-Einstellung", "hardware": "Umbau an der Anlage", "other": "Sonstiges"},
    "en": {"heating_curve": "Heating curve changed", "valves": "Radiator valves adjusted",
           "hydraulic_balancing": "Hydraulic balancing", "pump_setting": "Pump setting changed",
           "dhw_setting": "Hot water setting", "hardware": "Hardware change", "other": "Other"},
}

# Personen im Haushalt (Warmwasserbedarf, Audit Warmwasser); Felder wie audit_core.household
SUBENTRY_PERSON = "person"
CONF_PERSON_NAME = "name"
CONF_BIRTH_YEAR = "birth_year"
CONF_PRESENCE = "presence"
CONF_WEEKS_PRESENT = "weeks_present"
CONF_WEEKS_ABSENT = "weeks_absent"
CONF_ROTATION_START = "rotation_start"
CONF_WEEKDAYS = "weekdays"
CONF_EVERY_N_WEEKS = "every_n_weeks"
CONF_SHARE_PCT = "share_pct"
CONF_SHOWERS_PER_WEEK = "showers_per_week"
CONF_BATHS_PER_WEEK = "baths_per_week"
CONF_SHOWER_TIME = "shower_time"
# Felder des zweiten Schritts je Anwesenheitsmuster
PRESENCE_FIELDS = {"always": (), "rotation": (CONF_WEEKS_PRESENT, CONF_WEEKS_ABSENT, CONF_ROTATION_START),
                   "weekdays": (CONF_WEEKDAYS, CONF_EVERY_N_WEEKS, CONF_ROTATION_START), "share": (CONF_SHARE_PCT,)}

VERDICTS = ["ok", "hint", "warn", "info", "not_assessable"]

# Prüfungen je Audit: (Audit, check_id, key) aus der Registry. Daraus entstehen die Sensoren, auch bevor Daten da sind.
CHECKS: list[tuple[str, str, str]] = [(a.audit_id, c.check_id, c.key) for a in REGISTRY for c in a.checks]
AUDITS = [a.audit_id for a in REGISTRY]

# Audits als Untereinträge („Audit hinzufügen“): je Audit höchstens einer
SUBENTRY_AUDIT = "audit"
CONF_AUDIT = "audit"
CONF_AUDITS = "audits"

# Übernahme aus der Vorgänger-Integration „WP-Audit“ (Domain heatpump_audit)
LEGACY_DOMAIN = "heatpump_audit"
CONF_IMPORT_TIMELINE_FROM = "import_timeline_from"


def language(hass) -> str:
    return "de" if (hass.config.language or "en").startswith("de") else "en"


def audit_title(audit_id: str, lang: str) -> str:
    return f"Audit: {BY_ID[audit_id].names[lang]}"


CARD_URL = "/air_water_heatpump_audit/air-water-heatpump-audit-card.js"
