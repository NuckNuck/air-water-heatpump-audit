# Changelog

Alle Änderungen an der Integration, neueste zuerst. Jede Version gibt es als
[GitHub-Release](https://github.com/NuckNuck/air-water-heatpump-audit/releases); HACS bietet sie als Update an.
Versionsnummern nach [Semantic Versioning](https://semver.org/lang/de/): Solange die Hauptversion 0 ist, kann jede
Nebenversion (0.x.0) Namen, Entitäten oder Einstellungen ändern.

## [Unveröffentlicht]

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

[Unveröffentlicht]: https://github.com/NuckNuck/air-water-heatpump-audit/compare/v0.10.1...HEAD
[0.10.1]: https://github.com/NuckNuck/air-water-heatpump-audit/releases/tag/v0.10.1
