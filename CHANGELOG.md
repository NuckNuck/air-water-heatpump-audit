# Changelog

Alle Änderungen an der Integration, neueste zuerst. Jede Version gibt es als
[GitHub-Release](https://github.com/NuckNuck/air-water-heatpump-audit/releases); HACS bietet sie als Update an.
Versionsnummern nach [Semantic Versioning](https://semver.org/lang/de/): Solange die Hauptversion 0 ist, kann jede
Nebenversion (0.x.0) Namen, Entitäten oder Einstellungen ändern.

## [Unveröffentlicht]

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
