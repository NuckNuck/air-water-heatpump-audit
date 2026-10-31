# Entwurf: Audits als zuschaltbare Module (Weg B, F148/F149)

Stand: 26.10.2026. Kern umgesetzt (Abschnitt „Umsetzung“ am Ende), HA-Teil folgt mit der Umbenennung (F147).

## Ziel

Eine Integration („Luft-Wasser-Wärmepumpen-Audit“, F147) ist das Framework. Die einzelnen Audits sind Module, die der
Nutzer je Anlage zuschaltet. Nur zugeschaltete Audits rechnen, bekommen Entitäten und erscheinen in der Karte. Ein neues
Audit entsteht, indem man ein Modul anlegt und in der Registry einträgt – Runner, Sensor-Plattform, Karte und Config
Flow bleiben unverändert.

Heute (v0.8.1) sind die Audits fachlich schon getrennt (`data_basis.py`, `efficiency.py`, `flow_temp.py`,
`cycles.py`), verdrahtet ist aber alles zentral: `runner.py` ruft jede Prüfung mit fest verdrahteten Argumenten auf,
`ROLE_KEYS`, `CHECKS`, `help.py`, `actions.py`, die Übersetzungen und die Karte (`TL_AUDITS`, Farben, Beschriftungen)
kennen alle Audits einzeln.

## Schichten

```
custom_components/<domain>/
  audit_core/                 reines Python, nur Standardbibliothek, hardwarefrei (F146)
    framework/                series, result, days, readiness, registry, runner, facts
    audits/
      __init__.py             REGISTRY = [data_basis.AUDIT, efficiency.AUDIT, flow_temperature.AUDIT, capacity.AUDIT]
      data_basis/             checks.py, help.py, actions.py, timeline.py, strings.py, __init__.py (AUDIT)
      efficiency/
      flow_temperature/
      capacity/
  sources/                    recorder.py, influx.py (HA-abhängig)
  coordinator.py, sensor.py, config_flow.py, frontend/
```

Die Registry ist eine statische Liste. Dynamisches Nachladen (entry points) bringt nichts, weil HA nur das
Integrationsverzeichnis lädt, und macht Tests und Fehlerbilder unübersichtlicher.

## Gemeinsame Grundgrößen (facts)

Die Audits sind nicht unabhängig; sie teilen Zwischenergebnisse. Diese werden zu benannten, einmal je Lauf
berechneten Grundgrößen. Jede Grundgröße nennt ihre Rollen und die Grundgrößen, die sie braucht. Der Runner rechnet nur,
was die zugeschalteten Audits anfordern (transitiv), jede höchstens einmal.

| fact | heute | Rollen / braucht | genutzt von |
|---|---|---|---|
| `artifacts` | `d0.artifact_windows` | heartbeat | alle |
| `running` | `intervals_where(compressor_running)` | compressor_running | Datenbasis |
| `sensor_offset` | `d0.check_sensor_offset` (D4) | flow/return_temp, compressor_running, pump_running, defrost, dhw_active | D4, `heat_*` |
| `heat_raw`, `heat_corrected` | `heat.heat_power` | flow_rate, flow/return_temp; `sensor_offset` | Effizienz, C4, Zeitstrahl |
| `meter_step` | `check_meter_resolution` (D8) | electricity_meter | D8, E1 |
| `dq` | `data_quality(audit0)` | `coverage`, `sensor_offset`, `meter_step` | E3, alle Audit-Sensoren |
| `cycles` | `c3.detect_cycles` | compressor_running, defrost, dhw_active; `artifacts` | Leistung, Vorlauf, Zeitstrahl |
| `heating_windows` | `t2.heating_windows` | circuit_pump_running; `cycles` | Vorlauf |
| `pause_windows`, `circuit_offset` | `t2.pause_windows`, T2 | circuit_flow_temp; `sensor_offset`-Rollen | T1, T2 |
| `daily_rows` | `e1.daily_rows` | electricity_meter, outdoor_temp; `heat_*`, `carnot_ideal` | Effizienz, Zeitstrahl |
| `dhw_charges` | `w1.detect_charges` | dhw_active, dhw_tank_temp, electricity_meter; `heat_corrected`, `carnot_ideal`, `artifacts` | Warmwasser |
| `dhw_quiet_windows`, `dhw_standby` | `w1.quiet_windows`, `w1.standby_w` | dhw_tank_temp, dhw_active; Stammdatum `dhw_tank_volume_l` | W4, W6 |
| `dhw_draw` | `w1.draw_of` | `dhw_charges`, `dhw_standby`; `cold_water_c` | W2, W4, W6 |
| `persons`, `dhw_dates` | `hh.parse_persons`, `hh.local_dates` | Stammdatum `household` (Untereinträge „Person“) | W5, W6 |
| `day_costs`, `outdoor_daily` | `k1.day_cost` | price_signal, outdoor_temp_reference; `daily_rows` | Kosten |

Grundsatz: **Eine Prüfung, deren Ergebnis andere brauchen (D4, D8, T2), wird als Grundgröße gerechnet; die Prüfung
selbst bewertet nur noch den fertigen Wert.** Damit rechnet z. B. das Effizienz-Audit mit dem Offset, auch wenn das
Datenbasis-Audit abgeschaltet ist.

Grundgrößen hängen vom Abschnitt ab: `window` (ganzes Fenster, z. B. Fühler-Offsets) oder `section` (ab dem letzten
Ereignis). Der Cache-Schlüssel ist `(fact, abschnitt)`; der Zeitstrahl nutzt immer `window`.

## Schnittstelle je Audit

```python
@dataclass(frozen=True)
class CheckSpec:
    check_id: str                  # "E3"
    key: str                       # "carnot_efficiency" → unique_id, translation_key, entity_id
    run: Callable[[Context], CheckResult]
    help: Help                     # was / Bewertung / Grundlage (heute help.py)
    action: ActionFn | None = None # heute actions.py; darf nur Prüfungen desselben Audits lesen (by_id)
    counts_for_verdict: bool = True  # E1, E2, E4: info, zählen nicht

@dataclass(frozen=True)
class TimelineSpec:
    metric: str                    # "carnot_efficiency"
    scale: Callable[[dict], dict]  # Bänder aus denselben Schwellen wie die Prüfung (F100)
    daily_point: Callable[[Context, int], dict]

@dataclass(frozen=True)
class AuditSpec:
    audit_id: str                  # "efficiency"
    order: int                     # Reihenfolge in Karte und Config Flow
    color: str                     # feste Audit-Farbe (Datenreife, Zeitstrahl), keine Ampelfarbe
    section: Literal["window", "section"]   # Datenbasis: window, alle anderen: section
    required_roles: tuple[str, ...]  # ohne sie ist das ganze Audit „nicht bewertbar“
    optional_roles: tuple[str, ...]
    master_keys: tuple[str, ...]   # Stammdaten, die der Options Flow für dieses Audit zeigt
    checks: tuple[CheckSpec, ...]
    timeline: TimelineSpec | None
    strings: dict[str, dict]       # {"de": {...}, "en": {...}} Name, Prüfungsnamen, Kartenbeschriftungen
```

`Context` gibt einer Prüfung Zugriff auf Zeitreihen je Rolle, Grundgrößen (`ctx.fact("cycles")`), Stammdaten,
Abschnitt und Zeitzone. Rollen, die ein Audit nicht angemeldet hat, liefert `Context` nicht aus – so fällt eine
fehlende Anmeldung im Test sofort auf.

Die Registry prüft beim Import (und ein Test zusätzlich): eindeutige `audit_id`/`check_id`/`key`, Grundgrößen
zyklusfrei, jede genutzte Rolle ist in `ROLE_KEYS` des Frameworks bekannt.

## Runner

1. Zugeschaltete Audits aus der Registry holen.
2. Benötigte Rollen und Grundgrößen bestimmen; der Coordinator lädt nur diese Rollen (weniger Recorder-/Influx-Last).
3. Je Audit `checks` ausführen, Datenreife (`progress`), Aktionen und Urteil (`overall` über `counts_for_verdict`).
4. Zeitstrahl: je Audit `daily_point` über das ganze Fenster.

Das Ergebnis behält die heutige Form (`audits.<id>`, `readiness.<id>`, `timeline`), enthält aber nur zugeschaltete
Audits. Ein Golden-Test vergleicht den Bericht vor und nach dem Umbau mit allen vier Audits: identisch bis auf
Reihenfolge.

## HA-Teil

- **Haupteintrag = Anlage:** Rollen und Stammdaten bleiben dort, weil mehrere Audits dieselben Rollen nutzen
  (`flow_temp` brauchen drei von vier). Ereignisse bleiben Untereinträge (`event`).
- **Neuer Untereintragstyp `audit`:** „Audit hinzufügen“ auf der Integrationsseite, je `audit_id` höchstens einmal.
  Der Flow zeigt, welche Pflichtrollen fehlen, und verweist auf „Neu konfigurieren“ des Haupteintrags. Audit-eigene
  Einstellungen (später z. B. abweichende Schwellen) gehören in den Untereintrag.
- **Entitäten je Audit-Untereintrag** (`async_add_entities(..., config_subentry_id=…)`), je Audit ein Gerät. Wird der
  Untereintrag gelöscht, entfernt HA dessen Entitäten selbst; die Tageswerte des Audits im Zeitstrahl-Speicher löscht
  die Integration mit.
- **Config Flow:** Bei der Ersteinrichtung zuerst die Audits auswählen (Vorschlag: alle), danach nur die Rollen-Schritte,
  die die gewählten Audits brauchen; Pflichtrollen markiert.
- **Options Flow:** Abschnitte aus den `master_keys` der zugeschalteten Audits.
- **Übersetzungen:** HA liest nur `translations/<lang>.json` der Integration. Die Texte stehen deshalb in
  `strings` je Audit; ein Skript `scripts/build_translations.py` erzeugt daraus `strings.json` und `translations/*.json`,
  ein Test prüft, dass beide übereinstimmen.
- **Karte:** keine Audit-Liste mehr im JavaScript. Ein Übersichts-Sensor liefert im Attribut `audits` je
  zugeschaltetem Audit `id`, `order`, `color`, Namen und Zeitstrahl-Beschriftungen in der HA-Sprache; Karte und
  Zeitstrahl bauen sich daraus auf.

## Datenbasis-Audit

Durch die Grundgrößen hängt kein anderes Audit mehr am Datenbasis-Audit. Es kann deshalb wie die anderen abschaltbar
sein; `dq` wird trotzdem gerechnet und steht an jedem Audit-Sensor. Vorschlag: bei der Ersteinrichtung vorausgewählt,
mit Hinweis „Empfohlen: zeigt, wie belastbar die anderen Urteile sind“ (F150).

## Reihenfolge mit F146 und F147

1. **F146 Kern hardwarefrei** (im bestehenden Paket): Rollen neutral benennen, Texte D6/D8/D10, Profil und
   Mahtanar-Vorgaben aus dem Kern. Migration des Config-Eintrags auf Version 2 – noch unter `heatpump_audit`, weil das
   der laufende Betrieb braucht.
2. **Kern auf Module umbauen:** `framework/`, Grundgrößen, `audits/`, Registry, Runner. Reiner Kern-Umbau; Prüfstein ist
   der Golden-Test (Bericht identisch). Prototyp `run_audit.py` nutzt denselben Runner (alle Audits).
3. **F147 + HA-Umbau in einem Schritt:** neue Domain `air_water_heatpump_audit` mit Audit-Untereinträgen von Anfang an.
   Eine Domain kann HA nicht migrieren – die neue Integration ist für HA eine andere. Deshalb statt zweier Migrationen
   ein einmaliger Import im Config Flow („Aus WP-Audit übernehmen“): Rollen, Stammdaten, Ereignisse und
   Zeitstrahl-Speicher aus dem alten Eintrag; danach alten Eintrag entfernen, Dashboards und Lovelace-Ressourcen
   (`dashboards.py`, `heatpump_audit_dashboard.py`) und Grafana-Abfragen umstellen.
   Verlauf der Ergebnis-Sensoren: Bei einer neuen Domain entstehen neue Entitäten ohne Verlauf. Wer ihn behalten will:
   alten Eintrag löschen, neue Entitäten kurz unter den alten entity_ids anlegen und dann in der Entitäten-Registry
   umbenennen – HA zieht Verlauf und Statistik bei einer Umbenennung mit. Die Tageswerte des Zeitstrahls kommen
   unabhängig davon über den Import mit.
4. Repo umbenennen, README/Spezifikation anpassen, danach GitHub (F152).

## Tests

- Kern: bestehende 78 Tests laufen weiter, ggf. auf neue Importpfade umgestellt; neu Golden-Test, Registry-Validierung,
  „Audit X allein zugeschaltet“ je Audit (rechnet ohne die anderen und liefert dieselben Urteile).
- HA: venv mit `pytest-homeassistant-custom-component` neu aufsetzen; Tests für Audit-Untereintrag hinzufügen/löschen
  (Entitäten kommen/gehen), Import aus altem Eintrag, Übersetzungen vollständig.

## Offene Fragen

- **F150 (entschieden):** abschaltbar, bei der Einrichtung vorausgewählt mit Empfehlung.
- **F151 (entschieden):** ja.

## Umsetzung Kern (26.10.2026)

- `audit_core/registry.py` (`AuditSpec`, `CheckSpec`, `TimelineSpec`, `validate`), `audit_core/context.py`
  (Laufkontext, Grundgrößen als `cached_property`), `audit_core/audits/` (ein Modul je Audit, `REGISTRY`),
  `runner.run_audits(..., audits=[…])`, `runner.roles_for(...)`.
- Die Prüf-Logik bleibt in `data_basis.py`, `efficiency.py`, `flow_temp.py`, `cycles.py`; die Audit-Module verdrahten
  sie nur. Hilfetexte (`help.py`) und Aktionen (`actions.py`) bleiben vorerst zentral nach `check_id` – ein neues Audit
  trägt dort seine Einträge ein. Übersetzungen: statt Generator ein Test, dass jede Prüfung der Registry in allen
  Sprachdateien steht (HA-Teil).
- Prüfstein: `tests/golden/synthetic_report.json` (synthetische Anlage `tests/synthetic.py`, erzeugt vor dem Umbau) ist
  unverändert; jedes Audit liefert allein und nur mit seinen angemeldeten Rollen dasselbe wie im Gesamtlauf. Mit
  echten InfluxDB-Daten (24.–26.10.) ebenfalls identisch.

## Umsetzung HA-Teil (26.10.2026, Version 0.9.0)

- Neue Domain `air_water_heatpump_audit`, Anzeigename „Luft-Wasser-Wärmepumpen-Audit“ (F147); Config-Eintrag
  Version 1 der neuen Domain. Statt Migration: Menü „Aus WP-Audit übernehmen“, solange es einen Eintrag der Domain
  `heatpump_audit` gibt (Rollen über `migrate_roles`, Optionen, Ereignisse, Zeitstrahl-Speicher beim ersten Laden).
- Einrichtung: Profile und Audits in einem Schritt (Datenbasis empfohlen und vorausgewählt, F150), danach die
  Rollen-Schritte. Untereintrag `audit` („Audit hinzufügen“) warnt bei fehlenden Pflichtrollen und lässt trotzdem zu.
- Ein Gerät je Audit-Untereintrag („Audit: Effizienz“), Zeitstrahl am Haupteintrag; der Coordinator lädt nur Rollen
  der zugeschalteten Audits.
- Karte ohne feste Audit-Liste: Zeitstrahl-Sensor liefert `audits` (Name, Farbe, Reihenfolge, Kennzahl), Audit-Sensor
  `audit_name` und `color`; die Karte ohne `entities` zeigt alle zugeschalteten Audits. Die Integration trägt die
  Karte selbst als Lovelace-Ressource ein (Storage-Modus).
- Abweichung vom Entwurf: Rollen-Schritte zeigen weiterhin alle Rollen (alle optional), nicht nur die der gewählten
  Audits.

## Audits Warmwasser und Kosten (30.10.2026, Version 0.15.0)

- Zwei neue Module nach dem Muster oben: `audits/dhw.py` (W1–W5, Fachlogik `audit_core/dhw.py`) und `audits/cost.py`
  (K1–K5, `audit_core/cost.py`). Runner, Sensoren und Karte blieben unverändert; die Karte bekam nur Texte
  (Zeitstrahl-Hinweise, Tagesdetails, Einheiten `charges` und `nights` der Datenreife).
- Neue Rollen `dhw_tank_temp`, `dhw_setpoint` (Config-Flow-Schritt „Warmwasser“) und `price_signal`, `grid_lock`
  (Schritt „Tarif“); neue Stammdaten im Abschnitt „Kosten“ und `dhw_tank_volume_l`, `heating_degree_days`.
- Der Arbeitspreis wird im Options Flow aus dem Energie-Dashboard vorgeschlagen (`config_flow.energy_price`), wenn dort
  der Zähler der Rolle `electricity_meter` als Netzbezug steht – HA-Wissen bleibt damit außerhalb des Kerns.
- Ereignisse setzten anfangs auch diese Audits zurück (ein gemeinsamer `section_start`). Seit 0.16.0 hat das Audit
  Warmwasser einen eigenen Abschnitt (siehe unten).
- Der Golden-Test vergleicht weiter nur die ersten vier Audits; „Audit allein“ und Registry-Test decken die neuen mit
  ab. Schwellen und Quellen: Spezifikation Abschnitte 6 und 7.

## Haushalt und Abschnitte je Audit (31.10.2026, Version 0.16.0)

- `audit_core/household.py`: Personen mit Anwesenheitsmuster und erwartetem Warmwasserbedarf, ohne HA-Bezug. HA legt
  sie als Untereinträge `person` an; der Coordinator reicht sie als Stammdatum `household` (Liste von dicts) weiter.
- Grundgrößen können andere Grundgrößen nutzen: `dhw_draw` braucht `dhw_standby` (W4); W2 und W4 lesen `dhw_draw` für
  ihre Texte. Das ist der erste Schritt zu Prüfungen, die aufeinander verweisen; Wechselwirkungen mit Euro je Aktion
  folgen als eigenes Vorhaben.
- Abschnitte je Audit: `AuditSpec.section` kennt neben `window` und `section` jetzt `dhw`. `Context` führt dafür
  `dhw_section_start`/`dhw_event` (nur Ereignisse aus `dhw.EVENT_KINDS`); `since()` und `event_of()` lösen den
  Abschnitt eines Audits auf. Der Bericht trägt je Audit das Ereignis (`audits.<id>.event`), Sensor und Karte zeigen
  es je Audit.


## Wirkung und Zielkonflikte (31.10.2026, Version 0.17.0)

- `audit_core/impact.py` läuft im Runner nach `attach_actions` je Audit: `annotate(results, ctx.year_basis)`.
  `YearBasis` (Grundgröße `year_basis` im `Context`) rechnet Jahresstrom, Warmwasser- und Heizstrom, Arbeitszahlen
  und Preis einmal je Lauf.
- Regeln je Prüfung in `_IMPACT` (kWh Strom, positiv = Ersparnis) und feste Sätze in `CONFLICTS`. Eine Regel liest
  nur das eigene Ergebnis und Grundgrößen, nie das Ergebnis eines anderen Audits; so bleibt „Audit allein = Audit im
  Gesamtlauf“ wahr.
- Die Karte sortiert die Ersparnisse über alle gezeigten Audits selbst (`_priorities`); im Bericht gibt es dafür kein
  eigenes Feld.
