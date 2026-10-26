"""Konstanten: Rollen, Stammdaten, Prüfungen."""

from __future__ import annotations

from datetime import timedelta

from .audit_core.actions import CONTROL_ROLES
from .audit_core.runner import CAPACITY, DATA_BASIS, EFFICIENCY, FLOW_TEMPERATURE

DOMAIN = "air_water_heatpump_audit"
UPDATE_INTERVAL = timedelta(hours=1)

# Rollen je Config-Flow-Schritt (Spezifikation 1.3). Vorschläge für Entitäten kommen aus den Profilen (profiles.py).
ROLE_STEPS: dict[str, tuple[str, ...]] = {
    "signals": ("compressor_running", "compressor_frequency", "pump_running", "defrost", "dhw_active", "immersion_heater",
             "booster_heater", "booster_heater_2", "heartbeat"),
    "measurements": ("electricity_meter", "flow_temp", "return_temp", "flow_rate", "outdoor_temp",
                     "outdoor_temp_reference"),
    "controller": ("controller_heating_consumed", "controller_dhw_consumed", "controller_date"),
    # Heizkreis hinter Puffer oder Weiche und Raum (Audit 2); bei Anlagen ohne Trennung leer lassen
    "circuit": ("flow_setpoint", "circuit_flow_temp", "circuit_return_temp", "circuit_pump_running", "room_temp"),
    # Stellgrößen (Spezifikation 1.8): Was die Schnittstelle zur Wärmepumpe schreiben kann. Nur zugeordnete Rollen
    # erscheinen als Vorschlag in der Spalte „Aktion“.
    "controls": tuple(CONTROL_ROLES),
}
ROLE_DOMAINS: dict[str, list[str]] = {
    role: ["binary_sensor"] for role in ROLE_STEPS["signals"] if role not in ("compressor_frequency", "heartbeat")
} | {"outdoor_temp_reference": ["sensor", "weather"], "circuit_pump_running": ["binary_sensor"]} | {
    role: list(spec.domains) for role, spec in CONTROL_ROLES.items()
}
# Umbenannte Rollen (Version 1 → 2): herstellerneutrale Namen statt FTC (Mitsubishi-Steuerung).
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
# Abschnitte des Options-Formulars; gespeichert werden die Optionen flach.
OPTION_SECTIONS: dict[str, tuple[str, ...]] = {
    "plant": (CONF_HYDRAULIC_SEPARATION, CONF_FLOW_RATE_MIN_LPM, CONF_CIRCUIT_FLOW_MAX_LPM, CONF_CAPACITY_MIN_TABLE, CONF_IMMERSION_HEATER_KW,
              CONF_BOOSTER_HEATER_KW, CONF_BOOSTER_HEATER_2_KW),
    "site": (CONF_HEATING_HOURS, CONF_ROOM_TEMP_TARGET),
    "evaluation": (CONF_WINDOW_DAYS, CONF_DATA_SINCE, CONF_DATA_SOURCE),
}
# Optionale Stammdaten: leer heißt „unbekannt“, die abhängige Prüfung ist dann nicht bewertbar.
OPTIONAL_OPTIONS = (CONF_FLOW_RATE_MIN_LPM, CONF_CIRCUIT_FLOW_MAX_LPM, CONF_CAPACITY_MIN_TABLE, CONF_HEATING_HOURS,
                    CONF_IMMERSION_HEATER_KW, CONF_BOOSTER_HEATER_KW, CONF_BOOSTER_HEATER_2_KW, CONF_DATA_SINCE)
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
}
MASTER_KEYS = (CONF_HYDRAULIC_SEPARATION, CONF_FLOW_RATE_MIN_LPM, CONF_CIRCUIT_FLOW_MAX_LPM, CONF_ROOM_TEMP_TARGET, CONF_CAPACITY_MIN_TABLE,
               CONF_HEATING_HOURS)

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

VERDICTS = ["ok", "hint", "warn", "info", "not_assessable"]

# Prüfungen je Audit: (Audit, check_id, key). Daraus entstehen die Sensoren, auch bevor Daten da sind.
CHECKS: list[tuple[str, str, str]] = [
    (DATA_BASIS, "D1", "history_depth"),
    (DATA_BASIS, "D2", "coverage"),
    (DATA_BASIS, "D3", "resolution"),
    (DATA_BASIS, "D4", "sensor_offset"),
    (DATA_BASIS, "D5", "meter_vs_controller"),
    (DATA_BASIS, "D6", "controller_day_boundary"),
    (DATA_BASIS, "D8", "meter_resolution"),
    (DATA_BASIS, "D9", "restart_artifacts"),
    (DATA_BASIS, "D10", "outdoor_sensor"),
    (EFFICIENCY, "E1", "daily_cop"),
    (EFFICIENCY, "E2", "weekly_cop"),
    (EFFICIENCY, "E3", "carnot_efficiency"),
    (EFFICIENCY, "E4", "dhw_share"),
    (FLOW_TEMPERATURE, "T1", "buffer_flow_loss"),
    (FLOW_TEMPERATURE, "T2", "circuit_sensor_offset"),
    (FLOW_TEMPERATURE, "T3", "flow_ratio"),
    (FLOW_TEMPERATURE, "T4", "heat_pump_spread"),
    (FLOW_TEMPERATURE, "T5", "flow_vs_setpoint"),
    (FLOW_TEMPERATURE, "T6", "heating_curve_headroom"),
    (CAPACITY, "C1", "starts_per_year"),
    (CAPACITY, "C2", "max_starts_per_hour"),
    (CAPACITY, "C3", "short_cycles"),
    (CAPACITY, "C4", "load_vs_min_capacity"),
    (CAPACITY, "C5", "backup_heater_share"),
    (CAPACITY, "C6", "defrost"),
    (CAPACITY, "C7", "modulation"),
]
AUDITS = [DATA_BASIS, EFFICIENCY, FLOW_TEMPERATURE, CAPACITY]

CARD_URL = "/air_water_heatpump_audit/air-water-heatpump-audit-card.js"
