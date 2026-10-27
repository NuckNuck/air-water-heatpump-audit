# Beispiel: Mitsubishi Ecodan mit Mahtanar (ESPHome)

So läuft das Audit auf der Anlage, an der es entwickelt wurde. Die Beschreibung zeigt eine mögliche Konfiguration,
keine Vorschrift: Andere Wärmepumpen und Schnittstellen funktionieren genauso, sie brauchen nur eine eigene Zuordnung
der Rollen ([Spezifikation 1.3](../specification.md#13-eingänge-rollen)).

## Die Anlage

| Teil | Bei uns | Rolle im Audit |
|---|---|---|
| Außengerät | Mitsubishi Ecodan Zubadan PUD-SHWM140YAA (14 kW, R32) | – |
| Innengerät | Speichermodul EHPT20X-MHEDW mit Regler FTC6 | – |
| Schnittstelle | [Mahtanar](https://github.com/tinwer-group/mahtanar) 1.4 (WLAN-Variante, ESP32-C3) am Stecker CN105 des FTC, Firmware [esphome-ecodan-hp](https://github.com/gekkekoe/esphome-ecodan-hp) | fast alle Rollen |
| Hydraulik | paralleler Pufferspeicher 300 l zwischen Wärmepumpe und Heizkreis, Heizkörper | Stammdatum `hydraulic_separation` = `parallel_buffer` |
| Stromzähler | eigener Zähler für die Wärmepumpe, ausgelesen mit einem IR-Lesekopf (Tasmota, SML) über MQTT | `electricity_meter` |
| Raumthermometer | Zigbee-Sensor Sonoff SNZB-02P über Zigbee2MQTT im Wohnzimmer | `room_temp` |
| Wetter | Integration Open-Meteo (`weather.home`) | `outdoor_temp_reference` |
| Langzeitdaten | InfluxDB 2 über die Home-Assistant-Integration „InfluxDB“ | Datenquelle `auto` |

Der Mahtanar ersetzt das WLAN-Modul von Mitsubishi (MELCloud) am CN105; beides gleichzeitig geht nicht.

## Firmware

Die Firmware entsteht mit ESPHome aus den Paketen von esphome-ecodan-hp und dem Board-Teil des Mahtanar. Gerätename
und Sprache der Labels bestimmen später die entity_ids (siehe [Zuordnung](#zuordnung-der-rollen)).

```yaml
substitutions:
  name: ecodan-heatpump
  friendlyName: Ecodan heatpump

api:
  encryption:
    key: !secret heatpump_encryption_key

ota:
  - platform: esphome
    encryption:
      key: !secret heatpump_encryption_key

external_components:
  - source: github://gekkekoe/esphome-ecodan-hp@main
    components: [ ecodan, optimizer ]
    refresh: always

packages:
  ecodan:
    url: https://github.com/gekkekoe/esphome-ecodan-hp/
    ref: main
    refresh: always
    files: [
            confs/base.yaml,
            confs/energy.yaml,
            confs/cpu-monitoring.yaml,
            confs/request-codes.yaml,
            confs/auto-adaptive.yaml,      # enthält auch die Kurzzyklus-Sperre (Stellgrößen)
            confs/zone1.yaml,
            confs/server-control-z1.yaml,
            confs/ecodan-labels-de.yaml,   # oder ecodan-labels-en.yaml
            confs/wifi.yaml,
           ]
  # Ersetzt die Pins und die Status-LED der Standard-Platine durch die des Mahtanar 1.4
  mahtanar:
    url: https://github.com/tinwer-group/mahtanar
    ref: 1.4-release
    refresh: always
    files: [ esphome-ecodan-hp-configs/esp32c3-mahtanar.yaml ]

wifi:
  power_save_mode: NONE          # im Blechgehäuse ist das Signal schwach
  ap:
    password: !secret heatpump_ap_password   # eigenes Passwort statt des bekannten Standards

ecodan:
  id: ecodan_instance
  uart_id: uart_ecodan
```

Die Dateinamen der Pakete ändern sich bei esphome-ecodan-hp gelegentlich – vor dem build in deren README nachsehen.

Praxishinweise:

- **Erst per USB flashen** (z. B. mit web.esphome.io), danach per OTA. Nicht jedes USB-Kabel überträgt Daten.
- **Steuerfunktionen aus lassen**, solange man nur messen will (Auto-Adaptiv, Kurzzyklus-Sperre, Server Control,
  Legionellen-Automatik). Wie sich die Schalter nach einem Neustart verhalten, legt `restore_mode` in den Paketen fest:
  Bei unserem build (Oktober 2026) stand er auf `DISABLED`, der ESP sendete beim Start nichts an die Wärmepumpe.
  Neuere Fassungen nutzen `RESTORE_DEFAULT_OFF` (letzter Zustand, sonst aus) – vor dem Flashen in
  `confs/auto-adaptive.yaml` nachsehen.
- **WLAN im Gehäuse:** Mit geschlossener Frontblende war das Signal bei uns fast weg (unter −85 dBm). Ein kleiner
  Access Point neben dem Innengerät hat das gelöst.

## Was die Werte taugen

Diese Eigenschaften sieht man im Audit 0 (Datenbasis) wieder:

- **Temperaturen kommen in 0,5-K-Schritten**, obwohl die Firmware zwei Nachkommastellen zeigt (der FTC liefert sie
  schon gerundet). Bei einer Spreizung von 3–4 K ist ein Einzelwert der Wärme damit auf gut ±10 % unsicher; das
  Audit mittelt deshalb über die Zeit (D3, D4).
- **Durchfluss** in ganzen l/min, **Außenfühler** in 0,5- bis 1-K-Schritten und beim Abtauen verfälscht (D10).
- **Strom laut FTC ist eine Schätzung**, solange am FTC keine externen Zähler angeschlossen sind (DIP-Schalter SW3);
  laut Foren liegt sie meist 5–14 % über einem echten Zähler. Für das Audit zählt deshalb nur der eigene Stromzähler
  (D5 vergleicht beides).
- **Tageswerte der FTC** (`heating_consumed`, `dhw_consumed`) meldet der FTC kurz vor Mitternacht nach seiner eigenen
  Uhr. Die Sommerzeit stellt man am Regler von Hand um; D6 zeigt, wenn die Uhr falsch geht.
- **`output_power`** kommt in ganzen kW und taugt nicht zur Auswertung; das Audit rechnet die Wärme selbst aus
  Durchfluss und Spreizung.
- Werte kommen etwa alle 11 s. Die ESP-Laufzeit dient als Heartbeat (D2, D9).

Ein Stromzähler ohne Freischaltung (PIN beim Messstellenbetreiber) liefert oft nur ganze kWh. Das reicht für
Wochenwerte; Tageswerte bleiben „vorläufig“ (D8, E1).

## Zuordnung der Rollen

Wählt man bei der Einrichtung das Schnittstellen-Profil **esphome_ecodan**, schlägt der Config Flow die Entitäten vor.
Er erkennt drei Schreibweisen und nimmt jeweils die, die es gibt:

| Rolle | englische Labels | deutsche Labels |
|---|---|---|
| `compressor_running` | `binary_sensor.ecodan_heatpump_compressor` | `binary_sensor.ecodan_heatpump_kompressor` |
| `compressor_frequency` | `sensor.ecodan_heatpump_compressor_frequency` | `sensor.ecodan_heatpump_kompressor_frequenz` |
| `pump_running` | `binary_sensor.ecodan_heatpump_water_pump_status` | `binary_sensor.ecodan_heatpump_wasserpumpen_status` |
| `defrost` | `binary_sensor.ecodan_heatpump_defrost` | `binary_sensor.ecodan_heatpump_abtauen` |
| `dhw_active` | `binary_sensor.ecodan_heatpump_3_way_valve` | `binary_sensor.ecodan_heatpump_3_wege_ventil` |
| `immersion_heater` | `binary_sensor.ecodan_heatpump_immersion_heater` | `binary_sensor.ecodan_heatpump_elektroheizung` |
| `booster_heater` | `binary_sensor.ecodan_heatpump_booster_heater` | `binary_sensor.ecodan_heatpump_zusatzheizung` |
| `heartbeat` | `sensor.ecodan_heatpump_esp_uptime` | `sensor.ecodan_heatpump_esp_betriebszeit` |
| `flow_temp` / `return_temp` | `sensor.ecodan_heatpump_feed_temp` / `…_return_temp` | `sensor.ecodan_heatpump_vorlauftemperatur` / `…_rucklauftemperatur` |
| `flow_rate` | `sensor.ecodan_heatpump_flow_rate` | `sensor.ecodan_heatpump_durchflussrate` |
| `outdoor_temp` | `sensor.ecodan_heatpump_outside_temp` | `sensor.ecodan_heatpump_aussentemperatur` |
| `controller_heating_consumed` | `sensor.ecodan_heatpump_heating_consumed` | `sensor.ecodan_heatpump_heizung_verbraucht` |
| `controller_dhw_consumed` | `sensor.ecodan_heatpump_dhw_consumed` | `sensor.ecodan_heatpump_tww_verbraucht` |
| `controller_date` | `sensor.ecodan_heatpump_controller_date` | `sensor.ecodan_heatpump_controller_datum` |
| `controller_heat_today` | `sensor.ecodan_heatpump_estimated_total_daily_energy_produced` | `sensor.ecodan_heatpump_geschatzte_tagliche_energieproduktion` |
| `flow_setpoint` | `sensor.ecodan_heatpump_zone_1_setpoint_value` | `sensor.ecodan_heatpump_zone_1_sollwert` |
| `circuit_flow_temp` / `circuit_return_temp` | `sensor.ecodan_heatpump_z1_feed_temp` / `…_z1_return_temp` | `sensor.ecodan_heatpump_z1_vorlauftemperatur` / `…_z1_rucklauftemperatur` |

Die dritte Schreibweise ist die kurze ohne „ecodan_“ (`sensor.heatpump_feed_temp` usw.), so wie wir die Entitäten
nach der Einrichtung umbenannt haben. Bei anderem Gerätenamen oder anderer Sprache ordnet man die Rollen im Config
Flow von Hand zu; „Neu konfigurieren“ ändert sie später.

Nicht vom Mahtanar kommen: `electricity_meter` (eigener Zähler), `outdoor_temp_reference` (Wetter-Integration),
`room_temp` (Raumthermometer) und `circuit_pump_running` – der FTC meldet die Heizkreispumpe nicht getrennt, die Rolle
bleibt leer.

**Heizkreis hinter dem Puffer:** Die Fühler „Z1 Vorlauf/Rücklauf“ (THW6/THW7 am FTC) sitzen im Heizkreis nach dem
Puffer. Mit ihnen misst Audit 2, wie viel Temperatur der Puffer kostet (T1) und wie viel mehr der Heizkreis fördert
als die Wärmepumpe (T3). Ohne Puffer oder Weiche bleiben diese Rollen leer.

## Stammdaten

Das Modell-Profil **mitsubishi_pud_shwm140** schlägt aus dem Datenblatt vor:

- `capacity_min_table`: kleinste Heizleistung je Vorlauf (35/45/55 °C) und Außentemperatur (Data Book S. A-54),
- `immersion_heater_kw`: 3 kW (Werkseinstellung des Heizstabs im EHPT20X).

Von Hand ergänzt haben wir:

| Stammdatum | Wert | Woher |
|---|---|---|
| `hydraulic_separation` | `parallel_buffer` | Blick auf die Verrohrung |
| `flow_rate_min_lpm` | 14,3 l/min | Data Book PUD-SHWM140 S. A-13 |
| `circuit_flow_max_lpm` | 57 l/min | Kennlinie der Heizkreispumpe (Wilo Para 25/7, aus 25/6 und 25/8 interpoliert) |
| `heating_hours` | aus der Klimakarte des Bundesverbands Wärmepumpe für die eigene PLZ | waermepumpe.de/werkzeuge/klimakarte |
| `room_temp_target` | gewünschte Raumtemperatur | eigene Wahl |
| `data_since` | Zeitpunkt des Einbaus des Mahtanar | ältere Daten stammen aus anderer Quelle |

## Stellgrößen

Über den CN105 kann die Firmware nur einen Teil der Einstellungen schreiben. Für das Audit sind das die beiden Werte
der **Kurzzyklus-Sperre** der Firmware (Rollen `short_cycle_lockout`, `short_cycle_min_run`). Heizkurve,
Parallelverschiebung und Pumpenstufen lassen sich so nicht schreiben; dafür nennt die Aktion den Zielwert, und man
stellt ihn am Bedienteil bzw. an der Pumpe ein.

## Was wir damit gefunden haben

- **Heizkreispumpe auf Werkseinstellung:** Die Pumpe im Heizkreis lief auf höchster konstanter Drehzahl. Der
  Heizkreis förderte dadurch ein Vielfaches des Durchflusses der Wärmepumpe, Rücklaufwasser mischte sich im Puffer in
  den Vorlauf, und die Wärmepumpe musste mehrere Kelvin wärmer liefern (T1 gelb, T3 als Erklärung). Mit kleinster
  konstanter Drehzahl sank der Pufferverlust deutlich, und die Heizkörper rauschten nicht mehr. Die Umstellung auf
  eine Δp-v-Kennlinie brachte dagegen nichts, weil die Thermostatventile ganz offen standen.
- **Fühler-Offset:** Vor- und Rücklauffühler zeigen in Pausen mit laufender Pumpe einen kleinen Versatz (D4). Das
  Audit zieht ihn von der Wärme ab und zeigt beide Werte.
- **Mindestdurchfluss:** Der Durchfluss der Wärmepumpe lag an der Untergrenze des Herstellers, innerhalb der
  Messgenauigkeit (T4) – ein Punkt zum Beobachten, kein Mangel.
