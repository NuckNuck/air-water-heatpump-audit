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
CONF_TARIFF_BASE_FEE = "tariff_base_fee"
CONF_HOUSEHOLD_PRICE = "household_price"
CONF_REFERENCE_FUEL_PRICE = "reference_fuel_price"
CONF_REFERENCE_EFFICIENCY = "reference_efficiency"
CONF_COLD_WATER_C = "cold_water_c"
CONF_DHW_DISINFECTION_INTERVAL_DAYS = "dhw_disinfection_interval_days"
# Abschnitte des Options-Formulars; gespeichert werden die Optionen flach.
OPTION_SECTIONS: dict[str, tuple[str, ...]] = {
    "plant": (CONF_HYDRAULIC_SEPARATION, CONF_FLOW_RATE_MIN_LPM, CONF_CIRCUIT_FLOW_MAX_LPM, CONF_CAPACITY_MIN_TABLE, CONF_IMMERSION_HEATER_KW,
              CONF_BOOSTER_HEATER_KW, CONF_BOOSTER_HEATER_2_KW),
    "dhw": (CONF_DHW_TANK_VOLUME_L, CONF_COLD_WATER_C, CONF_DHW_DISINFECTION_INTERVAL_DAYS),
    "site": (CONF_HEATING_HOURS, CONF_HEATING_DEGREE_DAYS, CONF_ROOM_TEMP_TARGET),
    "cost": (CONF_TARIFF_PRICE, CONF_TARIFF_BASE_FEE, CONF_HOUSEHOLD_PRICE, CONF_REFERENCE_FUEL_PRICE,
             CONF_REFERENCE_EFFICIENCY),
    "evaluation": (CONF_WINDOW_DAYS, CONF_DATA_SINCE, CONF_DATA_SOURCE),
}
# Optionale Stammdaten: leer heißt „unbekannt“, die abhängige Prüfung ist dann nicht bewertbar.
OPTIONAL_OPTIONS = (CONF_FLOW_RATE_MIN_LPM, CONF_CIRCUIT_FLOW_MAX_LPM, CONF_CAPACITY_MIN_TABLE, CONF_HEATING_HOURS,
                    CONF_IMMERSION_HEATER_KW, CONF_BOOSTER_HEATER_KW, CONF_BOOSTER_HEATER_2_KW, CONF_DATA_SINCE,
                    CONF_DHW_TANK_VOLUME_L, CONF_HEATING_DEGREE_DAYS, CONF_TARIFF_PRICE, CONF_TARIFF_BASE_FEE,
                    CONF_HOUSEHOLD_PRICE, CONF_REFERENCE_FUEL_PRICE, CONF_REFERENCE_EFFICIENCY)
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
    CONF_TARIFF_PRICE: None,  # Arbeitspreis €/kWh; Vorschlag aus dem Energie-Dashboard (config_flow.energy_price)
    CONF_TARIFF_BASE_FEE: None,  # zusätzlicher Grundpreis €/Jahr für den Wärmepumpenzähler
    CONF_HOUSEHOLD_PRICE: None,
    CONF_REFERENCE_FUEL_PRICE: None,  # früherer Brennstoff, €/kWh inklusive Grundpreis-Anteil
    # Jahresnutzungsgrad der früheren Heizung, bezogen auf den abgerechneten Brennwert: Feldmittel Gas-Brennwertkessel
    # 0,86 (DBU-Feldtest, 60 Anlagen); nur wirksam, wenn auch ein Brennstoffpreis eingetragen ist
    CONF_REFERENCE_EFFICIENCY: 0.86,
    CONF_COLD_WATER_C: 10.0,  # Kaltwasser im Jahresmittel (W6)
    CONF_DHW_DISINFECTION_INTERVAL_DAYS: 7,  # W2: Abstand der Aufheizungen auf 60 °C, wenn der Speicher kühler ist
}
MASTER_KEYS = (CONF_HYDRAULIC_SEPARATION, CONF_FLOW_RATE_MIN_LPM, CONF_CIRCUIT_FLOW_MAX_LPM, CONF_ROOM_TEMP_TARGET, CONF_CAPACITY_MIN_TABLE,
               CONF_HEATING_HOURS, CONF_DHW_TANK_VOLUME_L, CONF_HEATING_DEGREE_DAYS, CONF_TARIFF_PRICE,
               CONF_TARIFF_BASE_FEE, CONF_HOUSEHOLD_PRICE, CONF_REFERENCE_FUEL_PRICE, CONF_REFERENCE_EFFICIENCY,
               CONF_COLD_WATER_C, CONF_DHW_DISINFECTION_INTERVAL_DAYS)

# Ereignisse (Spezifikation 1.5) als Untereinträge des Config Entry
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

# Personen im Haushalt als Untereinträge (Warmwasserbedarf, Audit Warmwasser); Felder wie audit_core.household
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
