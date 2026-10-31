# Changelog

Alle Änderungen an der Integration, neueste zuerst. Jede Version gibt es als
[GitHub-Release](https://github.com/NuckNuck/air-water-heatpump-audit/releases); HACS bietet sie als Update an.
Versionsnummern nach [Semantic Versioning](https://semver.org/lang/de/): Solange die Hauptversion 0 ist, kann jede
Nebenversion (0.x.0) Namen, Entitäten oder Einstellungen ändern.

## [Unveröffentlicht]

## [0.16.0] – in Arbeit

### Neu
- **Personen im Haushalt** als Untereinträge: Geburtsjahr, Duschen und Bäder pro Woche (leer = typisch fürs Alter),
  übliche Duschzeit und Anwesenheit – immer, Wechselwochen ab einem Startdatum, bestimmte Wochentage (auch jede
  zweite Woche) oder ein Anteil der Zeit.
- **W6 Zapfmenge und Austausch**: Warmwasser pro Tag als Duschwasser 40 °C, Austausch des Speicherinhalts (gelb über
  72 h), Vergleich mit dem üblichen Bedarf des Haushalts, Vorrat eines vollen Speichers bei 45/50/55 °C,
  Nachladetemperatur und Ladeleistung im Vergleich zu einer laufenden Dusche.
- Stammdaten-Abschnitt **Warmwasser**: Speicherinhalt (bisher unter „Anlage“), Kaltwassertemperatur, Abstand der
  Aufheizung auf 60 °C.
- Release-Action: Ein Tag mit Zusatz (z. B. `v0.16.0b1`) wird ein Pre-Release.

### Geändert
- **W2**: Unter 50 °C grün, wenn der Speicher regelmäßig auf 60 °C aufgeheizt wird, sonst gelb; bisher war unter
  50 °C immer gelb. Die Aktion schlägt zuerst die Legionellenschaltung vor.
- **W4** nennt den Anteil des Verlusts an der geladenen Wärme.
- **W5** empfiehlt kein festes Ladefenster am Nachmittag mehr, sondern eines passend zu den Duschzeiten.

## [0.15.1] – 2026-10-31

### Behoben
- Stammdaten: Ein Wert 0 (z. B. „Zusatzheizung 0 kW“) wurde im Formular nicht vorbelegt und ging beim nächsten
  Speichern verloren. Er bleibt jetzt erhalten.

## [0.15.0] – 2026-10-30

### Neu
- **Audit Warmwasser** (W1–W5): Gütegrad und Arbeitszahl der Warmwasserbereitung, Speichertemperatur gegen die
  Hygiene-Untergrenze von 50 °C und gegen unnötige Wärme über 60 °C, Häufigkeit der Aufheizung auf 60 °C mit
  Heizstab-Strom, Speicherverlust mit Klasse des Energielabels, Einbuße durch Laden zu kalten Tageszeiten.
- **Audit Kosten** (K1–K5): Wärmepreis in ct/kWh gegen den früheren Brennstoff, Kosten pro Jahr über die Gradtage des
  Standorts, lohnt der eigene Wärmepumpentarif, dynamischer Strompreis, Sperrzeiten des Netzbetreibers.
- Neue Einrichtungsschritte „Warmwasser“ und „Tarif“, neuer Stammdaten-Abschnitt „Kosten“. Der Arbeitspreis wird aus
  dem Energie-Dashboard vorgeschlagen.
- Profil Mitsubishi Ecodan (ESPHome): Speichertemperatur und Warmwasser-Sollwert werden vorgeschlagen.
- Zeitstrahl: Gütegrad Warmwasser und Wärmepreis je Tag.

### Hinweis
- Beide Audits sind nach dem Update nicht automatisch an: Einstellungen → Geräte & Dienste →
  Luft-Wasser-Wärmepumpen-Audit → **Audit hinzufügen**. Die Speichertemperatur über **Neu konfigurieren** zuordnen,
  Preise und Speicherinhalt unter **Konfigurieren** eintragen.

## [0.14.2] – 2026-10-27

### Behoben
- Karte: Die Spalte „Herkunft“ brach Wörter wie „beschreibend“ mitten im Wort um. Sie ist jetzt etwas breiter und
  bricht nicht mehr.

## [0.14.1] – 2026-10-27

### Behoben
- „Neu konfigurieren“ löste eine Warnung im Log aus (doppeltes Neuladen, ab Home Assistant 2026.12 ein Fehler).
  Neu geladen wird jetzt nur noch über den Update-Listener.

## [0.14.0] – 2026-10-27

### Neu
- Datenlücken in einem Tag (z. B. Home Assistant oder Sicherung kurz aus) kosten nicht mehr den ganzen Tag. Die Wärme
  der Lücke wird aufgefüllt – aus dem Wärmezähler der Steuerung, wenn er zugeordnet ist, sonst nach Heizlast
  (kalte Stunden wiegen mehr). Der Tag zählt, solange die aufgefüllte Wärme höchstens 10 % ausmacht und die Lücken
  zusammen höchstens 6 h dauern. Bisher fiel ein Tag schon ab 30 min Lücke weg.
- Neue optionale Rolle „Steuerung: Wärme heute (Tageszähler)“ im Schritt „Werte der Steuerung“; das Profil
  `esphome_ecodan` schlägt die geschätzte tägliche Energieproduktion vor. Bestehende Einträge: über
  „Neu konfigurieren“ ergänzen.
- Tagestabelle unter E1: Tage mit aufgefüllter Lücke tragen ein *, beim Überfahren steht Dauer, Anteil und Weg.

### Geändert
- Lücken werden nicht mehr mit dem letzten Messwert überbrückt; grenzt eine Lücke an Mitternacht, zählt der Tag
  nicht (Zählerstand unbekannt).

## [0.13.0] – 2026-10-27

### Neu
- Karte: Der graue Marker „nicht bewertbar“ füllt sich mit dem Datenstand von links grün (z. B. 2 von 3 Tagen =
  zwei Drittel grün); beim Überfahren steht „67 % – 2 von 3 vollen Tagen“. Sind die Daten vollständig, zeigt der
  Marker das Urteil der Prüfung. Prüfungen, denen ein Messwert fehlt, bleiben grau.

## [0.12.0] – 2026-10-27

### Geändert
- Grün im Zweifel: Prüfungen ohne Grenzüberschreitung und ohne nennenswerte Effizienzeinbuße sind jetzt grün statt
  blau. Was bemerkenswert ist, steht weiter als Anmerkung im Text. Betroffen: D3 Auflösung, D9 Neustarts,
  C3 kurze Heizläufe, C6 Abtauungen (blau nur ohne Außentemperatur), C7 Modulation. Blau bleibt für Kennzahlen, die
  eine gelbe Prüfung erklären (T3, T5), und für unplausibel gute Werte.
- Das Gesamturteil eines Audits kann dadurch grün werden, wo es bisher nur „Info“ zeigte.

## [0.11.1] – 2026-10-27

### Geändert
- T2 (Fühlerabgleich): Ein Unterschied bis 1 K liegt innerhalb der Fühlertoleranz und gilt jetzt als grün („Die beiden
  Vorlauffühler stimmen überein“) statt als blaue Info. Der Mittelwert wird in T2 und T1 nur noch auf 0,1 K genau
  angezeigt – die Fühler melden in 0,5-K-Schritten.

## [0.11.0] – 2026-10-27

### Neu
- Eigenes Icon: Außengerät einer Luft-Wasser-Wärmepumpe mit Lupe und Haken. Home Assistant ab 2026.3 zeigt es unter
  „Geräte & Dienste“ (Ordner `brand/` in der Integration); Vorlage `docs/brand/icon.svg`, MIT-Lizenz wie das Repo.

## [0.10.2] – 2026-10-27

### Geändert
- Karte: Die Datenreife braucht nur noch Titelzeile und Balken. Welches Audit ab wann bereitsteht und was ihm noch
  fehlt, steht im Tooltip beim Überfahren des Balkens oder des **?** (Klick hält ihn offen).

## [0.10.1] – 2026-10-26

### Neu
- Beispielanlage `docs/examples/mitsubishi_ecodan_mahtanar.md`: Aufbau, ESPHome-Konfiguration, Eigenheiten der
  Messwerte, Zuordnung der Rollen, Stammdaten und Befunde der Entwicklungsanlage.

### Behoben
- Die Einrichtung schlägt die Messwerte jetzt auch für die Standard-entity_ids der Ecodan-Firmware vor (Gerätename
  „Ecodan heatpump“, englische und deutsche Labels). Vorher passte die Vorbelegung nur zu umbenannten Entitäten.

## [0.10.0] – 2026-10-26

### Geändert
- C3 (sehr kurze Heizläufe): gelb erst, wenn an mindestens 2 verschiedenen Tagen Läufe unter 3 min vorkommen.
- C6 (Abtauungen): gelb bei mehr als 2 Abtauungen je Laufstunde über +5 °C außen, ab 5 h Lauf in diesem Band.
  Die Außentemperatur kommt vom Wetterdienst, sonst vom Außenfühler.
- Spezifikation liegt im Repo (`docs/specification.md`).

## [0.9.3] – 2026-10-26

### Behoben
- T6: Ein Tag zählt nur, wenn der Raumfühler seit mindestens 90 % des Tags misst; angebrochene Messtage verfälschen
  das Ergebnis nicht mehr.

## [0.9.2] – 2026-10-26

### Behoben
- Keine Fehler und Warnungen der Integration mehr im Home-Assistant-Log (`via_device_id`, Texte zur Mindestleistung).

## [0.9.1] – 2026-10-26

### Behoben
- Prüftexte mit richtiger Einzahl und Mehrzahl statt „1 Tage“ oder „Start(s)“.

## [0.9.0] – 2026-10-26

### Geändert
- Neuer Name „Luft-Wasser-Wärmepumpen-Audit“, Domain `air_water_heatpump_audit`, Sensoren
  `sensor.air_water_heatpump_audit_*`, Karten `custom:air-water-heatpump-audit-card` und
  `custom:air-water-heatpump-audit-timeline-card`. **Bestehende Einrichtungen des alten „WP-Audit“ werden übernommen,
  Dashboards müssen auf die neuen Namen umgestellt werden.**
- Kern ohne Herstellerbezug: Rollen der Steuerung neutral benannt, Vorschläge für bekannte Schnittstellen und Modelle
  als Profile außerhalb des Kerns.
- Kern in Audit-Module aufgeteilt; es werden nur die zugeschalteten Audits gerechnet.

### Neu
- Audits einzeln zu- und abschalten (Untereinträge mit eigenem Gerät, „Audit hinzufügen“ mit Hinweis auf fehlende
  Messwerte).
- Die Karte trägt sich selbst als Lovelace-Ressource ein und zeigt ohne `entities` alle zugeschalteten Audits.

## [0.8.1] – 2026-10-26

- Erster öffentlicher Stand (damals „WP-Audit“, Entwicklungsversion).

[Unveröffentlicht]: https://github.com/NuckNuck/air-water-heatpump-audit/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/NuckNuck/air-water-heatpump-audit/releases/tag/v0.11.0
[0.10.2]: https://github.com/NuckNuck/air-water-heatpump-audit/releases/tag/v0.10.2
[0.10.1]: https://github.com/NuckNuck/air-water-heatpump-audit/releases/tag/v0.10.1
