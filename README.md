# Luft-Wasser-Wärmepumpen-Audit für Home Assistant

> ## ⚠️ Entwicklungsversion
>
> **Diese Integration ist noch in Entwicklung. Sie läuft bisher an genau einer Anlage, Namen, Entitäten und
> Einstellungen können sich mit jedem Update noch ändern – auch so, dass man sie neu einrichten muss.** Sie liest nur
> mit und ändert nichts an der Wärmepumpe. Die Urteile sind Hinweise, kein Gutachten: Bitte nichts an der Anlage
> verstellen, ohne die Erklärung zur jeweiligen Prüfung gelesen zu haben, und im Zweifel den Fachbetrieb fragen.

## Worum geht es?

Eine Wärmepumpe heizt fast immer – aber oft nicht so sparsam, wie sie könnte. Typische Gründe: Die Heizkurve ist zu
hoch eingestellt, die Pumpen fördern zu viel Wasser, die Wärmepumpe schaltet ständig ein und aus („taktet“) oder ein
Temperaturfühler misst daneben. Von außen merkt man davon nichts, nur an der Stromrechnung.

Das **Luft-Wasser-Wärmepumpen-Audit** schaut sich die Messwerte an, die Home Assistant ohnehin von der Wärmepumpe
aufzeichnet, und beantwortet bis zu vier Fragen – jede ist ein eigenes **Audit**, das man einzeln zu- oder abschalten
kann:

| Audit | Frage | Beispiel für einen Befund |
|---|---|---|
| **Datenbasis** | Kann man den Messwerten trauen? | „Der Vorlauffühler zeigt 0,5 K mehr als der Rücklauffühler, obwohl beide gleich sein müssten.“ |
| **Effizienz** | Wie gut arbeitet die Wärmepumpe? | „Gütegrad 0,38 – im Bereich guter Anlagen aus dem Fraunhofer-Feldtest.“ |
| **Vorlauf** | Heizt sie wärmer als nötig? | „Hinter dem Pufferspeicher kommen 2,8 K weniger an, als die Wärmepumpe erzeugt.“ |
| **Leistung** | Passt die Wärmepumpe zum Haus? | „Hochgerechnet 5.200 Verdichterstarts im Jahr – viele Anlagen kommen mit unter 2.000 aus.“ |

Jede Prüfung bekommt eine Ampel:

- 🟢 **Grün** – in Ordnung.
- 🟡 **Gelb** – Hinweis: lohnt sich anzuschauen, kein Eilfall.
- 🔴 **Rot** – deutliche Abweichung, sollte geklärt werden.
- 🔵 **Blau** – nur zur Information, kein Urteil.
- ⚪ **Grau** – noch nicht bewertbar (zu wenig Daten oder ein Messwert fehlt).

Zu jeder gelben oder roten Prüfung zeigt die Karte, **wer** etwas tun kann (Sie selbst oder der Fachbetrieb), **was**
zu tun ist und **welcher Wert** am Gerät eingestellt werden sollte. Hinter jeder Prüfung steht ein **„?“** mit einer
Erklärung in einfachen Worten: was gemessen wird, ab wann es gelb oder rot wird und woher diese Grenze stammt.

Die Grenzwerte stammen, wo immer möglich, aus veröffentlichten Messungen – vor allem aus dem Feldtest
**WP-QS des Fraunhofer ISE** (Monatswerte von über 20 Luft-Wasser-Wärmepumpen in Bestandsgebäuden) und aus Normen
und Herstellerangaben.

## Was wird genau geprüft?

### Audit 0 – Datenbasis: Kann man den Messwerten trauen?

Bevor man eine Wärmepumpe beurteilt, muss klar sein, ob die Zahlen stimmen. Dieses Audit bewertet nicht die
Wärmepumpe, sondern die Messung. Aus D2, D4 und D8 entsteht die **Datenqualität** (hoch / mittel / niedrig), die bei
allen anderen Audits mit angezeigt wird.

| Prüfung | Was wird geprüft? |
|---|---|
| D1 Rohdatentiefe | Wie viele Tage Messwerte vorliegen. Grün ab 30 Tagen oder mit Langzeitspeicher (InfluxDB). |
| D2 Abdeckung | Ob die Messwerte lückenlos kamen. Grün ab 98 % der Zeit. |
| D3 Auflösung | In welchen Schritten Temperaturen und Durchfluss gemeldet werden (nur Info). |
| D4 Fühler-Offset | Vor- und Rücklauffühler im Vergleich, wenn nur die Pumpe läuft – dann müssten beide gleich viel zeigen. |
| D5 Zähler gegen Steuerung | Stromverbrauch laut Wärmepumpen-Steuerung im Vergleich zum echten Stromzähler. |
| D6 Tageswechsel der Steuerung | Ob die Uhr der Wärmepumpe richtig geht (häufig nach der Zeitumstellung nicht). |
| D8 Zählerauflösung | Ob der Stromzähler genau genug meldet (0,1 kWh oder feiner). |
| D9 Neustarts | Wie oft die Datenschnittstelle neu gestartet ist. |
| D10 Außenfühler | Außenfühler der Wärmepumpe im Vergleich zum Wetterdienst. Ein falscher Außenfühler verstellt die ganze Heizkurve. |

### Audit 1 – Effizienz: Wie gut arbeitet die Wärmepumpe?

| Prüfung | Was wird geprüft? |
|---|---|
| E1 Arbeitszahl Tag | Erzeugte Wärme geteilt durch Strom, für den letzten vollen Tag (nur Info – hängt stark vom Wetter ab). |
| E2 Arbeitszahl Woche | Dasselbe für die letzten 7 Tage, daneben der Mittelwert aus dem Feldtest bei ähnlichem Wetter (nur Info). |
| **E3 Gütegrad** | **Die eigentliche Note:** Wie nah kommt die Wärmepumpe an das physikalisch Mögliche heran? Wetter und Vorlauftemperatur sind herausgerechnet. Grün im Bereich guter Anlagen aus dem Feldtest. |
| E4 Warmwasser-Anteil | Wie viel der Wärme ins Warmwasser geht (nur Info). |

Der Strom kommt dabei **immer vom Stromzähler**, nie aus einer Schätzung der Wärmepumpe. Die Wärme berechnet das Audit
selbst aus Durchfluss und Temperaturen – einmal „roh“ und einmal um den Fühlerfehler aus D4 korrigiert. Bewertet wird
mit dem vorsichtigeren Wert.

### Audit 2 – Vorlauf: Heizt sie wärmer als nötig?

Jedes Grad weniger Vorlauftemperatur spart etwa 2–3 % Strom. Dieses Audit sucht, wo Temperatur verloren geht.

| Prüfung | Was wird geprüft? |
|---|---|
| T1 Pufferverlust | Wie viel Temperatur zwischen Wärmepumpe und Heizkörpern verloren geht, wenn ein Pufferspeicher oder eine Weiche dazwischen sitzt. |
| T2 Fühlerabgleich | Ob die Fühler vor und hinter dem Puffer gleich messen – sonst ist T1 unsicher. |
| T3 Volumenstrom | Ob die Heizkreispumpe mehr Wasser bewegt als die Wärmepumpe (häufigste Ursache für T1). |
| T4 Spreizung und Durchfluss | Temperaturunterschied Vor-/Rücklauf und Durchfluss im Vergleich zur Herstellerangabe. |
| T5 Ist gegen Soll | Wie weit der tatsächliche Vorlauf über dem Sollwert der Heizkurve liegt (nur Info). |
| T6 Reserve der Heizkurve | Ob die Räume dauerhaft wärmer sind als gewünscht – dann kann die Heizkurve tiefer. Braucht ein Raumthermometer; ein Tag zählt erst, wenn es fast den ganzen Tag gemessen hat (der Einbautag zählt also meist nicht). |

### Audit 3 – Leistung: Passt die Wärmepumpe zum Haus?

Eine zu große oder ungünstig eingestellte Wärmepumpe schaltet ständig ein und aus. Das kostet Effizienz und
Lebensdauer.

| Prüfung | Was wird geprüft? |
|---|---|
| C1 Starts pro Jahr | Verdichterstarts, hochgerechnet aufs Jahr. Grün bis 2.000. |
| C2 Starts pro Stunde | Die meisten Starts innerhalb einer Stunde. Grün bis 6. |
| C3 Kurze Zyklen | Wie viele Heizläufe kürzer als 10 Minuten sind; gelb, wenn an mindestens zwei Tagen Läufe unter 3 Minuten vorkommen. |
| C4 Last gegen Mindestleistung | Ob der Wärmebedarf unter der kleinsten Leistung der Wärmepumpe liegt – dann ist Takten unvermeidbar (nur Info). |
| C5 Heizstab-Anteil | Wie viel Strom der elektrische Heizstab verbraucht. Grün bis 2 %. |
| C6 Abtauung | Wie oft das Außengerät abtaut; gelb, wenn es auch bei über +5 °C außen mehr als zweimal pro Laufstunde abtaut. |
| C7 Modulation | Wie viel der Laufzeit die Wärmepumpe mit kleiner Leistung arbeitet (nur Info). |

### Wann gibt es ein Ergebnis?

Viele Prüfungen brauchen Zeit: eine Woche für die Effizienz, 14 Tage für die Starts pro Jahr, 20 Messfenster für
einen belastbaren Fühlervergleich. Oben in der Karte zeigt ein Balken je Audit, **wie viele Daten schon da sind und an
welchem Tag das Audit voraussichtlich fertig ist**.

### Ereignisse: „Ich habe etwas verstellt“

Wenn an der Anlage etwas geändert wird – Heizkurve, Pumpenstufe, Heizkörperventile, hydraulischer Abgleich –, trägt
man das als **Ereignis** ein. Die Audits Effizienz, Vorlauf und Leistung rechnen dann ab diesem Zeitpunkt neu, damit
nie „vorher“ und „nachher“ vermischt werden. So sieht man schwarz auf weiß, ob die Änderung etwas gebracht hat.

### Zeitstrahl

Eine zweite Karte zeigt je Tag einen Wert pro Audit (Gütegrad, Pufferverlust, Starts pro Tag, Datenabdeckung) mit
denselben Ampelgrenzen, dazu die Ereignisse als senkrechte Linien. Die Tageswerte speichert die Integration selbst,
sie bleiben also auch erhalten, wenn Home Assistant die alten Rohdaten löscht.

## Was brauche ich?

1. **Home Assistant** ab Version **2026.10**.
2. **Eine Luft-Wasser-Wärmepumpe, deren Messwerte in Home Assistant ankommen.** Wie das geht, hängt vom Hersteller
   ab. Entwickelt und getestet wurde mit einer **Mitsubishi Ecodan** und der Schnittstelle
   [Mahtanar](https://github.com/tinwer-group/mahtanar) mit der ESPHome-Firmware
   [esphome-ecodan-hp](https://github.com/gekkekoe/esphome-ecodan-hp). Jede andere
   Wärmepumpe geht auch, sofern die Werte unten als Entitäten in Home Assistant vorhanden sind. Wie diese Anlage
   aufgebaut und eingerichtet ist, steht im Beispiel
   [Mitsubishi Ecodan mit Mahtanar](docs/examples/mitsubishi_ecodan_mahtanar.md).
3. **Ein eigener Stromzähler für die Wärmepumpe**, dessen Zählerstand (kWh) in Home Assistant ankommt – z. B. über
   einen Infrarot-Lesekopf am Zähler. Schätzungen der Wärmepumpe selbst reichen nicht für ein Urteil.
4. Empfohlen: **InfluxDB** als Langzeitspeicher (Home-Assistant-Integration „InfluxDB“, Version 2). Ohne InfluxDB nutzt
   das Audit die normale Aufzeichnung von Home Assistant, die standardmäßig nur 10 Tage zurückreicht.
5. Optional: **ein Raumthermometer** im wichtigsten Raum (für T6).

### Welche Messwerte werden genutzt?

Bei der Einrichtung ordnen Sie jedem Messwert eine vorhandene Entität zu. **Jedes Feld ist freiwillig.** Fehlt ein
Wert, zeigen nur die Prüfungen, die ihn brauchen, „nicht bewertbar“ – alles andere läuft trotzdem.

| Messwert | Wofür | Wichtig? |
|---|---|---|
| Verdichter läuft (an/aus) | Starts, Laufzeiten, fast alle Prüfungen | **sehr wichtig** |
| Stromzähler Wärmepumpe (kWh) | Effizienz, Heizstab-Anteil | **sehr wichtig** |
| Vorlauf- und Rücklauftemperatur | Wärme, Fühlervergleich | **sehr wichtig** |
| Durchfluss (l/min) | Wärme | **sehr wichtig** |
| Außentemperatur der Wärmepumpe | Gütegrad, Außenfühler | **sehr wichtig** |
| Lebenszeichen der Schnittstelle (z. B. Betriebszeit) | erkennt Lücken und Neustarts | wichtig |
| Abtauung aktiv, Warmwasserbetrieb (3-Wege-Ventil) | trennt Heizen, Warmwasser und Abtauen | wichtig |
| Primärpumpe läuft | Fühlervergleich D4 | wichtig |
| Verdichterfrequenz | Modulation C7 | nützlich |
| Heizstab, Zusatzheizung 1 und 2 | Heizstab-Anteil C5 | nützlich |
| Wetterdienst (z. B. `weather.home`) | Vergleich Außenfühler D10 | nützlich |
| Stromverbrauch und Datum laut Steuerung | Plausibilität D5, D6 | nützlich |
| Soll-Vorlauf, Vor-/Rücklauf hinter Puffer, Heizkreispumpe | Audit Vorlauf (nur mit Puffer oder Weiche) | je nach Anlage |
| Raumtemperatur | Reserve der Heizkurve T6 | nützlich |
| Einstellbare Werte der Schnittstelle (Pumpenstufe, Heizkurve, Taktsperre) | konkrete Vorschläge in der Spalte „Aktion“ | optional |

## Installation – Schritt für Schritt

Es gibt zwei Wege. **Weg A (HACS)** ist der einfachere, wenn HACS schon installiert ist. Sonst **Weg B** (Dateien von
Hand kopieren).

### Weg A: über HACS

HACS ist ein „App-Store“ für Erweiterungen von Home Assistant. Falls noch nicht vorhanden:
[Anleitung zur HACS-Installation](https://hacs.xyz/docs/use/).

1. In Home Assistant links auf **HACS** klicken.
2. Oben rechts auf die **drei Punkte ⋮** → **Benutzerdefinierte Repositories**.
3. Bei *Repository* eintragen: `https://github.com/NuckNuck/air-water-heatpump-audit`
   Bei *Typ*: **Integration** wählen → **Hinzufügen**.
4. In HACS nach **Luft-Wasser-Wärmepumpen-Audit** suchen, anklicken → unten rechts **Herunterladen** → nochmal **Herunterladen**.
5. **Home Assistant neu starten:** Einstellungen → oben rechts ⋮ → **Home Assistant neu starten** → **Neu starten**.
   Etwa eine Minute warten.

Weiter mit [Einrichten](#einrichten).

### Weg B: Dateien von Hand kopieren

1. Auf dieser Seite oben auf den grünen Knopf **Code** → **Download ZIP**. Die ZIP-Datei auf dem Computer entpacken.
2. In Home Assistant das Add-on **Samba share** oder **File editor** installieren (Einstellungen → Add-ons →
   Add-on-Store), damit man an die Dateien von Home Assistant kommt.
3. Im Ordner `config` von Home Assistant einen Ordner `custom_components` anlegen, falls es ihn noch nicht gibt.
4. Aus der entpackten ZIP-Datei den Ordner `custom_components/air_water_heatpump_audit` **komplett** dorthin kopieren.
   Danach muss es `config/custom_components/air_water_heatpump_audit/manifest.json` geben.
5. **Home Assistant neu starten** (Einstellungen → ⋮ → Home Assistant neu starten).

### Einrichten

1. **Einstellungen** → **Geräte & Dienste** → unten rechts **Integration hinzufügen**.
2. Nach **Luft-Wasser-Wärmepumpen-Audit** suchen und anklicken.
3. **Profile und Audits:**
   - *Schnittstelle zur Wärmepumpe:* Gibt es Ihre Schnittstelle in der Liste (z. B. Mitsubishi Ecodan mit ESPHome),
     wählen Sie sie aus – dann sind die folgenden Felder schon ausgefüllt (beim Ecodan-Profil für deutsche und
     englische Labels der Firmware). Sonst **Keins**.
   - *Modell der Wärmepumpe:* liefert Werte aus dem Datenblatt. Steht Ihr Modell nicht drin: **Keins**.
   - *Audits:* Haken bei den Audits, die laufen sollen. **Datenbasis** ist empfohlen – sie zeigt, wie belastbar die
     anderen Urteile sind. Weitere Audits lassen sich später jederzeit zuschalten.
4. Nun kommen fünf Seiten, auf denen Sie die Messwerte zuordnen (siehe Tabelle oben). In jedem Feld kann man tippen,
   um die passende Entität zu suchen, z. B. „vorlauf“ oder „flow“. Was es bei Ihrer Anlage nicht gibt, **leer
   lassen**.
   - **Betriebssignale:** Verdichter, Pumpe, Abtauen, Warmwasser, Heizstab, Lebenszeichen.
   - **Messwerte:** Stromzähler, Vor- und Rücklauf, Durchfluss, Außentemperatur, Wetterdienst.
   - **Werte der Steuerung:** Stromverbrauch und Datum, wie die Wärmepumpe sie selbst meldet.
   - **Heizkreis und Raum:** nur ausfüllen, wenn zwischen Wärmepumpe und Heizkörpern ein Pufferspeicher oder eine
     hydraulische Weiche sitzt, und für den Raumthermometer.
   - **Stellgrößen:** nur, wenn Ihre Schnittstelle diese Werte verstellen kann. Das Audit ändert **nie** selbst etwas.
5. **Absenden.** Die Integration rechnet einmal pro Stunde und direkt nach jedem Neustart.

Später ändern:

- **Audit zuschalten:** Einstellungen → Geräte & Dienste → Luft-Wasser-Wärmepumpen-Audit → **Audit hinzufügen**.
- **Audit abschalten:** auf derselben Seite beim Eintrag des Audits (z. B. „Audit: Leistung“) ⋮ → **Löschen**. Seine
  Anzeigen verschwinden mit.
- **Messwerte anders zuordnen:** beim Haupteintrag ⋮ → **Neu konfigurieren**.

**Umstieg von „WP-Audit“:** Wer die Vorgängerin (interner Name `heatpump_audit`) noch eingerichtet hat, bekommt beim
Einrichten die Wahl **Aus WP-Audit übernehmen**. Übernommen werden die Zuordnung der Messwerte, die Anlagendaten, die
Ereignisse und die gespeicherten Tageswerte des Zeitstrahls; alle Audits werden zugeschaltet. Danach den alten Eintrag
„WP-Audit“ löschen.

### Anlagendaten ergänzen (empfohlen)

Manches lässt sich nicht messen, sondern steht im Datenblatt. Ohne diese Angaben zeigen einzelne Prüfungen „nicht
bewertbar – Stammdaten fehlen“.

**Einstellungen → Geräte & Dienste → Luft-Wasser-Wärmepumpen-Audit → Zahnrad ⚙ (Konfigurieren):**

- **Anlage:** Art der Verbindung zwischen Wärmepumpe und Heizkreis (direkt, Pufferspeicher, Weiche), Mindestdurchfluss
  der Wärmepumpe, größter Förderstrom der Heizkreispumpe, kleinste Heizleistung laut Datenblatt, Leistung von
  Heizstab und Zusatzheizung (alles aus Datenblatt oder Installationshandbuch – im Zweifel den Installateur fragen).
- **Standort und Komfort:** Heizstunden pro Jahr am Wohnort (aus der Klimakarte des Bundesverbands Wärmepumpe) und die
  gewünschte Raumtemperatur.
- **Auswertung:** wie viele Tage zurück gerechnet wird, ab wann Daten gelten (z. B. ab Einbau der Schnittstelle) und
  ob InfluxDB oder die normale Aufzeichnung genutzt wird („auto“ wählt selbst).

### Karte auf dem Dashboard anzeigen

Die Karten liefert die Integration mit und meldet sie selbst bei Home Assistant an – es ist nichts zu installieren.

1. Nach der Einrichtung einmal den Browser neu laden (Taste **F5**; in der Handy-App: Einstellungen der App →
   Companion App → Debugging → Frontend-Cache zurücksetzen).
2. Gewünschtes Dashboard öffnen → oben rechts ✏ **Bearbeiten** → **Karte hinzufügen** → ganz unten **Manuell** und
   Folgendes einfügen:

```yaml
type: vertical-stack
cards:
  - type: custom:air-water-heatpump-audit-card
  - type: custom:air-water-heatpump-audit-timeline-card
```

3. **Speichern.** Die erste Karte zeigt alle zugeschalteten Audits, die zweite den Zeitstrahl. Tipp: Die Tabelle ist
   breit. Am besten wirkt sie in einer eigenen Ansicht mit dem Ansichtstyp **Panel (eine Karte)**.

Nur bestimmte Audits zeigen: bei der ersten Karte eine Liste angeben, z. B.

```yaml
type: custom:air-water-heatpump-audit-card
entities:
  - sensor.air_water_heatpump_audit_efficiency
  - sensor.air_water_heatpump_audit_capacity
```

### Ereignis eintragen

Nach jeder Änderung an der Anlage:

- in der **Zeitstrahl-Karte** auf **Ereignis hinzufügen** (nur für Administratoren sichtbar), oder
- **Einstellungen → Geräte & Dienste → Luft-Wasser-Wärmepumpen-Audit → Ereignis hinzufügen.**

Zeitpunkt, Art (z. B. „Heizkurve geändert“) und eine kurze Notiz eintragen. Ändern und löschen geht auf derselben Seite.

## Häufige Fragen

**Ändert die Integration etwas an meiner Wärmepumpe?**
Nein. Sie liest nur Messwerte und erzeugt eigene Anzeige-Sensoren. Vorschläge in der Spalte „Aktion“ setzt man selbst
um – oder lässt sie vom Fachbetrieb umsetzen.

**Fast alles ist grau.**
Normal in den ersten Tagen. Der Balken oben in der Karte zeigt, wann welches Audit fertig ist. Bleibt eine Prüfung
dauerhaft grau, steht in der Erläuterung, welcher Messwert oder welche Anlagenangabe fehlt.

**Die Karte zeigt „Custom element doesn't exist“.**
Der Browser hat noch die alte Seite im Speicher: Seite neu laden (F5). Hilft das nicht und Lovelace läuft im
YAML-Modus, die Ressource von Hand eintragen: URL `/air_water_heatpump_audit/air-water-heatpump-audit-card.js`, Typ
JavaScript-Modul.

**Gelb heißt kaputt?**
Nein. Gelb heißt: Hier lässt sich vermutlich etwas verbessern. Die Erklärung hinter dem „?“ sagt, warum.

**Funktioniert das auch mit einer Sole- oder Wasser-Wärmepumpe?**
Noch nicht. Der Gütegrad (E3) rechnet mit der Außenluft als Wärmequelle, Abtauen (C6) gibt es nur bei
Luft-Wasser-Wärmepumpen.

**Wie entferne ich die Integration?**
Einstellungen → Geräte & Dienste → Luft-Wasser-Wärmepumpen-Audit → ⋮ → **Löschen**, danach in HACS entfernen (bzw.
den Ordner `custom_components/air_water_heatpump_audit` löschen) und die Ressource unter Dashboards → Ressourcen
entfernen.

## Für Entwickler

- `custom_components/air_water_heatpump_audit/` – Integration: Datenquelle (Recorder oder InfluxDB 2 über die
  vorhandene InfluxDB-Integration) → zugeschaltete Audits → Ergebnis-Sensoren und Lovelace-Karten.
  - `audit_core/` – alle Prüfungen als reines Python ohne Abhängigkeiten und ohne Herstellerbezug; kennt die Anlage
    nur über Rollen und Stammdaten. `audit_core` im Projektroot ist ein Symlink darauf.
    - `audits/` – ein Modul je Audit (`AUDIT = AuditSpec(...)`: Rollen, Stammdaten, Prüfungen, Zeitstrahl),
      `registry.py` die Schnittstelle, `context.py` die gemeinsamen Grundgrößen (Fühler-Offset, Wärme, Zyklen,
      Datenqualität), `runner.py` rechnet die zugeschalteten Audits. Neues Audit: Modul anlegen, in
      `audits/__init__.py` eintragen, Texte in `translations/*.json`, `help.py` und `actions.py` ergänzen.
  - `profiles.py` – Vorschläge für bekannte Schnittstellen und Modelle (außerhalb des Kerns). Je Schnittstelle eine
    Grundform und weitere Schreibweisen (`INTERFACE_VARIANTS`, z. B. je Sprache der Firmware-Labels); der Config
    Flow schlägt die erste vor, die es in der Instanz gibt.
  - `frontend/air-water-heatpump-audit-card.js` – `custom:air-water-heatpump-audit-card` (Ampel, Datenreife,
    Tabelle) und `custom:air-water-heatpump-audit-timeline-card` (Zeitstrahl); die Integration trägt die Datei selbst
    als Lovelace-Ressource ein.
- Einträge: Haupteintrag = Anlage (Rollen, Stammdaten), Untereinträge `audit` (je zugeschaltetem Audit, mit eigenem
  Gerät) und `event` (Änderungen an der Anlage).
- Sensoren: `sensor.air_water_heatpump_audit_<audit>` (Gesamturteil, Attribute `dq`, `checks`, `readiness`,
  `audit_name`, `color`), `sensor.air_water_heatpump_audit_<id>_<key>` je Prüfung (Zustand = Urteil, Attribute
  `value`, `unit`, `text`, `origin`, `details`, `progress`, `help`, `action`),
  `sensor.air_water_heatpump_audit_timeline` (Tageswerte, Skalen, zugeschaltete Audits, Ereignisse).
- `prototype/` – Kommandozeilen-Bericht direkt aus InfluxDB:
  `python3 -m prototype.run_audit [START] [ENDE] [--site prototype/site.json]`; Vorlage
  `prototype/site.example.json`, Verbindung über `HEATPUMP_AUDIT_INFLUX_URL` und `HEATPUMP_AUDIT_CREDENTIALS`.
- Tests: `python3 -m unittest` (Kern, inkl. Vergleichsbericht `tests/golden/` einer synthetischen Anlage),
  `pytest tests_ha` in einer venv mit `pytest-homeassistant-custom-component` (Integration).
- Texte: Zahlen mit `audit_core.result.num()` (Dezimalkomma), Anzahlen mit `count(n, Einzahl, Mehrzahl)`. In
  `strings.json`/`translations/*.json` sind `{…}` Platzhalter – jede Sprache braucht genau die des englischen Texts
  (Test `test_translation_placeholders_match_english`), Beispiele mit Klammern also nicht in diese Dateien.
- Fachliche Grundlage (Rollen, Stammdaten, jede Prüfung mit Gate, Schwellen und Quellen):
  [`docs/specification.md`](docs/specification.md).
- Aufbau und Entscheidungen: [`docs/audit_modules_design.md`](docs/audit_modules_design.md).

## Lizenz

[MIT](LICENSE). Kurz: Sie dürfen die Integration frei nutzen, ändern und weitergeben, auch kommerziell. Einzige Pflicht: Der Lizenztext und der Copyright-Vermerk bleiben erhalten. Es gibt keine Gewährleistung und keine Haftung.
