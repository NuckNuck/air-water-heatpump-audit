# Changelog

Alle Änderungen an der Integration, neueste zuerst. Jede Version gibt es als
[GitHub-Release](https://github.com/NuckNuck/air-water-heatpump-audit/releases); HACS bzw. der Marketplace (ab Home
Assistant 2026.11) bieten sie als Update an.
Versionsnummern nach [Semantic Versioning](https://semver.org/lang/de/): Solange die Hauptversion 0 ist, kann jede
Nebenversion (0.x.0) Namen, Entitäten oder Einstellungen ändern.

## [0.21.0] – unveröffentlicht

### Geändert
- **Ereignisse setzen die Bewertung nicht mehr zurück** (#39): Nach einem neuen Ereignis rechnen alle Audits über
  denselben Zeitraum weiter wie vorher. Bisher fielen viele Prüfungen sofort auf „nicht bewertbar“ oder „vorläufig“,
  obwohl sich an den Daten nichts geändert hatte. Ob eine Änderung wirkt, zeigt der Zeitstrahl. Über der Tabelle
  steht „Letztes Ereignis …“ statt „Bewertet ab …“. Die Zeile „davor: …“ unter vorläufigen Urteilen entfällt.
- **K4 nur mit dynamischem Strompreis** (#40): Ohne zugeordneten dynamischen Strompreis gibt es K4 weder in der Karte
  noch als Sensor; ein vorhandener K4-Sensor wird entfernt.

- **W2 bewertet das eingestellte Warmwasser-Soll** (#44): Bisher galt der Median der Speichertemperatur über alle
  Ladungen im Zeitraum. Wer nach einem gelben W2 das Soll anhob, sah wochenlang weiter Gelb, weil die alten Ladungen
  im Median blieben. Jetzt zählt das aktuelle Soll, eine Umstellung wirkt sofort. Ohne zugeordneten Soll-Sensor nimmt
  W2 ersatzweise die Speichertemperatur nach dem Laden der letzten 7 Tage. Unter 50 °C bleibt W2 grün, wenn der
  Speicher regelmäßig auf 60 °C aufgeheizt wird.

### Behoben
- **Zahlen mit höchstens zwei Nachkommastellen** (#42): Unter „Datenbasis“ stand der Zählerstrom ungerundet
  (z. B. „443.21299999999997 kWh“). Die Attribute aller Audit-Sensoren und die Zahlen in Prüftexten haben jetzt
  höchstens zwei Nachkommastellen; die Karte zeigt Wärme, Offset und Zählerstrom im Zahlformat der HA-Sprache.

## [0.20.0] – 2026-11-09

### Behoben
- **Audit-Seite blieb beim Aktualisieren leer** (#31): Nach jedem gespeicherten Ereignis, nach Änderungen im Menü
  „Haushalt“ oder an den Stammdaten wurde die Integration komplett neu geladen; bis zum Ende der neuen Rechnung waren
  alle Audits „nicht verfügbar“. Jetzt bleiben die bisherigen Ergebnisse stehen und es wird im Hintergrund neu
  gerechnet. Neu geladen wird nur noch, wenn sich Rollen oder Audits ändern.

### Schneller
- **Rohdaten bleiben zwischen den Läufen im Speicher** (#35): Statt bei jedem Lauf das ganze Fenster neu zu laden,
  holt die Integration nur das Neue seit dem letzten Lauf. Ganz geladen wird nach dem Start, bei geänderten Rollen,
  Preis-Sensoren oder Datenquelle, nach einem Fehler und einmal am Tag (Spezifikation 8.2).

### Neu
- **Hinweis „Wird aktualisiert …“ mit Fortschrittsbalken** in Audit- und Zeitstrahl-Karte, solange gerechnet wird,
  mit Schritt und geschätzter Restzeit (aus der Dauer des letzten Laufs). Grundlage ist das neue WebSocket-Abo
  `air_water_heatpump_audit/progress/subscribe` (Spezifikation 8.1).
- **Arbeitszahl der letzten 365 Tage** (#33): neuer Sensor `sensor.air_water_heatpump_audit_cop_365_days`,
  Wärme ÷ Strom über die gespeicherten Tage des Zeitstrahls (korrigierte Wärme, auch Statistik-Tage). Solange noch
  kein volles Jahr vorliegt, nennt er im Attribut `days`, wie viele Tage er abdeckt (Spezifikation 4.3).

## [0.19.0] – 2026-11-09

### Neu
- **K3: Lohnt sich der eigene Zähler?** (#25) Neben der Ersparnis nennt K3 jetzt, ab welchem Haushaltsstrompreis und
  ab welchem Jahresstrom der Wärmepumpe sich der eigene Zähler lohnt, und welchen Preisabstand zwischen Haushaltsstrom
  und Wärmepumpentarif es dafür braucht (#27; unabhängig von der Preishöhe, gut zum Vergleich von Angeboten). Ein Diagramm in der Tabelle zeigt die
  Grenzkurve und die eigene Lage.
- **Frühere Heizung im Kosten-Zeitstrahl** als durchgezogene, beschriftete Linie; bisher steckte der Vergleich nur in
  der Bandgrenze (+ 10 %). Die Vergleichslinien anderer Heizsysteme sind dicker und am rechten Ende beschriftet.
- Neue Einstellung **Reduziertes Netzentgelt nach § 14a EnWG (Modul 2)** im Abschnitt Kosten, Standard aus. Nur mit
  eigenem Zähler zulässig. Ist sie an, weist K3 darauf hin, dass das reduzierte Netzentgelt beim Zusammenlegen der
  Zähler entfiele.
- **Zeitraum-Umschalter** im Zeitstrahl: 3 Tage, 7 Tage, 30 Tage, 90 Tage, 1 Jahr, alles (Kartenoption `range`, Standard 90).

### Behoben
- Unter dem Urteil ragte „vorläufig · x von y …“ in die Aktionsspalte; die Zeile bricht jetzt um.

## [0.18.0] – 2026-11-09

### Neu
- **Wärmepreise anderer Heizsysteme im Kosten-Zeitstrahl** (#15): gestrichelte Linien für Heizöl, Erdgas,
  Holzpellets, Fernwärme und Stromdirektheizung, in ct je kWh Wärme (Brennstoffpreis ÷ Nutzungsgrad). Die Preise
  kommen aus Preis-Sensoren mit dem Attribut `heating_system`, z. B. aus einer Preis-Integration oder einem
  Scrape-Sensor für den örtlichen Händler (README). Die Tageswerte bleiben im Zeitstrahl gespeichert.
- Neue Option **Wärmepreise anderer Heizsysteme vergleichen** im Abschnitt Kosten, Standard: an.
- **Feste Kosten im Wärmepreis** (#17): Grundpreis des Wärmepumpentarifs und neu das Messstellenentgelt des
  Wärmepumpenzählers, neue Auswahl „eigener Zähler“ oder „Haushaltszähler“. Sie werden über die Jahreswärme verteilt
  (Hochrechnung K2, sonst frühere Abrechnung) und stecken jetzt auch im Zeitstrahl. Leer heißt „nicht eingetragen“
  und erzeugt einen Hinweis, 0 ist ein gültiger Wert.
- **Frühere Heizung** als Stammdaten: System und Jahresverbrauch so, wie er auf der Abrechnung steht; das Audit
  rechnet ihn in Wärme um. Der eigene Nutzungsgrad gilt für dieses System.
- **Reparaturmeldung** „Feste Kosten der Wärmepumpe fehlen“ mit kleinem Formular; in der Karte ein Link
  **⚙ Einstellungen** je Audit und bei fehlenden Stammdaten. Die Anlagendaten öffnen dann direkt den Abschnitt Kosten.
- Die Legende des Kosten-Zeitstrahls (Vergleichslinien, feste Kosten) steht hinter **ⓘ Legende** und öffnet sich
  beim Überfahren oder Antippen. Fehlende Stammdaten bleiben sichtbar.
- Grundpreis und Zählermiete werden mit Zeitraum eingetragen: **pro Monat** oder **pro Jahr**, so wie es im Vertrag
  oder auf der Rechnung steht. Vorauswahl beim Grundpreis „pro Monat“, bei der Zählermiete „pro Jahr“; schon
  eingetragene Beträge gelten weiter pro Jahr. Die Felder heißen jetzt „Grundpreis Wärmepumpen-Stromtarif
  (Stromanbieter)“ und „Zählermiete Wärmepumpenzähler (Messstellenentgelt)“.
- Arbeitspreise (Wärmepumpenstrom, Haushaltsstrom, früherer Brennstoff) wahlweise in **ct/kWh** oder **€/kWh**,
  vorausgewählt ct/kWh. Schon eingetragene Preise gelten weiter in €/kWh.
- **Ereignisse und Personen nicht mehr als einzelne Untereinträge** (#18): Auf der Integrationsseite standen sie
  flach neben den Audits. Ereignisse verwaltet jetzt die Zeitstrahl-Karte (anlegen, ändern ✎, löschen ✕), Personen
  das neue Menü **Konfigurieren → Haushalt**. Die Stammdaten stehen unter **Konfigurieren → Anlagendaten**.
  Bestehende Untereinträge werden beim Update automatisch übernommen.
- **Tage aus der Langzeitstatistik** (#19): Nach einer Neuinstallation zeigt der Zeitstrahl auch die Tage vor den
  Rohdaten (bis 400 Tage zurück) mit Arbeitszahl und Wärmepreis. Strom kommt vom Zähler, die Wärme vom Wärmezähler
  der Steuerung, korrigiert mit dem Verhältnis zur selbst gerechneten Wärme (ab einer Woche eigener Messwerte). Die
  Hochrechnung K2 und die Jahreswärme für die festen Kosten nutzen diese Tage ab dem letzten Ereignis; alle anderen
  Prüfungen bleiben bei Rohdaten. Das Tagesdetail der Karte kennzeichnet solche Tage.
- **Hochrechnung K2 schon ab 5 gültigen Tagen** (#21), als vorläufig gekennzeichnet bis 14 Tage; sie wird mit jedem
  Tag genauer. Jahreswärme für die festen Kosten und die Wirkung je Aktion folgen derselben Hochrechnung. Das Audit
  Vorlauf liest dafür auch die Außentemperatur, damit es allein dieselbe Wirkung zeigt wie im Gesamtlauf.

### Behoben
- K2 meldete bei 5–13 gültigen Tagen „Außentemperatur fehlt für die Gradtage“, obwohl nur Tage fehlten.
- Statistik-Tage beginnen mit dem ersten vollen Tag nach `data_since`; der angebrochene Einbautag zählt nicht.
- Die Reparaturmeldung „Feste Kosten der Wärmepumpe fehlen“ schloss sich beim Öffnen sofort als behoben und leerte
  dabei Zählerart, Grundpreis und Messstellenentgelt (0.18.0b2/b3). Jetzt erscheint das Formular.
- Preis-Sensoren können `includes_fixed_charges` und `annual_base_fee` angeben. Die Vergleichslinie
  Stromdirektheizung kommt aus dem Arbeitspreis des Haushaltsstroms.

### Geändert
- Nutzungsgrad Holzpellets 0,80 statt 0,85, belegt mit Feldmessungen (65–90 %).
- K1 rechnet die festen Kosten je kWh über die Jahreswärme statt je Tag; ohne Jahreswärme bleiben sie draußen, der
  Text sagt das. K3 zieht Grundpreis und Messstellenentgelt ab und ist am Haushaltszähler nur Information.

## [0.17.0] – 2026-11-01

Enthält auch alle Änderungen aus 0.16.0 (nicht einzeln veröffentlicht, siehe unten).

### Neu
- **Wirkung je Aktion**: Gelbe und rote Prüfungen nennen, was ihre Aktion ungefähr im Jahr bringt oder kostet
  (kWh Strom und €), z. B. Vorlauf senken (T1, T6), Ladezeit (W5), Heizstab (C5), Tarif (K3, K4) – und was die
  Legionellenschaltung kostet (W2).
- **Zielkonflikte** stehen bei der Aktion, z. B. „Der Speicher muss bis zum nächsten Duschen reichen (W6)“.
- Die Karte zeigt oben **„Was am meisten bringt“**: bis zu fünf Aktionen nach Ersparnis.
- Stammdatum **Wohnfläche**: K2 nennt Wärme und Strom je m² und die ungefähre Klasse im Energieausweis; mit den
  Personen im Haushalt auch die Kosten je Person.

- **Vorläufige Urteile** (#11): Nach einem Ereignis (und beim Start) urteilt jede Prüfung schon ab einem Drittel
  ihrer Mindestmenge, z. B. nach 3 statt 7 Tagen. Die Karte zeigt solche Urteile blasser mit „vorläufig · 3 von 7
  vollen Tagen“. D4 und T2 behalten ihre Grenze, W3 urteilt nach einer Woche.
- **Stand vor dem Ereignis** (#11): Ist eine Prüfung vorläufig oder noch grau, steht darunter das Urteil aus dem
  Abschnitt vor der Änderung („davor: grün 0,31“), so sieht man gleich, ob die Änderung etwas bringt.

### Behoben
- Der **Zeitstrahl** zeigt keine leeren Tage vor dem ersten Messwert mehr; auch bereits gespeicherte leere Tage
  fallen weg (#9).

## [0.16.0] – nur als Pre-Release, enthalten in 0.17.0

### Neu
- **Personen im Haushalt** als Untereinträge: Geburtsjahr, Duschen und Bäder pro Woche (leer = typisch fürs Alter),
  übliche Duschzeit und Anwesenheit – immer, Wechselwochen ab einem Startdatum, bestimmte Wochentage (auch jede
  zweite Woche) oder ein Anteil der Zeit.
- **W6 Zapfmenge und Austausch**: Warmwasser pro Tag als Duschwasser 40 °C, Austausch des Speicherinhalts (gelb über
  3 Tagen, rot über 7 Tagen nach DVGW), Vergleich mit dem üblichen Bedarf des Haushalts, Vorrat eines vollen Speichers bei 45/50/55 °C,
  Nachladetemperatur und Ladeleistung im Vergleich zu einer laufenden Dusche.
- Stammdaten-Abschnitt **Warmwasser**: Speicherinhalt (bisher unter „Anlage“), Kaltwassertemperatur, Abstand der
  Aufheizung auf 60 °C.
- Release-Action: Ein Tag mit Zusatz (z. B. `v0.16.0b1`) wird ein Pre-Release.

### Geändert
- **W2**: Unter 50 °C grün, wenn der Speicher regelmäßig auf 60 °C aufgeheizt wird, sonst gelb; bisher war unter
  50 °C immer gelb. Die Aktion schlägt zuerst die Legionellenschaltung vor.
- **W4** nennt den Anteil des Verlusts an der geladenen Wärme.
- **W5** empfiehlt kein festes Ladefenster am Nachmittag mehr, sondern eines passend zu den Duschzeiten.
- **Audit Warmwasser** beginnt nur noch bei Ereignissen neu, die das Warmwasser betreffen (Warmwasser-Einstellung,
  Umbau, Sonstiges). Bisher verwarf z. B. eine verstellte Heizkreispumpe auch die Warmwasser-Daten davor. Die Karte
  zeigt je Audit das Ereignis, ab dem es rechnet.
- **W6** zeigt die Zapfmenge ab dem ersten vollen Tag (vorläufig) und bewertet den Austausch ab 3 Tagen.
- Werte mit Quellen belegt (Spezifikation 6.6): Dusche 40 l bei 40 °C und 10 l/min, Bedarf je Person nach dem
  BWP-Leitfaden, Stagnation nach DVGW. Kleinkinder rechnen mit 2 statt 3 Bädern pro Woche.

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

[Unveröffentlicht]: https://github.com/NuckNuck/air-water-heatpump-audit/compare/v0.17.0...HEAD
[0.17.0]: https://github.com/NuckNuck/air-water-heatpump-audit/releases/tag/v0.17.0
[0.11.0]: https://github.com/NuckNuck/air-water-heatpump-audit/releases/tag/v0.11.0
[0.10.2]: https://github.com/NuckNuck/air-water-heatpump-audit/releases/tag/v0.10.2
[0.10.1]: https://github.com/NuckNuck/air-water-heatpump-audit/releases/tag/v0.10.1
