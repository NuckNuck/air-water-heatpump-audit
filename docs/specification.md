# Luft-Wasser-Wärmepumpen-Audit – Spezifikation

Stand: Version 0.16.0. Fachliche Grundlage der Integration: was jede Prüfung misst, wann sie urteilt und woher jede
Schwelle stammt. Die Abschnittsnummern verwenden auch die Kommentare im Code (z. B. „Spezifikation 1.5“).
Aufbau des Codes und Entscheidungen zum Umbau auf Audit-Module: [`audit_modules_design.md`](audit_modules_design.md).

Quellen stehen als Kurzschlüssel in Klammern, das Verzeichnis folgt in Abschnitt 9.

---

## 1. Rahmen

### 1.1 Grundsätze

1. **Strom immer vom Zähler** (Rolle `electricity_meter`). Eigene Stromwerte der Wärmepumpen-Steuerung sind meist
   Schätzungen und erscheinen nur als Vergleich in Audit 0 (D5).
2. **Wärme selbst gerechnet** aus Durchfluss × Spreizung × ρ·cp (4,153 kJ/(l·K)). Der Fühler-Offset aus D4 wird
   abgezogen; solange er nicht belastbar ist (< 20 Fenster), steht „vorläufig“ dabei. Angezeigt werden immer beide
   Werte, roh und korrigiert; Urteile rechnen mit dem korrigierten, pessimistischeren Wert.
3. **Jede Schwelle trägt eine Herkunft:**
   - `sourced`: aus einer gelesenen Quelle übernommen (Kurzschlüssel + Seite)
   - `derived`: aus belegten Zahlen abgeleitet (die Ableitung steht dabei)
   - `physical`: physikalisch zwingend, z. B. Energiebilanz oder Messauflösung
   - `descriptive`: keine Schwelle in der Literatur, nur Anzeige ohne Farbe
4. **Kein Urteil ohne Datenbasis.** Jede Prüfung hat eine Mindestmenge (Gate). Ist sie nicht erreicht, lautet das
   Ergebnis „nicht bewertbar“ mit Begründung, nie eine geratene Farbe.
5. **Hochrechnungen sind höchstens gelb.** Rot braucht gemessene Werte im Bewertungszeitraum.
6. **Rot nur außerhalb der Messtoleranz.** Wo Fühler oder Durchflussmesser die Aussage nicht hergeben, bleibt es bei
   Gelb.
7. **Dem Besitzer helfen, nicht verwirren:** Jedes Audit soll eine klare Aussage liefern; erklärende Kennzahlen sind
   `info` und ändern das Gesamturteil nicht.

### 1.2 Urteilsstufen

| Key | Anzeige | Bedeutung |
|---|---|---|
| `ok` | grün | im belegten oder abgeleiteten Normalbereich |
| `hint` | gelb | auffällig, beobachten oder prüfen |
| `warn` | rot | klar außerhalb, Handlungsbedarf |
| `info` | blau | Kennzahl ohne Bewertungsmaßstab, oder unplausibel gut (Messhinweis) |
| `not_assessable` | grau | Mindestmenge nicht erreicht, Eingang oder Stammdatum fehlt |

Gesamturteil eines Audits = schlechtestes Urteil seiner bewerteten Prüfungen; `info` zählt nicht mit. Sind alle
Prüfungen `not_assessable`, ist auch das Audit `not_assessable`.

**Grün im Zweifel (seit 0.12.0):** Liegt eine Abweichung unterhalb der Fühler- oder Messtoleranz oder ist sie
minimal, und ist keine nennenswerte Effizienzeinbuße zu erwarten, ist das Urteil `ok`. Das Bemerkenswerte steht als
Anmerkung im Text, nichts wird weggelassen. `info` bleibt Kennzahlen vorbehalten, die eine gelbe oder rote Prüfung
erklären (T3, T5), und unplausibel guten Werten. Ziel: wenige Anmerkungen, die zählen, statt vieler blauer Zeilen.

Zu jedem Urteil gehört eine Datenqualität `dq` (`high`, `medium`, `low`), siehe Audit 0.

### 1.3 Eingänge (Rollen)

Die Prüfungen kennen die Anlage nur über Rollen. Welche Entität eine Rolle erfüllt, legt der Besitzer im Config Flow
fest; bekannte Schnittstellen schlagen eine Zuordnung vor (Profile in `profiles.py`, außerhalb des Kerns). Ein
Profil kennt mehrere Schreibweisen je Rolle (z. B. je Sprache der Firmware-Labels); vorgeschlagen wird die erste, die
es in der Instanz gibt. Beispiel einer vollständigen Anlage: [`examples/mitsubishi_ecodan_mahtanar.md`](examples/mitsubishi_ecodan_mahtanar.md).

| Rolle | Bedeutung | Genutzt von |
|---|---|---|
| `electricity_meter` | Zählerstand Strom der Wärmepumpe (kWh) | D5, D8, Audit 1, C5 |
| `compressor_running` | Verdichter läuft (an/aus) | Zyklen, Audit 1–3 |
| `compressor_frequency` | Verdichterfrequenz (Hz) | C7 |
| `flow_temp`, `return_temp` | Vor- und Rücklauf am Wärmeerzeuger | D3, D4, Wärme, T1–T5 |
| `flow_rate` | Durchfluss am Wärmeerzeuger (l/min) | Wärme, T3, T4 |
| `outdoor_temp` | Außenfühler der Wärmepumpe | D10, Audit 1, C4 |
| `outdoor_temp_reference` | Außentemperatur eines Wetterdienstes (`sensor` oder `weather`, Attribut `temperature`) | D10 |
| `pump_running` | Pumpe der Wärmepumpe läuft | D4, T2 |
| `defrost` | Abtauung aktiv | Zyklen, D4, D10, C6 |
| `dhw_active` | Warmwasserbereitung aktiv | Zyklus-Klassen, E4, Audit 2 |
| `immersion_heater`, `booster_heater`, `booster_heater_2` | Heizstab bzw. Zusatzheizungen an | C5 |
| `heartbeat` | regelmäßig wechselnder Wert der Schnittstelle (z. B. Laufzeit) | D2, D9, gültige Tage |
| `controller_heating_consumed`, `controller_dhw_consumed` | Tageswerte Strom laut Steuerung | D5 |
| `controller_date` | Datum der Steuerung | D6 |
| `controller_heat_today` | Wärmezähler der Steuerung, Tageswert (zählt ohne Home Assistant weiter) | E1–E4: Lücken auffüllen |
| `flow_setpoint` | Soll-Vorlauf aus der Heizkurve | T5 |
| `circuit_flow_temp`, `circuit_return_temp` | Vor- und Rücklauf im Heizkreis hinter Puffer oder Weiche (optional) | T1–T3 |
| `circuit_pump_running` | Heizkreispumpe läuft (optional) | T1 |
| `room_temp` | Raumtemperatur des wichtigsten Raums (optional) | T6 |
| `dhw_tank_temp` | Temperatur im Warmwasserspeicher | Audit 4 |
| `dhw_setpoint` | Warmwasser-Sollwert (optional) | W2 |
| `price_signal` | aktueller Strompreis bei dynamischem Tarif, €/kWh (optional) | K1, K2, K4 |
| `grid_lock` | Sperre oder Dimmung durch den Netzbetreiber aktiv (optional) | K5 |

Rollen mit Text-Zustand: `controller_date`. Alle anderen werden als Zahl gelesen, an/aus als 1/0.

### 1.4 Stammdaten

Options Flow in Abschnitten, dazu die Personen im Haushalt als Untereinträge (6.6). Leere optionale Felder heißen „unbekannt“; die abhängige Prüfung ist dann
`not_assessable` mit dem Grund „Stammdaten fehlen“, nie ein Ersatzwert eines anderen Geräts.

| Abschnitt | Key | Bedeutung | Genutzt von |
|---|---|---|---|
| Anlage | `hydraulic_separation` | `none`, `series_buffer`, `parallel_buffer`, `hydraulic_separator`, `unknown` | T1, T3 |
| Anlage | `flow_rate_min_lpm` | Mindestdurchfluss der Wärmepumpe laut Hersteller | T4 |
| Anlage | `circuit_flow_max_lpm` | größter Förderstrom der Heizkreispumpe laut Datenblatt; T3 kappt die Mischungsbilanz darauf | T3 |
| Anlage | `capacity_min_table` | kleinste Heizleistung (kW) je Vorlauftemperatur und Außentemperatur, YAML, linear interpoliert | C4 |
| Anlage | `immersion_heater_kw`, `booster_heater_kw`, `booster_heater_2_kw` | Leistung von Heizstab und Zusatzheizungen | C5, W3 |
| Warmwasser | `dhw_tank_volume_l` | Nenninhalt des Warmwasserspeichers | W4, W6 |
| Warmwasser | `cold_water_c` | Kaltwassertemperatur im Jahresmittel, Vorgabe 10 °C | W6 |
| Warmwasser | `dhw_disinfection_interval_days` | Abstand der Aufheizung auf 60 °C, Vorgabe 7 Tage | W2 |
| Standort und Komfort | `heating_hours` | Heizstunden pro Jahr am Standort (BWP-KK) | C1 |
| Standort und Komfort | `heating_degree_days` | langjähriges Mittel der Gradtagzahl G20/15 am Standort (Kd/a) | K2 |
| Standort und Komfort | `room_temp_target` | gewünschte Raumtemperatur | T6 |
| Kosten | `tariff_price` | Arbeitspreis des Wärmepumpenstroms (€/kWh); Vorschlag aus dem Energie-Dashboard, wenn dort der Zähler der Rolle `electricity_meter` als Netzbezug steht | K1–K3 |
| Kosten | `tariff_base_fee` | zusätzlicher Grundpreis des Wärmepumpenzählers (€/a) | K1–K3 |
| Kosten | `household_price` | Arbeitspreis des Haushaltsstroms (€/kWh) | K3 |
| Kosten | `reference_fuel_price` | Preis des früheren Brennstoffs je abgerechneter kWh, mit Grundpreis-Anteil | K1, K2 |
| Kosten | `reference_efficiency` | Jahresnutzungsgrad der früheren Heizung, bezogen auf die abgerechnete kWh; Vorgabe 0,86 (Gas-Brennwertkessel, DBU-BW S. 7/39: Mittel 86,2 % auf Hs, n = 60; Gas wird nach Brennwert abgerechnet) | K1, K2 |
| Auswertung | `window_days` | Auswertefenster in Tagen (Standard 30; mit Recorder wirkt höchstens dessen Aufbewahrung) | alle |
| Auswertung | `data_since` | Daten gelten ab (z. B. Einbau der Schnittstelle) | alle |
| Auswertung | `data_source` | `auto`, `influxdb` oder `recorder` | alle |

Ein Modell-Profil in `profiles.py` kann Datenblattwerte vorschlagen; der Besitzer bestätigt sie im Options Flow.

### 1.5 Ereignisse

Der Besitzer trägt Änderungen an der Anlage als Untereintrag ein: Zeitpunkt, Art (`heating_curve`, `valves`,
`hydraulic_balancing`, `pump_setting`, `dhw_setting`, `hardware`, `other`) und Notiz. Ereignisse teilen die Zeit in
Abschnitte; Audits mit Mehrtageswerten mitteln nie über einen Trenner hinweg.

- **Audit 0** prüft die Daten und nutzt das ganze Fenster.
- **Audits 1–5** rechnen ab dem letzten Ereignis im Fenster (`section_start`). Jede Ereignisart setzt sie zurück.
- **Ausnahmen:** D4 und T2 (Fühlerabgleich) nutzen das ganze Fenster, denn Ereignisse ändern die Anlage, nicht die
  Fühler. Der Zeitstrahl speichert Tageswerte über das ganze Fenster.
- Kein aktives Nachfragen: Die Integration fordert keine Ereignisse an.

### 1.6 Geltungsbereich: Luft-Wasser-Wärmepumpen

1. **Prüfungen kennen nur Rollen und Stammdaten**, keine Hersteller, Modelle oder Entitäts-IDs. Hardware kommt nur
   über Profile (Vorbelegung im Config Flow) und Datenquellen (`recorder_source.py`, `influx_source.py`) hinein.
2. **Herstellerangaben stehen ausschließlich in den Stammdaten.**
3. **Fehlt eine Rolle, ist die Prüfung `not_assessable`** mit dem Grund „Eingang fehlt“. Kein Audit setzt einen
   Eingang voraus, den nicht jede Luft-Wasser-Wärmepumpe liefern kann; anlagenspezifische Eingänge sind optional.
4. **Schwellen kommen aus herstellerneutralen Quellen** (Feldstudien, Normen, Physik). Gilt eine Quelle nur für ein
   Gerät, steht das in der Herkunft, und die Schwelle wird über Stammdaten parametriert.
5. **Hydraulik ist ein Stammdatum**, weil Prüfungen wie der Pufferverlust nur bei bestimmten Schaltungen sinnvoll
   sind. Bei nicht zutreffender Schaltung lautet das Ergebnis `info` „trifft für diese Hydraulik nicht zu“.
6. **Nicht im Umfang:** Sole-Wasser- und Wasser-Wasser-Wärmepumpen (andere Quellentemperaturen und
   Gütegrad-Referenzen) sowie Hybridanlagen.

Verhaltensannahme: D4 und T2 setzen voraus, dass die Pumpe in Verdichterpausen weiterläuft. Ohne solche Fenster
sind sie `not_assessable`.

### 1.7 Aktionen

Ein gelbes oder rotes Urteil mündet in eine Aktion in der Spalte „Aktion“ (`audit_core/actions.py`):

- **wer** handelt: `owner` (selbst), `installer` (Fachbetrieb), `none` (nichts nötig),
- **was** zu tun ist (`text`, ein Satz), herstellerneutral,
- ein **Zielwert** mit dem heutigen Wert zum Vergleich (Zielwerte dürfen andere Prüfungen desselben Audits nutzen,
  z. B. nennt T1 den Ziel-Volumenstrom aus T3),
- wo es Handgriffe gibt, **konkrete Schritte** (`steps`, aufklappbar „So geht's“): woran man das Bauteil erkennt, was
  man vorher notiert, was man verstellt, dass man ein Ereignis einträgt, wie lange man beobachtet und woran man merkt,
  dass man zu weit gegangen ist.

Grün, `info` und „nicht bewertbar“ haben keine Aktion.

### 1.8 Stellgrößen

Kann die Schnittstelle eine angemerkte Einstellung schreiben, teilt sie das über Rollen mit (Config-Flow-Schritt
„Stellgrößen“, je Rolle eine `number`/`input_number`/`select`/`input_select`-Entität):

| Rolle | Prüfung | Vorschlag | Ereignis-Art |
|---|---|---|---|
| `circuit_pump_speed` | T1 | eine Stufe niedriger | `pump_setting` |
| `heating_curve_shift` | T6 | 1 K niedriger, an der Untergrenze gekappt | `heating_curve` |
| `short_cycle_lockout` | C3 | Sperre nach zu kurzem Heizlauf mindestens 30 min (Beispielwert einer Schnittstellen-Firmware) | `other` |
| `short_cycle_min_run` | C3 | Mindestlaufzeit mindestens 5 min | `other` |

Der Kern schreibt nie selbst: Er legt einen Vorschlag als `action.controls` ab. Die Karte zeigt „heute → Vorschlag“
und für Admins „Übernehmen“; nach einer Rückfrage ruft sie `number.set_value` bzw. `select.select_option` auf und
trägt ein Ereignis ein. Ist der Vorschlag erreicht, zeigt sie „✓ eingestellt“.

### 1.9 Datenreife

Jede Prüfung meldet, wie viel ihr noch fehlt (`progress`: vorhanden, nötig, Einheit, Zählweise `full_days`,
`elapsed` oder `rate`). Daraus schätzt `audit_core/readiness.py` je Audit den Tag, an dem alle Prüfungen bewertbar
sind (Hochrechnung, Audit 0 ab Fensterbeginn, Audits 1–5 ab dem letzten Ereignis). Fällt ein Tag durch, rückt der
Termin nach hinten.

In der Tabelle füllt sich der Marker einer `not_assessable`-Prüfung mit `progress` von links in der Farbe von
`ok` (Anteil vorhanden ÷ nötig, abgerundet); ohne `progress` (Eingang fehlt) bleibt er grau. Sobald die Prüfung
bewertbar ist, zeigt der Marker ihr Urteil.

---

## 2. Audit 0 – Datenbasis

Ziel: Bevor eine Prüfung urteilt, muss feststehen, ob die Daten dafür taugen. Audit 0 liefert `dq` und Korrekturwerte
an die anderen Audits.

| ID | Key | Prüft | Gate | Urteil | Herkunft |
|---|---|---|---|---|---|
| D1 | `history_depth` | Verfügbare Rohdaten (Recorder-Aufbewahrung, InfluxDB angebunden) | – | `ok` InfluxDB oder Recorder ≥ 30 d · `hint` Recorder 7–30 d (Hinweis Datenträger) · `warn` < 7 d | `derived`: Wochen- und Monatsvergleiche brauchen 7 bzw. 30 Tage |
| D2 | `coverage` | Anteil der Zeit mit lückenlosem Heartbeat (Lücke = > 180 s ohne Wechsel) | – | `ok` ≥ 98 % · `hint` 90–98 % · `warn` < 90 % | `derived`: 98 % ≈ 30 min Ausfall pro Tag (emoncms bildet „Quality“ ebenso, ohne Schwelle) |
| D3 | `resolution` | Tatsächliche Auflösung je Eingang; daraus die Unsicherheit der Wärme | genug gespeicherte Werte | `ok`; Unsicherheit je Einzelwert als Anmerkung (mittelt sich über Tage aus) | `physical`: Quantisierung ± halbe Schrittweite je Fühler |
| D4 | `sensor_offset` | Zeitmittel Vorlauf − Rücklauf bei laufender Pumpe, Verdichter seit ≥ 5 min aus, keine Abtauung, kein Warmwasser. Zeitmittel statt Median, weil gestufte Fühler den Median auf eine Stufe einrasten lassen | ≥ 3 Fenster à ≥ 3 min; belastbar ab 20 | `ok` \|Offset\| ≤ 0,5 K · `hint` ≤ 1,0 K · `warn` > 1,0 K | `derived`: 0,5 K = typische Auflösungsgrenze; 1 K verfälscht bei Spreizung < 4 K die Wärme deutlich (ETI-2011) |
| D5 | `meter_vs_controller` | Strom laut Steuerung ÷ Zählerstrom über volle Tage mit lückenlosem Heartbeat | 7 Tage | `ok` 0,95–1,20 · `hint` außerhalb · `warn` < 0,80 oder > 1,50 | `derived` aus Community-Berichten (OEM): Schätzungen der Steuerung liegen meist 5–14 % über dem Zähler. Bestätigt zugleich, dass der Zähler die ganze Anlage misst |
| D6 | `controller_day_boundary` | Uhrzeit, zu der das Datum der Steuerung wechselt, gegen lokale Mitternacht | 1 Wechsel | `ok` Versatz ≤ 15 min · `hint` darüber (Uhr falsch, z. B. Sommerzeit nicht umgestellt) | `derived`: Tageswerte der Steuerung folgen ihrer eigenen Uhr |
| D8 | `meter_resolution` | Schrittweite der Zählerstände | genug Zählerstände | `ok` ≤ 0,1 kWh · `hint` gröber (viele Zähler liefern ohne Freischaltung per PIN nur ganze kWh) | `physical`: Tageswerte sind auf ± einen Schritt unsicher |
| D9 | `restart_artifacts` | Neustarts der Schnittstelle (Heartbeat fällt) und Lücken; Zustandswechsel ±30 s darum werden für alle Audits verworfen | – | `ok` · `hint` > 3 Neustarts pro Tag, erst ab 1 Tag Zeitraum | `derived` |
| D10 | `outdoor_sensor` | Tagesmittel Außenfühler gegen Wetterdienst, nur Tage mit ≤ 10 % Abtauzeit | 3 Tage | `ok` \|Δ\| ≤ 1,5 K · `hint` ≤ 3 K · `warn` > 3 K | `sourced`: Plausibilisierung gegen Wetterdaten (WPS S. 25); Außenfühler werden durch Abtauen verfälscht (OEM). Schwellen `derived` |

D7 (Energie-Methode der Steuerung) ist entfallen: Die Einstellung ist herstellerspezifisch, und D5 deckt die Frage
ab, ob die Steuerung misst oder schätzt.

**`dq` für alle Audits:** `high`, wenn D2, D4 und D8 `ok` sind · `medium` bei höchstens einer Abweichung · sonst
`low`. Ein nicht bewertbares D4 oder D8 zählt wie `hint` (Qualität unbekannt, nicht belegt gut).

**Datenquellen:** InfluxDB enthält keine `unavailable`-Zustände; ein Ausfall sieht dort wie ein konstanter Wert aus.
Lücken lassen sich deshalb nur über den Heartbeat erkennen. Der InfluxDB-Tag `entity_id` hat keine Domain; gleich
benannte Entitäten verschiedener Domains werden über den Tag `domain` getrennt.

---

## 3. Audit 3 – Leistung passt zum Bedarf

Ziel: Zeigen, ob und warum die Wärmepumpe taktet, ob sie ihre Modulation nutzt und ob der Heizstab unnötig läuft.
Takten ist ein Symptom, keine Ursache.

### 3.1 Zykluserkennung

- Ein Zyklus ist eine Phase von `compressor_running` an bis aus. Ein Lauf, der am Anfang des Zeitraums schon läuft
  oder am Ende noch läuft, zählt nicht als Start und fehlt in den Laufzeit-Statistiken.
- Aus-Phasen < 30 s zählen nicht als Stopp (WPQS S. 98 ff. erfasst kürzere Stopps ebenfalls nicht zuverlässig).
- Neustart-Artefakte (D9) werden verworfen.
- Ein Stopp ±2 min an einer Abtauung zählt getrennt und nicht als Takt (`derived`).
- **Klasse je Zyklus:** `heating`, `dhw` oder `mixed` (beides im selben Lauf; Warmwasser ab 60 s). Starts zählen in
  C1/C2 unabhängig von der Klasse (Verschleiß), kurze Zyklen (C3) nur für `heating`.

### 3.2 Prüfungen

| ID | Key | Kennzahl | Gate | Urteil | Herkunft |
|---|---|---|---|---|---|
| C1 | `starts_per_year` | Starts pro Jahr; vor Ablauf eines Jahres Hochrechnung Starts pro Heizstunde × `heating_hours` | 14 Tage; Stammdatum `heating_hours` | `ok` ≤ 2.000 · `hint` darüber. Weil es bisher immer eine Hochrechnung ist („Obergrenze“), nie `warn`; > 5.500 wäre `warn`, sobald ein ganzes Jahr gemessen ist (noch nicht gebaut) | `sourced`: WPQS S. 99–102 (ein Drittel ≤ 2.000, 90 % < 5.500). Hochrechnung `derived` und eine Obergrenze, weil bei Kälte weniger getaktet wird |
| C2 | `max_starts_per_hour` | höchste Startzahl in einem gleitenden 60-min-Fenster | 1 Tag | `ok` ≤ 6 · `hint` 7–12 · `warn` > 12 | `sourced`: Verdichterhersteller 6–12/h laut WPQS S. 98; Danfoss max. 12/h (DF-VZH S. 32) |
| C3 | `short_cycles` | Anteil und Anzahl der Heizzyklen < 10 min, zusätzlich < 3 min | 20 Heizzyklen | `ok` · `hint`: Heizzyklen < 3 min (ohne Abtauung/Neustart) an ≥ 2 verschiedenen Tagen; ein einzelner schlechter Tag (z. B. Wartung) reicht nicht | `sourced`: WPQS-Laufzeitklassen (< 10 min); 3 min = Mindestlaufzeit laut Danfoss (DF-VZH S. 47), übertragen |
| C4 | `load_vs_min_capacity` | mittlere Heizleistung eines vollen Tages gegen die kleinste Leistung bei Tagesmittel außen und mittlerem Vorlauf | 1 voller Tag ohne Lücken; Stammdatum `capacity_min_table` | `info` mit Klartext: unter der kleinsten Stufe → Takten physikalisch unvermeidbar; darüber bei vielen Starts → Regelung/Hydraulik prüfen | `physical` + Datenblatt der Anlage. Erklärt C1–C3, kein eigenes Urteil |
| C5 | `backup_heater_share` | Heizstab-Strom (Einschaltdauer × Nennleistung) ÷ Zählerstrom | 7 Tage; Stammdaten Heizstab-kW | `ok` ≤ 2 % · `hint` 2–4 % · `warn` > 4 % | `derived` aus WPQS S. 96–97 (Hälfte < 0,2 %, oberes Feld 2–4 %); Mittel 1,3 % (WPQS-PI) bzw. 1,9 % (WPS) |
| C6 | `defrost` | Abtauungen pro Verdichter-Laufstunde, zusätzlich nur für Laufzeit über +5 °C außen (Außentemperatur vom Wetterdienst, sonst Außenfühler) | Band über +5 °C: ≥ 5 h Lauf | `ok` (`info` ohne Außentemperatur) · `hint`: über +5 °C mehr als 2 Abtauungen je Laufstunde | `derived`: Abtaubereich −2…+5 °C (BFE-AT), darüber sollte kaum Reif entstehen; 2/h und 5 h eigene Festlegung. Wetterdienst bevorzugt, weil Abtauen den Außenfühler verfälscht (D10) |
| C7 | `modulation` | Laufzeitanteil ≤ 20 Hz und Verteilung in 10-Hz-Klassen | Laufzeit mit Frequenzwerten | `ok` | `descriptive`: keine Schwelle in der Literatur |

Geplant, noch nicht gebaut: **C8** Heizlast-Regression (Wochenmittel Wärme über Außentemperatur, ≥ 4 Wochen) gegen
die Nennleistung (Verfahren WPQS Kap. 6.1).

---

## 4. Audit 1 – Effizienz

Ziel: Zeigen, wie viel Wärme die Wärmepumpe aus einer Kilowattstunde Strom macht, und ob das für ihre Temperaturen
normal ist.

### 4.1 Rechenweg

- **Systemgrenze:** Strom = alles, was der Zähler misst (Verdichter, Ventilator, Steuerung, Pumpen im Gerät,
  Heizstab, Standby). Wärme am Erzeuger vor Puffer oder Weiche, inkl. Warmwasser, Abtauwärme abgezogen (WPQS S. 68).
  Das liegt wegen Pumpen und Standby einige Prozent unter einer reinen Erzeuger-Arbeitszahl.
- **Gültiger Tag:** voller Kalendertag in Ortszeit, Zählerstand an beiden Mitternächten bekannt (keine Lücke grenzt an
  Mitternacht), Strom ≥ 2 kWh (darunter ist ein Zählerschritt von 1 kWh mehr als 50 %).
- **Lücken im Tag (F175/F176):** Zeiten ohne Heartbeat (> 180 s) werden nicht mit dem letzten Wert überbrückt, sondern
  geschätzt aufgefüllt: (a) Rolle `controller_heat_today` (Wärmezähler der Steuerung, zählt ohne Home Assistant
  weiter) → Zählerdifferenz über die Lücke; ohne Zähler oder bei Rücksetzung in der Lücke (b) nach Heizlast:
  gemessene Wärme × Σ(20 °C − außen) in der Lücke ÷ Σ im übrigen Tag, nur Stunden unter 15 °C (Gradtagzahl G20/15,
  VDI 4710; Außentemperatur bevorzugt vom Wetterdienst); ohne Heizlast (c) nach Zeitanteil. Offset-Korrektur und
  ideale Strommenge folgen im Verhältnis des gemessenen Teils, Warmwasser wird nicht aufgefüllt. Der Tag zählt, wenn
  die aufgefüllte Wärme ≤ 10 % der Tageswärme und die Lücken zusammen ≤ 6 h sind; er trägt `gap_min`,
  `gap_heat_kwh`, `gap_share_pct`, `gap_method`, E1 nennt die Lücke im Text.
- **Woche:** die letzten 7 gültigen Tage seit dem letzten Ereignis (nicht zwingend zusammenhängend).
- **Gütegrad** (Konvention WPQS Kap. 6.7 S. 122–125): Carnot-COP = T_Senke ÷ (T_Senke − T_Quelle), T_Senke = Mittel
  aus Vor- und Rücklauf am Erzeuger, T_Quelle = Außentemperatur, beide in Kelvin. Ideale Strommenge =
  ∫ Wärmeleistung ÷ Carnot-COP dt; Gütegrad = ideale ÷ gemessene Strommenge (eigene Festlegung, der Bericht nennt die
  Gewichtung nicht). Zeitpunkte mit Hub < 5 K zählen nicht.

### 4.2 Prüfungen

| ID | Key | Kennzahl | Gate | Urteil | Herkunft |
|---|---|---|---|---|---|
| E1 | `daily_cop` | Arbeitszahl des letzten gültigen Tages (roh und korrigiert); alle Tage in `details` | 1 gültiger Tag | immer `info`; „vorläufig“, solange D8 gröber als 0,1 kWh oder D4 nicht belastbar | `descriptive`: für Tageswerte gibt es keine anerkannte Skala |
| E2 | `weekly_cop` | Arbeitszahl der Woche mit Feld-Vergleichswert bei gleicher Außentemperatur | 7 gültige Tage | `info`: Monatsmittel von L/W-Anlagen im Feld, linear zwischen 2,7 bei 2 °C und 3,8 bei 13 °C | `sourced`: WPQS S. 87 f. (Mittelwert, keine Grenze) |
| E3 | `carnot_efficiency` | Gütegrad der Woche (korrigierte Wärme) | 7 gültige Tage, `dq` ≠ `low` | `ok` 0,30–0,50 · `hint` < 0,30 · `info` > 0,50 (unplausibel gut, eher Messfehler) · `warn` < 0,24 nur mit belastbarem D4 | `derived`: WPQS S. 123, L/W 0,32–0,44 (Ø 0,39). Grün ab 0,30, weil diese Systemgrenze Pumpen, Standby, Heizstab und Warmwasser enthält. Rot bei 0,24 = 0,32 × 0,75, auch bei ±15 % Wärmefehler klar unter dem Feld |
| E4 | `dhw_share` | Anteil Warmwasser an der Wärme der Woche | 7 gültige Tage | `info` mit Vergleich zum Feldmittel 19 % | `sourced`: WPQS S. 72 |

**Gesamturteil Audit 1:** nur E3. Die Arbeitszahl allein taugt nicht als Urteil, weil sie vor allem vom Wetter und
vom Vorlauf abhängt; der Gütegrad rechnet beides heraus. Warum der Vorlauf hoch ist, beantwortet Audit 2, warum die
Wärmepumpe taktet, Audit 3.

Geplant: Hochrechnung aufs Jahr über Gradtage (frühestens nach 4 Wochen), Gütegrad je Hub-Klasse über die eigene
Historie, getrennte Arbeitszahl für Warmwasser (braucht einen Zähler mit Nachkommastellen).

---

## 5. Audit 2 – Vorlauf so niedrig wie möglich

Ziel: Zeigen, ob die Wärmepumpe wärmer heizt, als die Heizkörper brauchen, und woher der Aufschlag kommt (Puffer
oder Weiche, Spreizung, Heizkurve). Wirkung jedes vermeidbaren Kelvins: **2–3 % Effizienz** (`sourced`: BINE-2013
S. 4/6 nennt 1,5–4 %/K; VDZ-LF S. 8).

### 5.1 Auswertefenster

- **Heizbetrieb stationär:** Verdichter seit ≥ 10 min an, kein Warmwasser, keine Abtauung (`derived`: Vorlauf und
  Spreizung steigen nach dem Start erst an; 10 min = Laufzeitklasse aus C3).
- **Pause mit Umwälzung:** Verdichter seit ≥ 5 min aus, Pumpe an, kein Warmwasser, keine Abtauung (wie D4).
- Ist `circuit_pump_running` zugeordnet, zählen nur Zeitpunkte mit laufender Heizkreispumpe (ISE-HPC-2026 wertet den
  Ladeverlust ebenso nur bei gleichzeitigem Laden und Entladen aus).
- Neustart-Artefakte (D9) fallen heraus. Mittelwerte sind zeitgewichtet.

### 5.2 Prüfungen

| ID | Key | Kennzahl | Gate | Urteil | Herkunft |
|---|---|---|---|---|---|
| T1 | `buffer_flow_loss` | mittlere Differenz WP-Vorlauf − Heizkreis-Vorlauf im Heizbetrieb, korrigiert um T2 | ≥ 3 h Heizbetrieb aus ≥ 3 Zyklen; `info` „trifft nicht zu“ bei `none`/`series_buffer` | `ok` ≤ 1,5 K · `hint` ≤ 4 K · `warn` > 4 K nur mit belastbarem T2; dazu „≈ x–y % Effizienz“ | `derived`: Fühlertoleranz ±0,5–1 K je Fühler (SIKA-VVX, HUBA-210) → unter 1,5 K nicht unterscheidbar; ISE-HPC-2026 misst im Mittel bis 2,5 K; 4 K ≈ 8–12 % Mehrverbrauch. Keine Norm-Schwelle gefunden (BWP-LF, VDZ-LF) |
| T2 | `circuit_sensor_offset` | Zeitmittel WP-Vorlauf − Heizkreis-Vorlauf in Pausen mit Umwälzung | ≥ 3 Fenster à ≥ 3 min; belastbar ab 20 | `ok` bei \|Offset\| ≤ 1 K („Fühler stimmen überein“, Anzeige auf 0,1 K) · `hint` bei \|Offset\| > 1 K („Fühler prüfen, T1 unsicher“) | `physical`; 1 K wie D4: Fühlertoleranz ±0,5–1 K, Auflösung 0,5 K |
| T3 | `flow_ratio` | Volumenstrom Heizkreis ÷ Wärmepumpe aus der Mischungsbilanz V_WP/V_HK ≈ (T_HK,VL − T_HK,RL) ÷ (T_WP,VL − T_HK,RL); mit gemessenem Durchfluss auch in l/min, gekappt auf `circuit_flow_max_lpm` | wie T1; zusätzlich T_WP,VL − T_HK,RL ≥ 2 K | `info`: Verhältnis > 1 → „Heizkreis fördert mehr als die Wärmepumpe, Rücklauf mischt sich in den Vorlauf“ (Erklärung zu T1) | `physical` (Energie- und Massenbilanz). Bei gestuften Fühlern nur Größenordnung, deshalb kein Urteil |
| T4 | `heat_pump_spread` | Spreizung der Wärmepumpe im Heizbetrieb und mittlerer Durchfluss | wie T1 | `ok` · `hint`: Spreizung > 10 K · `hint`: Durchfluss mehr als max(1,5 l/min; 10 %) unter `flow_rate_min_lpm`, knapp darunter nur Text. Kleine Spreizung ist kein Mangel, nie `warn` | Feldreferenz `sourced`: WPS S. 67 (Ø 5,5 K, 3,0–7,8 K), heatpumpmonitor.org (L/W Median 3,2 K); 10 K: VDI 4645 laut VDZ-LF Tab. T6; Toleranz: SIKA-VVX (±0,6–0,8 l/min), HUBA-210 (bis ±1,5 l/min) |
| T5 | `flow_vs_setpoint` | mittlere Differenz Ist − Soll im Heizbetrieb, getrennt für WP-Vorlauf und Heizkreis-Vorlauf | wie T1 | `info`: zeigt, auf welchen Fühler die Steuerung regelt und wie viel der Puffer aufschlägt | `descriptive` (WPS S. 55 f.: „Speicheraufschlag“, ohne Schwelle) |
| T6 | `heating_curve_headroom` | Raumtemperatur (`room_temp`) gegen `room_temp_target`, Tagesmittel an Heiztagen (≥ 1 h Heizbetrieb); ein Tag zählt nur, wenn der Raumfühler seit ≥ 90 % des Tags misst (Einbau am Abend lieferte sonst nur den Abendwert) | 5 Heiztage im selben Abschnitt; Rolle `room_temp` | `hint` „Kurve hat Reserve, um 1 K absenken“: an ≥ 5 von 7 Heiztagen ≥ Ziel + 1 K und kein Tag < Ziel − 0,5 K · `info` „Kurve knapp“: ein Tag < Ziel − 0,5 K · sonst `ok`; nie `warn` | `derived`: Verfahren „schrittweise absenken“ (Ratgeber-Konsens); 0,5 K = Regelgenauigkeit von Raumreglern nach EN 15500 (Herstellerangaben, Sekundärquelle) |

Bei T6 gibt es bewusst keine Höchstdauer für einen Messwert: Home Assistant speichert gleichbleibende Werte nicht
erneut, ein ruhiger Tag sähe sonst lückenhaft aus. Abgedeckt ist alles ab dem ersten Messwert.

**Gesamturteil Audit 2:** schlechtestes Urteil aus T1, T4 und T6; T2, T3 und T5 erklären.

Geplant: nötige Vorlauftemperatur aus der Heizkörperkennlinie gegen das Soll der Heizkurve; Feldvergleich der
mittleren Heizkreistemperatur (WPS S. 68/83).

### 5.3 Nachrecherche zu den Schwellen

- Keine Norm oder Richtlinie nennt eine Kelvin-Schwelle für den Pufferverlust (BWP-LF und VDZ-LF gelesen; VDI 4645
  und VDI 2073 kostenpflichtig, nicht gelesen). VDZ-LF warnt nur qualitativ vor „unerwünschten Durchmischungen“
  (S. 9).
- heatpumpmonitor.org (eigene Auswertung, L/W ≥ 300 Tage, UK-lastig, nicht nach Gebäude bereinigt): Median-SCOP
  ohne hydraulische Trennung 3,96 (n = 410), mit Puffer 3,63 (n = 60), mit Weiche 3,36 (n = 12).
- Die Regel „Erzeugerkreis 10–20 % mehr Volumenstrom“ ist in keiner Primärquelle belegt → T3 bleibt `info`.

---

## 6. Audit 4 – Warmwasser

Ziel: Zeigen, ob die Wärmepumpe Warmwasser effizient, hygienisch ausreichend warm und zu einer günstigen Tageszeit
bereitet, und wie viel der Speicher verliert. Warmwasser macht im Feld 19 % der Wärme aus (WPQS S. 7/73).

### 6.1 Rechenweg

- **Ladung:** Phase mit `dhw_active` an, mindestens 60 s, vollständig im Abschnitt, ohne Lücke im Lebenszeichen und
  ohne Neustart-Artefakt (D9). Strom je Ladung = Zählerstand am Ende − am Anfang (Grundsatz 1), Wärme und ideale
  Strommenge wie in Audit 1 (4.1) über die Ladung. Ladungen unter 0,2 kWh Strom zählen für W1 nicht.
- **Speichertemperatur nach der Ladung:** höchster Wert von `dhw_tank_temp` bis 30 min nach dem Ende (vor der nächsten
  Ladung). Während der Ladung zeigen manche Speicherfühler Mischwerte aus nachströmendem Kaltwasser; sie werden nicht
  verwendet.
- **Aufheizen auf 60 °C** (Legionellenschaltung): Ladung mit Speichertemperatur ≥ 59 °C (60 °C − 1 K Fühlertoleranz).
- **Ruhige Nacht** (W4): längstes Stück zwischen 0 und 5 Uhr Ortszeit ohne Ladung (inklusive 30 min danach), ohne
  Lücke und Artefakt, mindestens 3 h; kühlt der Speicher darin schneller als 1 K/h ab, wurde gezapft, die Nacht zählt
  nicht (`derived`).

### 6.2 Prüfungen

| ID | Key | Kennzahl | Gate | Urteil | Herkunft |
|---|---|---|---|---|---|
| W1 | `dhw_efficiency` | Gütegrad über alle Ladungen (ideale ÷ gemessene Strommenge), dazu Arbeitszahl mit Feldvergleich | 7 Ladungen mit Zählerwerten; D8 ≤ 0,1 kWh; `dq` ≠ `low` | wie E3: `ok` 0,30–0,50 · `hint` < 0,30 · `warn` < 0,24 nur mit belastbarem D4 · `info` > 0,50 | `derived`: Der Gütegrad rechnet den höheren Hub heraus, es gelten die Schwellen von E3. Feldvergleich Arbeitszahl nur Warmwasser L/W im Bestand: Mittel 2,8, 2,1–3,5 (WPQS S. 79, n = 18); heatpumpmonitor.org Median 3,09 (OEM) |
| W2 | `dhw_temperature` | Median der Speichertemperatur nach dem Laden über alle Ladungen; unter 49 °C dazu der Abstand der Aufheizungen auf 60 °C im ganzen Fenster | 7 Ladungen; unter 49 °C ohne Aufheizung erst nach `dhw_disinfection_interval_days` + 1 Tag | unter 49 °C: `ok`, wenn alle Abstände (auch bis jetzt) ≤ Stammdatum + 1 Tag, sonst `hint` (Entscheid F226) · `hint` > 61 °C (Effizienz) · sonst `ok`, unter 50 °C mit Anmerkung „knapp“; Text nennt den Austausch aus W6 | `sourced`: untere Betriebstemperatur 50 °C für Ein- und Zweifamilienhäuser ohne Zirkulation, mit Zirkulation gelten 60 °C (DVGW-INFO S. 11); eine periodische Aufheizung ersetzt das nicht sicher (UBA-TWW S. 5); UBA empfiehlt durchgängig über 55 °C (S. 4). Ein Intervall für die Aufheizung nennt kein Regelwerk (DVGW-INFO S. 15, UBA-TWW S. 5); Vorgabe 7 Tage ist eigene Festlegung (`derived`), Mitsubishi Ecodan ab Werk 15 Tage (MEL-FTC6 S. 26). Über 60 °C verlangt keine Regel mehr, jedes Kelvin kostet ≈ 1,4 % (WPQS S. 171). Je 1 K Fühlertoleranz |
| W3 | `disinfection` | Aufheizungen auf 60 °C pro Woche, Heizstab-Strom dabei (Einschaltdauer bis 30 min nach der Ladung × `immersion_heater_kw`) | 14 Tage | `ok` · `hint` > 2 pro Woche · `ok` mit Text, wenn schon der Median (W2) ≥ 59 °C ist | `derived`; keine Pflicht und keine Häufigkeit in den Regeln (DVGW-INFO S. 15, UBA-TWW S. 5) – keine Aufheizung ist hier kein Befund, unter 50 °C bewertet sie W2 |
| W4 | `standby_loss` | Warmhalteverlust aus dem Abkühlen in ruhigen Nächten: S = V · ρc · ΣΔT ÷ Σt, umgerechnet auf 45 K (Speicher 65 °C, Raum 20 °C angenommen), mit Effizienzklasse | 5 ruhige Nächte und 15 h; Stammdatum `dhw_tank_volume_l`; Speicher ≥ 10 K über 20 °C | `ok` bis Klassengrenze D · `hint` darüber; Text nennt Klasse und kWh/Tag | `physical`; Klassen nach EU-812 Anh. II Tab. 2 (S < a + b·V^0,4); Mindestanforderung für neue Speicher Klasse C (EU-814, [sekundär]); eine Klasse Toleranz, weil 0,5-K-Fühler und angenommene Raumtemperatur die Schätzung etwa eine Klasse unsicher machen (grün im Zweifel). Prüfbedingung 45 K [sekundär] |
| W5 | `dhw_timing` | Einbuße nach Carnot, weil bei kälterer Luft geladen wird als im Mittel der wärmsten drei Stunden desselben Tages, gewichtet mit der Wärme je Ladung | 7 Ladungen mit Außentemperatur (Wetterdienst bevorzugt) | `ok` < 10 % · `hint` ≥ 10 % (gerundeter Wert) | `physical`: Carnot-COP T_Senke ÷ (T_Senke − T_außen), ≈ 2,0–2,5 %/K bei 45 K Hub; 10 % eigene Festlegung (`derived`): darunter ist ein Ladefenster den Komfortverlust kaum wert. Duscht der Haushalt überwiegend morgens (6.6), sagt der Text, dass ein Fenster am Nachmittag bis zum nächsten Morgen reichen muss |
| W6 | `dhw_draw` | Zapfmenge: (geladene Wärme − Bereitschaftsverlust aus W4) je Tag, als Mischwasser 40 °C und als Liter bei Speichertemperatur; Austausch = Speicherinhalt ÷ Liter je Tag; dazu Vorrat eines vollen Speichers V·(T − T_kalt)/(40 − T_kalt) bei heutiger Temperatur, 50 und 55 °C, Nachladetemperatur (Median der Speichertemperatur bei Ladebeginn), Ladeleistung gegen eine Dusche (10 l/min) und Bedarf laut Haushalt (6.6) | Wert ab 1 vollem Tag (vorläufig bis 7 Tage); Urteil ab 3 Tagen; Stammdatum `dhw_tank_volume_l` | `ok` Austausch ≤ 3 Tage · `hint` ≤ 7 Tage · `warn` darüber | `sourced`: bestimmungsgemäßer Betrieb = Austausch mindestens alle 7, besser alle 3 Tage (DVGW-STAG 2020, DVGW-TWIN-2024 S. 2). Für den Speicherinhalt nennt keine Regel eine eigene Frist; er wird wie das Wasser im Netz behandelt. Ohne W4 zählt die ganze geladene Wärme, der Text sagt das |

**Abschnitt:** Das Audit rechnet ab dem letzten Ereignis der Arten `dhw_setting`, `hardware` oder `other`; Ereignisse
am Heizkreis (Heizkurve, Ventile, Abgleich, Pumpe) ändern am Warmwasser nichts und beginnen es nicht neu.

**Gesamturteil Audit 4:** schlechtestes Urteil aus W1–W6. Zeitstrahl: Gütegrad der Ladungen je Tag mit den Bändern
von E3.

Nicht im Umfang: Zirkulationsverluste (WPQS S. 84: 32 % der geladenen Wärme bei 5 Anlagen) lassen sich ohne
Zirkulationsfühler nicht von Speicherverlusten trennen; sie erscheinen in W4 als hoher Verlust.

### 6.6 Haushalt

Personen als Untereinträge (`person`): Name, Geburtsjahr, Duschen und Bäder pro Woche (leer = typisch fürs Alter),
übliche Duschzeit (`morning`, `midday`, `evening`, `varied`) und Anwesenheit:

| `presence` | Felder | Anwesend an einem Tag |
|---|---|---|
| `always` | – | immer |
| `rotation` | `weeks_present`, `weeks_absent`, `rotation_start` | in den ersten `weeks_present` Wochen jedes Zyklus ab `rotation_start` (auch rückwärts) |
| `weekdays` | `weekdays`, `every_n_weeks`, `rotation_start` | an diesen Wochentagen in jeder n-ten Woche ab dem Anker |
| `share` | `share_pct` | mit diesem Anteil an jedem Tag |

Erwarteter Bedarf je Person und Tag als Mischwasser 40 °C: (Duschen · 40 l + Bäder · Wanne) ÷ 7 + 10 l Grundbedarf,
gewichtet mit der Anwesenheit und gemittelt über die Tage des Abschnitts.

| Größe | Wert | Herkunft |
|---|---|---|
| Dusche | 40 l bei 40 °C | DIN EN 15450 Anh. E [sekundär über BWP-TWE S. 17] |
| Durchfluss Dusche | 10 l/min (normal 10–12, Sparbrause < 9) | VZ-NRW |
| Vollbad | 120 l; Normen 103 l (DIN EN 15450) bis 140 l (DIN 4708) | `derived` aus [sekundär] |
| Kinderbad bis 5 Jahre | 60 l (etwa halbe Wanne) | `derived` |
| Grundbedarf (Hände, Küche) | 10 l/Tag | `derived` aus den kleinen Zapfungen der Profile in DIN EN 15450 |
| Gewohnheiten nach Alter | bis 5 J.: 2 Bäder/Woche (BIÖG: Säuglinge 1–2); 6–11 J.: 3 Duschen + 1 Bad; ab 12 J.: 6 Duschen | Kinder `derived` (keine Erhebung); Erwachsene: 43–52 % duschen täglich (Herstellerumfragen) |
| Plausibilität | Erwachsener ≈ 44 l Mischwasser/Tag ≙ 25 l bei 60 °C | BWP-TWE S. 23 |
| Kaltwasser | 10 °C Planungswert; real im Mittel ≈ 14 °C | BWP-TWE S. 20; Viega/SBZ 2019 [sekundär] |

Nicht im Umfang (eigenes Issue): Schulferien je Person – Kinder getrennter Eltern können in einem anderen Bundesland
zur Schule gehen; in den Ferien ändern sich oft Anwesenheit und Gewohnheiten.

---

## 7. Audit 5 – Kosten

Ziel: Den gemessenen Strom in Euro umrechnen: Was kostet eine Kilowattstunde Wärme, was das Jahr, und lohnt der Tarif?

### 7.1 Rechenweg

- **Tage:** die gültigen Tage aus Audit 1 (4.1), auch mit aufgefüllten Lücken.
- **Kosten eines Tages:** Mit `price_signal` jeder Zählerschritt × der Preis zu Beginn des Schritts; sonst Strom ×
  `tariff_price`. Grundpreis (`tariff_base_fee`) anteilig je Tag (÷ 365).
- **Vergleichspreis der Wärme** = `reference_fuel_price` ÷ `reference_efficiency`.
- **Hochrechnung** (K2): Je Tag Gradtage G = 20 °C − Tagesmittel außen, wenn das Mittel unter 15 °C liegt, sonst 0
  (G20/15, VDI 3807/DWD-GT; Außentemperatur vom Wetterdienst bevorzugt). Ausgleichsgerade Strom bzw. Wärme = a + b·G
  über die gültigen Tage; Jahr = 365·a + b·`heating_degree_days`. Ist die Spannweite der Tages-G < 4 K oder die Gerade
  unplausibel (a < 0 oder b ≤ 0), wird alles mit den Gradtagen skaliert („grob“).

### 7.2 Prüfungen

| ID | Key | Kennzahl | Gate | Urteil | Herkunft |
|---|---|---|---|---|---|
| K1 | `heat_price` | Wärmepreis der letzten 7 gültigen Tage in ct/kWh, mit Grundpreis-Anteil | 7 gültige Tage; Preis | `ok` ≤ Vergleichspreis × 1,10 · `hint` darüber · `info` ohne Vergleichspreis | `derived`: 10 % ≈ Messunsicherheit der Wärme; Nutzungsgrad Gas-Brennwert 0,86 auf Hs (DBU-BW). Wochenwert, im Winter höher als im Jahresmittel |
| K2 | `annual_cost` | Strom, Kosten und Wärme im Jahr, Ersparnis gegen den Vergleich | 14 gültige Tage; `heating_degree_days` | `info` (Hochrechnung) | `sourced`: Gradtagzahl G20/15 (DWD-GT); Referenz Potsdam 3.666,8 Kd. Mindestens 14 Tage `derived` |
| K3 | `tariff_benefit` | Ersparnis des eigenen Wärmepumpentarifs: (`household_price` − `tariff_price`) × Jahresstrom aus K2 − `tariff_base_fee` | wie K2; beide Preise; kein `price_signal` | `ok` ≥ 0 · `hint` < 0 | `physical` (Rechnung) |
| K4 | `price_timing` | gezahlter Mittelpreis gegen das Zeitmittel von `price_signal` | 7 Tage; Rolle `price_signal` | `ok` ≤ +3 % · `hint` darüber | `derived`: 3 % eigene Festlegung (Zufall einer Woche) |
| K5 | `grid_lock` | Sperren pro Tag, Dauer, längste Sperre; Heizstab-Stunden während und bis 2 h nach einer Sperre | 7 Tage; Rolle `grid_lock` | `ok` · `hint`, wenn der Heizstab dabei läuft. Anzahl und Dauer nur im Text | `derived`; seit 2024 keine feste Höchstdauer, nur Mindestleistung 4,2 kW (BK6-22-300 Anl. 1 Ziff. 4.5.1; präventiv höchstens 2 h täglich bis Ende 2028, Ziff. 10.5). Die frühere Tarifregel „3 × 2 h“ ist ohne Primärquelle und wird nicht verwendet |

**Gesamturteil Audit 5:** schlechtestes Urteil aus K1, K3–K5; K2 ist Information. Zeitstrahl: Wärmepreis je Tag (ohne
Grundpreis) mit dem Band von K1.

Geplant: Anteil eigener PV-Strom (Rolle für Netzbezug bzw. Eigenverbrauch).

---

## 8. Umsetzung

- **Kern** `audit_core/`: reines Python ohne Abhängigkeiten, Funktionen auf Zeitreihen (Liste von Zeit/Wert). Je
  Audit ein Modul in `audit_core/audits/`, gemeinsame Grundgrößen (Offset, Wärme, Zyklen, `dq`) in `context.py`.
- **Datenquellen:** Recorder von Home Assistant oder InfluxDB 2 über die vorhandene InfluxDB-Integration; fehlende
  Rollen kommen aus dem Recorder, bei Fehlern fällt die Integration auf den Recorder zurück.
- **Texte** für Menschen deutsch mit Dezimalkomma (`num()`), Anzahlen mit `count()`; Hilfe zu jeder Prüfung in
  `help.py`, Aktionen in `actions.py`.
- **Tests:** `python3 -m unittest` (Kern, inkl. Vergleichsbericht einer synthetischen Anlage in `tests/golden/`),
  `pytest tests_ha` (Integration).

---

## 9. Quellen

Status: [gelesen] = selbst gelesen, [sekundär] = nur über Zusammenfassungen, Foren oder Herstellerangaben.

| Kürzel | Quelle | Status |
|---|---|---|
| WPQS | Fraunhofer ISE: Abschlussbericht „WP-QS im Bestand“, 2. Fassung 25.11.2025. https://www.ise.fraunhofer.de/content/dam/ise/de/documents/projekte/WP-QS_Schlussbericht.pdf | [gelesen] |
| WPQS-PI | Fraunhofer ISE: Presseinformation 03.11.2025 „Wärmepumpen heizen auch im Altbau klimafreundlich“. https://www.ise.fraunhofer.de/content/dam/ise/de/documents/presseinformationen/2025/3025_ISE_PI_Waermepumpen-heizen-auch-im-Altbau-klimafreundlich.pdf | [gelesen] |
| WPS | Fraunhofer ISE: Schlussbericht „WPsmart im Bestand“, V2.1, 23.07.2020. https://wp-monitoring.ise.fraunhofer.de/wpqs-im-bestand/download/Berichte/BMWi-03ET1272A-WPsmart_im_Bestand-Schlussbericht.pdf | [gelesen] |
| ISE-HPC-2026 | Bavia Bampi, Avci, Wapler, Günther, Nienborg (Fraunhofer ISE): „Investigation of the effect of storage operation in Single-Family Homes with Separate Tanks for Space Heating and DHW“, 15th IEA Heat Pump Conference 2026, doi:10.23697/r0dk-ep45 | [gelesen] |
| DVGW-INFO | DVGW: Information „Energieeinsparungen im Warmwasserbereich in Trinkwasser-Installationen – geht das?“, März 2023. https://www.dvgw.de/medien/dvgw/leistungen/publikationen/energiesparen-warmwasser-dvgw-langfassung.pdf | [gelesen] |
| UBA-TWW | Umweltbundesamt: Fact Sheet „Trinkwarmwasserkonzepte für Gebäude mit einer Wärmepumpenheizung“, Januar 2024. https://www.umweltbundesamt.de/publikationen/trinkwarmwasserkonzepte-fuer-gebaeude-einer | [gelesen] |
| DVGW-STAG | DVGW: Information zum bestimmungsgemäßen Betrieb von Trinkwasser-Installationen, 08.05.2020. https://www.dvgw.de/medien/dvgw/covid19/dvgw-information-trinkwasser-installation-coronavirus.pdf | [gelesen] |
| DVGW-TWIN-2024 | DVGW: Kompaktinformation Stagnation und Wiederinbetriebnahme, März 2024 (Versorger-Kopie). https://evf.de/dateien/netze/twin-stagnation-wiederinbetriebnahme-maerz2024.pdf | [gelesen] |
| BWP-TWE | Bundesverband Wärmepumpe: Leitfaden Trinkwassererwärmung, 2019. https://www.waermepumpe.de/uploads/tx_bcpageflip/BWP_LF_TWW_2019_02.pdf | [gelesen]; zitiert DIN EN 15450 |
| VZ-NRW | Verbraucherzentrale NRW: Warmes Wasser sparen, 2025. https://www.verbraucherzentrale.nrw/de-x-simple/energie/warmes-wasser-sparen-88554 | [gelesen] |
| BIÖG | Bundesinstitut für Öffentliche Gesundheit, kindergesundheit-info.de: Baden. https://www.kindergesundheit-info.de/themen/entwicklung/0-12-monate/babys-pflege/baden/ | [gelesen] |
| MEL-FTC6 | Mitsubishi Electric: Ecodan FTC6 Installationshandbuch, Doc. 685702, Jan. 2025, PDF-S. 26, 76 (UK-Ausgabe) | [gelesen], Herstellerangabe |
| W 551 | DVGW-Arbeitsblatt W 551 (Kleinanlagen: 60 °C Reglertemperatur empfohlen), kostenpflichtig, über Fachpresse | [sekundär] |
| EU-812 | Delegierte Verordnung (EU) Nr. 812/2013, Anhang II Tabelle 2 (Effizienzklassen Warmwasserspeicher). https://www.legislation.gov.uk/eur/2013/812/annex/II/adopted | [gelesen] |
| EU-814 | Verordnung (EU) Nr. 814/2013 (Ökodesign Warmwasserspeicher: Warmhalteverlust ab 2017 höchstens Klasse C); Prüfbedingung 45 K über EN 12897 | [sekundär] |
| DBU-BW | Wolff, Teuber, Budde, Jagnow: Felduntersuchung Brennwertkessel, DBU-Abschlussbericht AZ 14133, 2004. https://opac.dbu.de/ab/DBU-Abschlussbericht-AZ-14133.pdf | [gelesen] |
| BK6-22-300 | Bundesnetzagentur: Festlegung zu § 14a EnWG, Anlage 1 zum Beschluss vom 27.11.2023. https://www.bundesnetzagentur.de/DE/Beschlusskammern/1_GZ/BK6-GZ/2022/BK6-22-300/Beschluss/BK6-22-300_Beschluss_Anlage1.pdf | [gelesen] |
| DWD-GT | Deutscher Wetterdienst: Gradtagzahlen nach VDI 3807 und Klimafaktoren. https://www.dwd.de/DE/leistungen/klimafaktoren/klimafaktoren.html | [gelesen] |
| BINE-2013 | BINE Themeninfo I/2013 „Elektrisch angetriebene Wärmepumpen“, FIZ Karlsruhe. https://www.energieinstitut.at/tools/machvier/doc/BINE_WP_Effizienz_reale_Bedingungen.pdf | [gelesen] |
| BWP-LF | Bundesverband Wärmepumpe: „Leitfaden Hydraulik“, Stand Juli 2016 | [gelesen] |
| BWP-KK | Bundesverband Wärmepumpe: Klimakarte (Norm-Außentemperatur und Heizstunden je PLZ). https://www.waermepumpe.de/werkzeuge/klimakarte/ | [gelesen] |
| VDZ-LF | VDZ: Leitfaden „Umsteigen auf die Wärmepumpe“ | [gelesen] |
| BFE-AT | EnergieSchweiz: „Betriebsoptimierung Heizung: Abtauung Luft-Wasser-Wärmepumpen“, Merkblatt 2019. https://pubdb.bfe.admin.ch/de/publication/download/9977 | [gelesen] |
| DF-VZH | Danfoss: Application guidelines VZH088-117-170, AB221086441234en, 2019 | [gelesen] |
| ETI-2011 | ETI/PassivSystems: Heat Meter Investigation, 2011. https://ukerc9.rl.ac.uk/publications/technical_report/DE_DE2003_5.pdf | [gelesen] |
| SIKA-VVX, HUBA-210 | Datenblätter der Durchfluss- und Temperatursensoren SIKA VVX und Huba Control Typ 210 (Messgenauigkeit) | [sekundär] |
| EN 15500 | Regelgenauigkeit von Raumreglern, über Herstellerangaben | [sekundär] |
| OEM | OpenEnergyMonitor-Forum und heatpumpmonitor.org (Methodik, Feldwerte). https://heatpumpmonitor.org | [sekundär] |
