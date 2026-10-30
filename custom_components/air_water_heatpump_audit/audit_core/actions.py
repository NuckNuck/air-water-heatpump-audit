"""Was der Besitzer bei Gelb oder Rot tun kann: wer handelt, was konkret zu tun ist, welcher Zielwert gilt.

Herstellerneutral formuliert. Nur gelbe und rote Urteile bekommen eine Aktion; grün, info und „nicht bewertbar“
nicht. `who`: `owner` (selbst), `installer` (Fachbetrieb), `none` (nichts zu tun, nur Hinweis zur Messung).
`text` sagt in einem Satz, worum es geht; `steps` sind die einzelnen Handgriffe in Reihenfolge. `target` nennt den
Wert, der am Gerät einzustellen oder zu erreichen ist, mit dem heutigen Wert zum Vergleich.

Stellgrößen (Spezifikation 1.8): Kann die Schnittstelle zur Wärmepumpe einen Wert schreiben, der zur Aktion passt,
ordnet der Besitzer die Entität einer Stellgrößen-Rolle zu (`CONTROL_ROLES`). Die Aktion bekommt dann einen
Vorschlag `controls` mit heutigem und vorgeschlagenem Wert; die Karte bietet ihn Admins zum Übernehmen an. Ohne
Zuordnung bleibt es beim Text. Der Kern schreibt nie selbst.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .result import HINT, WARN, CheckResult, num

OWNER, INSTALLER, NONE = "owner", "installer", "none"

_EVENT_STEP = "Hier im Zeitstrahl „Ereignis hinzufügen“ wählen, damit die Audits ab der Änderung neu rechnen."

_CYCLING_STEPS = [
    "Zuerst den hydraulischen Abgleich machen lassen; er ändert, wie viel Wärme die Heizkörper abnehmen, und damit "
    "das Takten.",
    "Danach mit dem Fachbetrieb die Regelung durchgehen: Schaltdifferenz (Hysterese) größer, Mindestlaufzeit und "
    "Sperrzeit nach dem Abschalten, Vorlauf nicht unnötig niedrig.",
    "Volumenstrom und Puffer prüfen lassen: Ein zu kleiner Wasserinhalt lässt die Wärmepumpe schnell abschalten.",
]


@dataclass
class Action:
    who: str
    text: str
    target: str | None = None
    steps: list[str] | None = None

    def as_dict(self) -> dict:
        out = {"who": self.who, "text": self.text, "target": self.target}
        if self.steps:
            out["steps"] = self.steps
        return out


def _today(r: CheckResult, spec: str = "g") -> str:
    return f" (heute {num(r.value, spec)}{' ' + r.unit if r.unit else ''})" if isinstance(r.value, int | float) else ""


def _carnot(r: CheckResult, _: dict) -> Action:
    if r.value is not None and r.value > 0.5:
        return Action(NONE, "Messung prüfen: Die Wärme scheint zu hoch oder der Strom zu niedrig (siehe Datenbasis). "
                            "An der Anlage ist nichts zu tun.")
    target = f"Gütegrad mindestens {num(0.30, '.2f')}{_today(r, '.2f')}"
    if r.verdict == WARN:
        return Action(INSTALLER, "Anlage mit dem Fachbetrieb durchsehen.", target, [
            "Vorlauftemperatur: Ist die Heizkurve höher als nötig (Audit Vorlauf)?",
            "Durchfluss der Wärmepumpe gegen die Herstellerangabe prüfen, Filter und Schmutzfänger reinigen.",
            "Abtauen und Heizstab: Wie oft und wie lange (Audit Leistung)?"])
    return Action(OWNER, "Die gelben Punkte der anderen Audits angehen, sie bestimmen den Gütegrad.", target, [
        "Zuerst Audit Vorlauf: Jedes Kelvin weniger Vorlauf bringt 2–3 % Effizienz.",
        "Danach Audit Leistung (Takten).",
        "Nach jeder Änderung eine Woche warten, dann diesen Wert erneut ansehen."])


def _sensor_offset(r: CheckResult, _: dict) -> Action:
    if r.verdict == WARN:
        return Action(INSTALLER, "Vorlauf- und Rücklauffühler der Wärmepumpe prüfen lassen.",
                      f"Unterschied höchstens {num(0.5, 'g')} K{_today(r, '+.1f')}",
                      ["Sitz der Fühler am Rohr und Wärmeleitpaste prüfen.",
                       "Fühler mit einem Anlegethermometer vergleichen, bei laufender Pumpe und stehendem Verdichter."])
    return Action(NONE, "Erst beobachten: Der Wert wird mit mehr Pausen genauer. Bleibt er über 1 K, Fühler prüfen.")


def _day_boundary(r: CheckResult, _: dict) -> Action:
    minutes = abs(r.value or 0)
    direction = "vorstellen" if (r.value or 0) > 0 else "zurückstellen"
    return Action(OWNER, "Uhrzeit der Wärmepumpen-Steuerung am Bedienteil stellen (Sommer-/Winterzeit).",
                  f"Uhr um {num(minutes, '.0f')} min {direction}",
                  ["Am Bedienteil der Wärmepumpe das Menü für Datum und Uhrzeit öffnen.",
                   "Uhrzeit auf die aktuelle Ortszeit stellen.",
                   "Am nächsten Tag prüfen, ob dieser Wert grün ist."])


def _buffer_loss(r: CheckResult, by_id: dict) -> Action:
    target = f"Vorlauf-Unterschied höchstens {num(1.5, 'g')} K{_today(r, '.1f')}"
    ratio = by_id.get("T3")
    hp, circuit = (ratio.details.get("heat_pump_lpm"), ratio.details.get("circuit_lpm")) if ratio else (None, None)
    if hp and circuit:
        target = (f"Heizkreis fördert etwa so viel wie die Wärmepumpe: ≈ {num(hp, '.0f')}–{num(hp * 1.3, '.0f')} "
                  f"statt ≈ {num(circuit, '.0f')} l/min; {target}")
    return Action(OWNER, "Die Heizkreispumpe fördert mehr Wasser, als die Wärmepumpe liefert. Sie in kleinen "
                         "Schritten herunterstellen. Kein Eilfall; am besten zusammen mit dem hydraulischen Abgleich.",
                  target, [
                      "Heizkreispumpe finden: die Umwälzpumpe im Rohr vom Puffer (bzw. der Weiche) zu den "
                      "Heizkörpern, nicht die Pumpe in der Wärmepumpe.",
                      "Heutige Einstellung ablesen und notieren (Stufe, Kennlinie oder Leuchtanzeige); Typenschild "
                      "fotografieren.",
                      "Eine Stufe niedriger stellen. Hat die Pumpe Regelarten, die niedrigste Proportionaldruck-"
                      "Kennlinie wählen (oft „Δp-v“ oder „PP1“).",
                      _EVENT_STEP + " Art: „Pumpe verstellt“.",
                      "Zwei bis drei Heiztage beobachten: Werden alle Räume warm und sinkt dieser Wert, bei Bedarf "
                      "noch eine Stufe.",
                      "Wird ein Raum nicht mehr warm: eine Stufe zurück und den hydraulischen Abgleich beim "
                      "Fachbetrieb beauftragen.",
                      "Hat die Pumpe keine Bedienung, weil die Steuerung sie regelt: Fachbetrieb die Pumpenleistung "
                      "des Heizkreises senken lassen."])


def _spread(r: CheckResult, _: dict) -> Action:
    d = r.details
    if d.get("flow_min_lpm") and d.get("flow_lpm") is not None and d["flow_lpm"] < d["flow_min_lpm"]:
        target = f"Durchfluss mindestens {num(d['flow_min_lpm'], 'g')} l/min (heute {num(d['flow_lpm'], '.1f')} l/min)"
    else:
        target = f"Spreizung höchstens {num(10, 'g')} K{_today(r, '.1f')}"
    return Action(INSTALLER, "Durchfluss der Wärmepumpe prüfen lassen.", target, [
        "Filter und Schmutzfänger im Rücklauf zur Wärmepumpe reinigen.",
        "Heizkreis entlüften und Anlagendruck prüfen.",
        "Pumpenstufe der Wärmepumpe prüfen; steht sie schon auf der höchsten Stufe, den Widerstand im Kreis "
        "suchen lassen (Ventile, Rohrquerschnitt)."])


def _curve_headroom(r: CheckResult, by_id: dict) -> Action:
    target = "Parallelverschiebung 1 K niedriger als heute"
    setpoint = by_id.get("T5")
    if setpoint and setpoint.details.get("setpoint_c") is not None:
        s = setpoint.details["setpoint_c"]
        target += f" (Soll-Vorlauf im Mittel ≈ {num(s - 1, '.1f')} statt {num(s, '.1f')} °C)"
    return Action(OWNER, "Die Räume sind wärmer als nötig: Heizkurve um 1 K absenken.", target, [
        "Am Bedienteil der Wärmepumpe die Parallelverschiebung der Heizkurve um 1 K senken.",
        _EVENT_STEP + " Art: „Heizkurve geändert“.",
        "Eine Woche beobachten. Ist es dann noch zu warm, noch einmal 1 K; wird es zu kühl, 1 K zurück."])


def _dhw_temperature(r: CheckResult, _: dict) -> Action:
    if (r.value or 0) > 60:
        return Action(OWNER, "Warmwasser-Solltemperatur senken.", f"Speicher höchstens 60 °C{_today(r, '.0f')}", [
            "Am Bedienteil die Warmwasser-Solltemperatur suchen und auf 55–60 °C stellen.",
            _EVENT_STEP])
    return Action(OWNER, "Warmwasser-Solltemperatur auf mindestens 50 °C stellen.",
                  f"Speicher mindestens 50 °C{_today(r, '.0f')}", [
                      "Am Bedienteil die Warmwasser-Solltemperatur suchen und so einstellen, dass der Speicher nach "
                      "dem Laden mindestens 50 °C zeigt (manche Steuerungen hören 1–2 K unter dem Sollwert auf).",
                      "Gibt es eine Zirkulationsleitung, verlangen die Regeln 60 °C; dann mit dem Fachbetrieb klären.",
                      "Jedes Kelvin mehr kostet etwa 1,4 % Strom beim Warmwasser – Hygiene geht vor.",
                      _EVENT_STEP])


def _fixed(who: str, text: str, target: Callable[[CheckResult], str | None] | None = None,
           steps: list[str] | None = None):
    return lambda r, _: Action(who, text, target(r) if target else None, steps)


_ACTIONS: dict[str, Callable[[CheckResult, dict], Action]] = {
    "D1": _fixed(OWNER, "Langzeitdaten einrichten, sonst fehlen die Vergleiche über Wochen und Monate.", steps=[
        "Am einfachsten: die Integration InfluxDB einrichten (Einstellungen → Geräte & Dienste); das Audit nutzt "
        "sie automatisch.",
        "Alternativ die Recorder-Aufbewahrung erhöhen (`recorder: purge_keep_days: 400` in configuration.yaml), "
        "dann besser auf einer USB-SSD statt auf dem eingebauten Speicher."]),
    "D2": _fixed(OWNER, "Die Schnittstelle an der Wärmepumpe verliert die Verbindung.",
                 lambda r: f"Daten an mindestens 98 % der Zeit{_today(r, '.1f')}", [
                     "WLAN-Signal der Schnittstelle ansehen; besser als −70 dBm ist gut.",
                     "Sonst einen Access Point näher an die Wärmepumpe stellen."]),
    "D3": _fixed(NONE, "An der Anlage ist nichts zu tun; die Messwerte sind nur grob aufgelöst."),
    "D4": _sensor_offset,
    "D5": _fixed(NONE, "Nichts zu tun: Die Auswertungen rechnen mit dem Stromzähler, nicht mit der Schätzung der "
                       "Steuerung."),
    "D6": _day_boundary,
    "D8": _fixed(OWNER, "Der Stromzähler liefert nur ganze kWh. Viele digitale Zähler liefern nach Freischaltung per PIN "
                       "Nachkommastellen.", steps=[
        "PIN beim Messstellenbetreiber anfordern.",
        "PIN am Zähler eingeben (meist per Taste oder Taschenlampe auf das Lichtsymbol).",
        "Im Zählermenü die erweiterte Datenausgabe einschalten (oft „InF“ auf „On“), damit der Lesekopf alle "
        "Werte bekommt."]),
    "D9": _fixed(OWNER, "Die Schnittstelle startet zu oft neu.", steps=[
        "Netzteil prüfen oder tauschen (mindestens 1 A).",
        "WLAN-Signal prüfen.",
        "Im Log der Schnittstelle nach dem Grund der Neustarts sehen."]),
    "D10": _fixed(INSTALLER, "Montageort des Außenfühlers prüfen lassen.",
                  lambda r: f"Abweichung zur Referenz höchstens {num(1.5, 'g')} K{_today(r, '+.1f')}",
                  ["Liegt der Fühler in der Sonne, an der Hauswand oder in der Abluft des Außengeräts? Dann "
                   "an eine schattige Nordseite versetzen lassen."]),
    "C1": _fixed(INSTALLER, "Die Wärmepumpe startet sehr oft.", lambda r: f"unter 5.500 Starts im Jahr{_today(r, ',')}",
                 _CYCLING_STEPS),
    "C2": _fixed(INSTALLER, "Die Wärmepumpe startet in manchen Stunden sehr oft.",
                 lambda r: f"höchstens 6 Starts pro Stunde{_today(r)}", _CYCLING_STEPS),
    "C3": _fixed(INSTALLER, "Einige Heizläufe dauern nur wenige Minuten.",
                 lambda r: f"keine Heizzyklen unter 3 min (heute {r.details.get('very_short', '?')})", _CYCLING_STEPS),
    "C4": _fixed(INSTALLER, "Der Wärmebedarf liegt oft unter der kleinsten Leistung der Wärmepumpe.",
                 steps=_CYCLING_STEPS),
    "C5": _fixed(INSTALLER, "Der Heizstab springt öfter ein als üblich.",
                 lambda r: f"Heizstab höchstens 2 % des Stroms{_today(r, '.1f')}", [
                     "Bivalenzpunkt in der Steuerung prüfen lassen (ab welcher Außentemperatur der Heizstab hilft).",
                     "Legionellenschaltung: Wie oft und wie heiß?",
                     "Sperrzeiten des Netzbetreibers: Muss der Heizstab danach nachheizen?"]),
    "C6": _fixed(INSTALLER, "Die Wärmepumpe taut auffällig oft ab.", steps=[
        "Verdampfer am Außengerät auf Laub, Schmutz oder Eis prüfen.",
        "Kann die kalte Luft frei abströmen (keine Wand oder Hecke direkt davor)?"]),
    "E3": _carnot,
    "W1": _fixed(INSTALLER, "Warmwasserbereitung mit dem Fachbetrieb durchsehen.",
                 lambda r: f"Gütegrad mindestens {num(0.30, '.2f')}{_today(r, '.2f')}", [
                     "Springt beim Warmwasser der Heizstab ein? Dann Speichertemperatur senken (W2).",
                     "Ist die Wärmeübertragerfläche im Speicher groß genug für die Wärmepumpe?",
                     "Durchfluss beim Laden prüfen; zu wenig Durchfluss treibt den Vorlauf hoch."]),
    "W2": _dhw_temperature,
    "W3": _fixed(OWNER, "Die Aufheizung auf 60 °C seltener einstellen, einmal pro Woche reicht.",
                 lambda r: f"höchstens einmal pro Woche{_today(r, '.1f')}", [
                     "Am Bedienteil die Legionellenschaltung suchen (oft „Legionellen“ oder „Antilegionella“).",
                     "Intervall auf 7 Tage stellen und die Uhrzeit auf den Nachmittag legen.",
                     _EVENT_STEP]),
    "W4": _fixed(OWNER, "Der Speicher verliert viel Wärme.", steps=[
        "Sind Anschlüsse und Rohre am Speicher gedämmt? Unisolierte Rohre in den ersten Metern verlieren viel.",
        "Läuft eine Zirkulationspumpe dauernd? Dann eine Zeitschaltung oder einen Taster vorsehen.",
        "Kann warmes Wasser im Rohr nach oben steigen und abkühlen (Schwerkraftzirkulation)? Dann einen "
        "Thermosiphon oder eine Rückschlagklappe einbauen lassen."]),
    "W5": _fixed(OWNER, "Warmwasser zur wärmsten Tageszeit laden.",
                 lambda r: f"Einbuße unter {num(10, 'g')} %{_today(r, '.0f')}", [
                     "Am Bedienteil das Zeitprogramm für Warmwasser öffnen.",
                     "Laden nur zwischen etwa 12 und 17 Uhr erlauben; vorher prüfen, ob der Speicher bis zum Abend "
                     "und zum nächsten Morgen reicht.",
                     _EVENT_STEP]),
    "K1": _fixed(OWNER, "Die Wärme ist teurer als mit dem früheren Brennstoff.", steps=[
        "Zuerst die gelben Punkte der Audits Effizienz, Vorlauf und Leistung angehen.",
        "Strompreis vergleichen: Wärmepumpentarife sind oft günstiger als Haushaltsstrom.",
        "Den Wert über mehrere Wochen ansehen; im Winter ist er höher als im Jahresmittel."]),
    "K3": _fixed(OWNER, "Der eigene Wärmepumpentarif lohnt sich bei diesem Verbrauch nicht.", steps=[
        "Angebote für Wärmepumpenstrom vergleichen.",
        "Sonst mit dem Elektriker klären, ob die Wärmepumpe über den Haushaltszähler laufen kann."]),
    "K4": _fixed(OWNER, "Die Wärmepumpe läuft oft in teuren Stunden.", steps=[
        "Warmwasser in die günstigen Stunden legen (Zeitprogramm).",
        "Wenn die Steuerung es kann: Heizen bei niedrigen Preisen etwas vorziehen (Puffer, Gebäudemasse)."]),
    "K5": _fixed(INSTALLER, "Nach Sperren heizt der Heizstab nach.", steps=[
        "Den Heizstab während und kurz nach einer Sperre blockieren lassen.",
        "Bivalenzpunkt prüfen: Der Heizstab sollte nur bei großer Kälte helfen, nicht nach jeder Sperre.",
        "Puffer und Speicher vor bekannten Sperrzeiten laden."]),
    "T1": _buffer_loss,
    "T2": _fixed(INSTALLER, "Die beiden Vorlauffühler zeigen unterschiedliche Werte.",
                 lambda r: f"Fühlerunterschied höchstens 1 K{_today(r, '+.1f')}",
                 ["Sitz der Fühler am Rohr und Wärmeleitpaste prüfen lassen."]),
    "T4": _spread,
    "T6": _curve_headroom,
}


# ----------------------------------------------------------------------------------------------------------------
# Stellgrößen: Rolle → was sie verstellt, welche Prüfungen sie nutzen und welcher Wert vorgeschlagen wird.

def _clamp(value: float, meta: dict) -> float:
    lo, hi = meta.get("min"), meta.get("max")
    if lo is not None:
        value = max(value, float(lo))
    if hi is not None:
        value = min(value, float(hi))
    return value


def _number(meta: dict) -> float | None:
    try:
        return float(meta.get("state"))
    except (TypeError, ValueError):
        return None


def _one_step_lower(meta: dict):
    """Zahl: eine Schrittweite weniger; Auswahl: die vorige Option (Optionen aufsteigend sortiert)."""
    if meta.get("options"):
        opts = list(meta["options"])
        i = opts.index(meta["state"]) if meta.get("state") in opts else -1
        return opts[i - 1] if i > 0 else None
    current = _number(meta)
    if current is None:
        return None
    step = float(meta.get("step") or 1)
    return _clamp(round(current - step, 6), meta)


def _minus_one_kelvin(meta: dict):
    current = _number(meta)
    return None if current is None else _clamp(round(current - 1.0, 6), meta)


def _at_least(minimum: float):
    """Zahl oder Auswahl mit Zahlen als Text: mindestens `minimum`, sonst unverändert."""
    def propose(meta: dict):
        if meta.get("options"):
            numeric = sorted((float(o), o) for o in meta["options"] if _is_number(o))
            current = float(meta["state"]) if _is_number(meta.get("state")) else None
            if current is not None and current >= minimum:
                return None
            return next((o for v, o in numeric if v >= minimum), None)
        current = _number(meta)
        if current is None or current >= minimum:
            return None
        return _clamp(minimum, meta)
    return propose


def _is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class ControlRole:
    label: str
    checks: tuple[str, ...]
    propose: Callable[[dict], object]
    event_kind: str
    domains: tuple[str, ...] = ("number", "input_number", "select", "input_select")


SHORT_CYCLE_LOCKOUT_MIN = 30  # Sperre nach einem zu kurzen Lauf; halbe Stunde lässt den Puffer sicher auskühlen
SHORT_CYCLE_MIN_RUN_MIN = 5  # kürzere Läufe lösen die Sperre aus; C3 zählt Läufe unter 3 min als sehr kurz

# Reihenfolge = Reihenfolge der Vorschläge in der Karte.
CONTROL_ROLES: dict[str, ControlRole] = {
    "circuit_pump_speed": ControlRole("Stufe der Heizkreispumpe", ("T1",), _one_step_lower, "pump_setting"),
    "heating_curve_shift": ControlRole("Parallelverschiebung der Heizkurve", ("T6",), _minus_one_kelvin,
                                       "heating_curve"),
    "short_cycle_lockout": ControlRole("Sperre nach zu kurzem Heizlauf (min)", ("C3",),
                                       _at_least(SHORT_CYCLE_LOCKOUT_MIN), "other"),
    "short_cycle_min_run": ControlRole("Mindestlaufzeit, kürzere Läufe lösen die Sperre aus (min)", ("C3",),
                                       _at_least(SHORT_CYCLE_MIN_RUN_MIN), "other"),
}


def _proposals(check_id: str, controls: dict[str, dict]) -> list[dict]:
    out = []
    for role, spec in CONTROL_ROLES.items():
        meta = controls.get(role)
        if check_id not in spec.checks or not meta or meta.get("state") in (None, "unknown", "unavailable"):
            continue
        value = spec.propose(meta)
        if value is None or str(value) == str(meta["state"]) or (_is_number(value) and _is_number(meta["state"])
                                                                and float(value) == float(meta["state"])):
            continue
        out.append({"role": role, "label": spec.label, "entity_id": meta["entity_id"],
                    "domain": meta["entity_id"].split(".")[0], "current": meta["state"], "value": value,
                    "unit": meta.get("unit") or "", "event_kind": spec.event_kind})
    return out


def attach_actions(results: list[CheckResult], controls: dict[str, dict] | None = None) -> list[CheckResult]:
    """Setzt `action` für gelbe und rote Prüfungen, sofern eine Aktion hinterlegt ist.

    Zielwerte dürfen auf andere Prüfungen desselben Audits zugreifen (T1 nutzt T3, T6 nutzt T5). `controls`: je
    zugeordneter Stellgrößen-Rolle der heutige Zustand ({entity_id, state, min, max, step, options, unit}).
    """
    by_id = {r.check_id: r for r in results}
    for r in results:
        entry = _ACTIONS.get(r.check_id)
        if r.verdict in (HINT, WARN) and entry is not None:
            r.action = entry(r, by_id).as_dict()
            if proposals := _proposals(r.check_id, controls or {}):
                r.action["controls"] = proposals
    return results
