"""Profile: Vorbelegungen für bekannte Schnittstellen und Wärmepumpen-Modelle.

Der Kern (`audit_core`) kennt keine Hersteller. Profile liegen deshalb hier, im HA-Teil, und landen nur als Vorschlag
in der Einrichtung: Ein Schnittstellen-Profil schlägt Entitäten für die Rollen vor, ein Modell-Profil Stammdaten aus
dem Datenblatt. Beides lässt sich danach ändern oder leeren. Keine Abhängigkeit von Home Assistant, damit auch der
Prototyp die Profile laden kann.
"""

from __future__ import annotations

# Schnittstellen: Rolle → vorgeschlagene Entität. Nur Rollen, die die Schnittstelle liefert.
INTERFACE_PROFILES: dict[str, dict[str, str]] = {
    # Mitsubishi Ecodan mit ESPHome-Firmware esphome-ecodan-hp (z. B. Mahtanar-Modul), Gerätename „heatpump“
    # (englische Labels); weitere Schreibweisen in INTERFACE_VARIANTS
    "esphome_ecodan": {
        "compressor_running": "binary_sensor.heatpump_compressor",
        "compressor_frequency": "sensor.heatpump_compressor_frequency",
        "pump_running": "binary_sensor.heatpump_water_pump_status",
        "defrost": "binary_sensor.heatpump_defrost",
        "dhw_active": "binary_sensor.heatpump_3_way_valve",
        "immersion_heater": "binary_sensor.heatpump_immersion_heater",
        "booster_heater": "binary_sensor.heatpump_booster_heater",
        "booster_heater_2": "binary_sensor.heatpump_booster_heater_2",
        "heartbeat": "sensor.heatpump_esp_uptime",
        "flow_temp": "sensor.heatpump_feed_temp",
        "return_temp": "sensor.heatpump_return_temp",
        "flow_rate": "sensor.heatpump_flow_rate",
        "outdoor_temp": "sensor.heatpump_outside_temp",
        "controller_heating_consumed": "sensor.heatpump_heating_consumed",
        "controller_dhw_consumed": "sensor.heatpump_dhw_consumed",
        "controller_date": "sensor.heatpump_controller_date",
        "controller_heat_today": "sensor.heatpump_estimated_total_daily_energy_produced",
        "flow_setpoint": "sensor.heatpump_zone_1_setpoint_value",
        "circuit_flow_temp": "sensor.heatpump_z1_feed_temp",
        "circuit_return_temp": "sensor.heatpump_z1_return_temp",
        "short_cycle_lockout": "select.heatpump_short_cycle_lockout_duration_min",
        "short_cycle_min_run": "number.heatpump_short_cycle_minimum_on_time",
    },
}

# Andere Schreibweisen derselben Entitäten. Die Firmware benennt sie nach Gerätename und Sprache der Labels: mit dem
# Standard-Gerätenamen „Ecodan heatpump“ entsteht `sensor.ecodan_heatpump_feed_temp` (englische Labels) bzw.
# `sensor.ecodan_heatpump_vorlauftemperatur` (deutsche Labels, confs/ecodan-labels-de.yaml). Abgeleitet aus den
# Label-Dateien von esphome-ecodan-hp; andere Sprachen ordnet man im Config Flow von Hand zu.
_ECODAN_DE = {
    "compressor_running": "binary_sensor.ecodan_heatpump_kompressor",
    "compressor_frequency": "sensor.ecodan_heatpump_kompressor_frequenz",
    "pump_running": "binary_sensor.ecodan_heatpump_wasserpumpen_status",
    "defrost": "binary_sensor.ecodan_heatpump_abtauen",
    "dhw_active": "binary_sensor.ecodan_heatpump_3_wege_ventil",
    "immersion_heater": "binary_sensor.ecodan_heatpump_elektroheizung",
    "booster_heater": "binary_sensor.ecodan_heatpump_zusatzheizung",
    "booster_heater_2": "binary_sensor.ecodan_heatpump_zusatzheizung_2",
    "heartbeat": "sensor.ecodan_heatpump_esp_betriebszeit",
    "flow_temp": "sensor.ecodan_heatpump_vorlauftemperatur",
    "return_temp": "sensor.ecodan_heatpump_rucklauftemperatur",
    "flow_rate": "sensor.ecodan_heatpump_durchflussrate",
    "outdoor_temp": "sensor.ecodan_heatpump_aussentemperatur",
    "controller_heating_consumed": "sensor.ecodan_heatpump_heizung_verbraucht",
    "controller_dhw_consumed": "sensor.ecodan_heatpump_tww_verbraucht",
    "controller_date": "sensor.ecodan_heatpump_controller_datum",
    "controller_heat_today": "sensor.ecodan_heatpump_geschatzte_tagliche_energieproduktion",
    "flow_setpoint": "sensor.ecodan_heatpump_zone_1_sollwert",
    "circuit_flow_temp": "sensor.ecodan_heatpump_z1_vorlauftemperatur",
    "circuit_return_temp": "sensor.ecodan_heatpump_z1_rucklauftemperatur",
    "short_cycle_lockout": "select.ecodan_heatpump_kurzzyklus_sperrdauer_min",
    "short_cycle_min_run": "number.ecodan_heatpump_kurzzyklus_minimale_laufzeit",
}
INTERFACE_VARIANTS: dict[str, list[dict[str, str]]] = {
    "esphome_ecodan": [
        {role: eid.replace(".heatpump_", ".ecodan_heatpump_", 1)
         for role, eid in INTERFACE_PROFILES["esphome_ecodan"].items()},
        _ECODAN_DE,
    ],
}


def role_candidates(profile: str | None) -> dict[str, list[str]]:
    """Je Rolle alle bekannten Schreibweisen des Profils, die Grundform zuerst."""
    out: dict[str, list[str]] = {}
    for mapping in [INTERFACE_PROFILES.get(profile or "", {}), *INTERFACE_VARIANTS.get(profile or "", [])]:
        for role, eid in mapping.items():
            out.setdefault(role, []).append(eid)
    return out


# Rollen, die zu keiner Wärmepumpe gehören, aber in fast jeder HA-Instanz gleich heißen
COMMON_ROLE_SUGGESTIONS: dict[str, str] = {"outdoor_temp_reference": "weather.home"}

# Modelle: Stammdaten aus Datenblatt und Installationshandbuch.
MODEL_PROFILES: dict[str, dict] = {
    # Mitsubishi PUD-SHWM140YAA: Mindest-Heizleistung in kW je Vorlauf (35/45/55 °C) und Außentemperatur
    # (Data Book MEDB S. A-54); Heizstab im Speichermodul EHPT20X 3 kW Werkseinstellung (OCH714E Tab. 9.5.2).
    "mitsubishi_pud_shwm140": {
        "capacity_min_table": {
            35: {-15: 5.8, -10: 3.8, -7: 3.9, 2: 3.5, 7: 3.5, 12: 3.9, 15: 4.3, 20: 4.8},
            45: {-15: 5.6, -10: 3.6, -7: 3.7, 2: 3.2, 7: 3.2, 12: 3.5, 15: 4.1, 20: 4.4},
            55: {-15: 5.4, -10: 3.3, -7: 3.2, 2: 2.7, 7: 2.7, 12: 3.0, 15: 3.6, 20: 4.0},
        },
        "immersion_heater_kw": 3.0,
    },
}
