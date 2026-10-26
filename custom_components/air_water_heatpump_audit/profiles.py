"""Profile: Vorbelegungen für bekannte Schnittstellen und Wärmepumpen-Modelle.

Der Kern (`audit_core`) kennt keine Hersteller. Profile liegen deshalb hier, im HA-Teil, und landen nur als Vorschlag
in der Einrichtung: Ein Schnittstellen-Profil schlägt Entitäten für die Rollen vor, ein Modell-Profil Stammdaten aus
dem Datenblatt. Beides lässt sich danach ändern oder leeren. Keine Abhängigkeit von Home Assistant, damit auch der
Prototyp die Profile laden kann.
"""

from __future__ import annotations

# Schnittstellen: Rolle → vorgeschlagene Entität. Nur Rollen, die die Schnittstelle liefert.
INTERFACE_PROFILES: dict[str, dict[str, str]] = {
    # Mitsubishi Ecodan mit ESPHome-Firmware esphome-ecodan-hp (z. B. Mahtanar-Modul), Entitäten-Präfix „heatpump_“
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
        "flow_setpoint": "sensor.heatpump_zone_1_setpoint_value",
        "circuit_flow_temp": "sensor.heatpump_z1_feed_temp",
        "circuit_return_temp": "sensor.heatpump_z1_return_temp",
        "short_cycle_lockout": "select.heatpump_short_cycle_lockout_duration_min",
        "short_cycle_min_run": "number.heatpump_short_cycle_minimum_on_time",
    },
}

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
