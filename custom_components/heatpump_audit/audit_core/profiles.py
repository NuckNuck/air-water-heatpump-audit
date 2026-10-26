"""Vorbelegungen für bekannte Geräte und Standorte. Die Prüfungen selbst kennen keine Hersteller (Spezifikation 1.6);
diese Werte landen nur als Vorschlag in den Stammdaten und lassen sich dort ändern oder leeren.
"""

from __future__ import annotations

# Mindest-Heizleistung Mitsubishi PUD-SHWM140YAA in kW je Vorlauf (35/45/55 °C) und Außentemperatur
# (Data Book MEDB S. A-54).
PUD_SHWM140_MIN_CAPACITY_KW = {
    35: {-15: 5.8, -10: 3.8, -7: 3.9, 2: 3.5, 7: 3.5, 12: 3.9, 15: 4.3, 20: 4.8},
    45: {-15: 5.6, -10: 3.6, -7: 3.7, 2: 3.2, 7: 3.2, 12: 3.5, 15: 4.1, 20: 4.4},
    55: {-15: 5.4, -10: 3.3, -7: 3.2, 2: 2.7, 7: 2.7, 12: 3.0, 15: 3.6, 20: 4.0},
}

# Heizstunden pro Jahr bei Heizgrenze 15 °C, BWP-Klimakarte, Beispielstandort im Mittelgebirge.
HEATING_HOURS_EXAMPLE_SITE = 6279
