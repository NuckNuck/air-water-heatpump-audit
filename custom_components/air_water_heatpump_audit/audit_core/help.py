"""Kurzhilfe je Prüfung für das „?“ in der Karte: was gemessen wird, wann grün/gelb/rot, woher die Grenze kommt.

Für Heizungsbesitzer ohne Fachwissen geschrieben (Leitlinie F84: helfen, nicht verwirren). Grenzen kommen aus den
Konstanten der Prüfungen, damit Hilfe und Urteil nie auseinanderlaufen.
"""

from __future__ import annotations

from . import cycles as c3
from . import efficiency as e1
from . import flow_temp as t2
from .result import num


def _k(v: float) -> str:
    return num(v, "g")


INFO_ONLY = "Nur zur Information, kein Urteil."

CHECK_HELP: dict[str, dict[str, str]] = {
    # Audit 0 – Datenbasis
    "D1": {"what": "Wie viele Tage Einzelmesswerte für die Auswertung vorliegen.",
           "rating": "Grün: Langzeitspeicher (InfluxDB) oder mindestens 30 Tage im Recorder. Gelb: 7–29 Tage. "
                     "Rot: unter 7 Tagen.",
           "source": "Abgeleitet: Wochen- und Monatsvergleiche brauchen genug Vorlauf."},
    "D2": {"what": "Anteil der Zeit, in der lückenlos Messwerte kamen (Lücke = mehr als 3 Minuten ohne Lebenszeichen "
                   "des Datensammlers).",
           "rating": "Grün ab 98 %, Gelb ab 90 %, Rot darunter.",
           "source": "Abgeleitet: Ein Tag zählt für die Auswertung nur mit mindestens 98 %."},
    "D3": {"what": "In welchen Schritten Temperaturen und Durchfluss gemeldet werden, und wie stark das die "
                   "berechnete Wärme schwanken lässt.",
           "rating": INFO_ONLY,
           "source": "Physikalisch: grobe Schritte bei kleiner Spreizung machen einzelne Werte ungenau."},
    "D4": {"what": "Vor- und Rücklauffühler im Vergleich, während die Pumpe läuft und der Verdichter steht – dann "
                   "müssten beide dasselbe zeigen. Ein Unterschied verfälscht die berechnete Wärme.",
           "rating": "Grün bis 0,5 K, Gelb bis 1 K, Rot darüber. Belastbar ab 20 Messfenstern, vorher vorläufig.",
           "source": "Abgeleitet aus der üblichen Fühlertoleranz (±0,5–1 K)."},
    "D5": {"what": "Strom laut Steuerung der Wärmepumpe im Vergleich zum Stromzähler über mindestens 7 Tage.",
           "rating": "Grün: Steuerung zeigt das 0,95- bis 1,2-fache des Zählers. Rot unter 0,8 oder über 1,5, "
                     "dazwischen Gelb. Ausgewertet wird immer der Zähler.",
           "source": "Abgeleitet: Hersteller nennen den Wert der Steuerung nur einen Richtwert."},
    "D6": {"what": "Ob die Uhr der Wärmepumpen-Steuerung stimmt: Ihre Tageswerte sollten um Mitternacht wechseln.",
           "rating": "Grün bis 15 Minuten Abweichung, sonst Gelb – meist nach der Zeitumstellung, Uhr am Gerät "
                     "stellen.",
           "source": "Belegt durch das Verhalten der Steuerung (Tageswechsel nach eigener Uhr)."},
    "D8": {"what": "In welchen Schritten der Stromzähler seinen Stand liefert.",
           "rating": "Grün bei 0,1 kWh oder feiner, sonst Gelb: Tageswerte werden dann ungenau.",
           "source": "Physikalisch: 1 kWh Schritt ist bei 10–20 kWh am Tag bis zu 10 % Fehler."},
    "D9": {"what": "Wie oft der Datensammler neu gestartet ist. Messwerte rund um einen Neustart werden verworfen.",
           "rating": "Gelb bei mehr als 3 Neustarts pro Tag, sonst nur Info.",
           "source": "Abgeleitet."},
    "D10": {"what": "Außenfühler der Wärmepumpe im Vergleich zum Wetterdienst (ohne Tage mit viel Abtauen).",
            "rating": "Grün bis 1,5 K Abweichung, Gelb bis 3 K, Rot darüber.",
            "source": "Abgeleitet: Der Außenfühler steuert die Heizkurve."},
    # Audit 1 – Effizienz
    "E1": {"what": "Arbeitszahl des letzten vollen Tages: erzeugte Wärme ÷ Strom vom Zähler.",
           "rating": INFO_ONLY + " Ein Tageswert hängt vor allem vom Wetter ab.",
           "source": "Beschreibend."},
    "E2": {"what": "Arbeitszahl der letzten 7 gültigen Tage, daneben das Mittel aus einem großen Feldtest bei "
                   "ähnlicher Außentemperatur.",
           "rating": INFO_ONLY + " Die Bewertung macht der Gütegrad (E3).",
           "source": "Fraunhofer ISE, Feldtest WP-QS (Monatswerte von 22 Luft/Wasser-Wärmepumpen)."},
    "E3": {"what": "Wie nah die Wärmepumpe an das physikalisch Mögliche bei ihren Temperaturen herankommt. Wetter "
                   "und Vorlauftemperatur sind damit herausgerechnet – das ist die eigentliche Note für die Technik.",
           "rating": f"Grün {_k(e1.CARNOT_OK_MIN)}–{_k(e1.CARNOT_PLAUSIBLE_MAX)} (Feldtest 0,32–0,44). Gelb darunter. "
                     f"Darüber Info: besser als jede Anlage im Feldtest, eher ein Messfehler. Rot unter {_k(e1.CARNOT_WARN_BELOW)}, nur mit "
                     "belastbarem Fühler-Offset. Urteil über eine Woche.",
           "source": "Fraunhofer ISE, Feldtest WP-QS (2025)."},
    "E4": {"what": "Anteil der Wärme, der ins Warmwasser geht.",
           "rating": INFO_ONLY + f" Feldtest-Mittel übers Jahr {e1.FIELD_DHW_SHARE} %, im Winter weniger.",
           "source": "Fraunhofer ISE, Feldtest WP-QS."},
    # Audit 2 – Vorlauf
    "T1": {"what": "Wie viel wärmer die Wärmepumpe heizt, als hinter dem Puffer im Heizkreis ankommt. Jedes Kelvin "
                   "zu viel kostet etwa 2–3 % Effizienz.",
           "rating": f"Grün bis {_k(t2.LOSS_OK_K)} K, Gelb bis {_k(t2.LOSS_HINT_K)} K, Rot darüber – Rot nur, wenn "
                     "die Fühler abgeglichen sind (T2).",
           "source": "Abgeleitet aus der Fühlertoleranz und Messungen des Fraunhofer ISE an Pufferspeichern."},
    "T2": {"what": "Vorlauffühler der Wärmepumpe und des Heizkreises im Vergleich, wenn der Verdichter steht und "
                   "Wasser umläuft – dann sollten beide gleich viel zeigen.",
           "rating": f"Info; Gelb bei mehr als {_k(t2.OFFSET_HINT_K)} K Unterschied (dann ist T1 unsicher). "
                     f"Belastbar ab {t2.ROBUST_PAUSE_WINDOWS} Pausen.",
           "source": "Physikalisch."},
    "T3": {"what": "Wie viel mehr Wasser die Heizkreispumpe bewegt als die Wärmepumpe, berechnet aus den "
                   "Temperaturen am Puffer.",
           "rating": INFO_ONLY + " Erklärt meist den Pufferverlust (T1).",
           "source": "Physikalisch (Mischungsrechnung)."},
    "T4": {"what": "Temperaturunterschied zwischen Vor- und Rücklauf der Wärmepumpe und der Durchfluss im Vergleich "
                   "zur Herstellerangabe.",
           "rating": f"Gelb bei mehr als {_k(t2.SPREAD_HINT_K)} K Unterschied oder wenn der Durchfluss deutlich unter "
                     "dem Minimum des Herstellers liegt (mehr als die Messtoleranz). Kleiner Unterschied ist kein "
                     "Mangel.",
           "source": "VDI 4645, Herstellerdaten, Feldtest Fraunhofer ISE."},
    "T5": {"what": "Vorlauf im Vergleich zum Sollwert der Heizkurve: Auf welchen Fühler regelt die Steuerung, und "
                   "wie viel legt die Wärmepumpe drauf?",
           "rating": INFO_ONLY,
           "source": "Beschreibend."},
    "T6": {"what": "Ob die Räume dauerhaft wärmer sind als gewünscht – dann könnte die Heizkurve tiefer und die "
                   "Wärmepumpe sparsamer laufen.",
           "rating": "Gelb, wenn der Raum an mindestens 5 von 7 Heiztagen 1 K oder mehr über dem Ziel liegt. "
                     "Braucht einen Raumfühler; ein Tag zählt erst, wenn der Fühler seit mindestens 90 % des Tags misst.",
           "source": "Abgeleitet aus der Regelgenauigkeit von Raumreglern (EN 15500)."},
    # Audit 3 – Leistung
    "C1": {"what": "Verdichterstarts, hochgerechnet auf ein Jahr. Viele Starts deuten auf eine zu große oder "
                   "ungünstig eingestellte Wärmepumpe hin.",
           "rating": f"Grün bis {num(c3.STARTS_PER_YEAR_OK, ',')} pro Jahr, darüber Gelb (90 % der Anlagen im "
                     f"Feldtest unter {num(c3.STARTS_PER_YEAR_HINT, ',')}). Höchstens Gelb, weil hochgerechnet. "
                     "Bewertet ab 14 Tagen.",
           "source": "Fraunhofer ISE, Feldtest WP-QS."},
    "C2": {"what": "Die meisten Verdichterstarts innerhalb einer Stunde.",
           "rating": "Grün bis 6, Gelb bis 12, Rot darüber.",
           "source": "Übliche Herstellergrenzen (WP-QS, Danfoss)."},
    "C3": {"what": "Anteil der Heizläufe, die kürzer als 10 Minuten sind.",
           "rating": "Info; Gelb, wenn mindestens 2 Läufe kürzer als 3 Minuten sind. Ab 20 Heizläufen.",
           "source": "Beschreibend."},
    "C4": {"what": "Wärmebedarf des Tages im Vergleich zur kleinsten Leistung der Wärmepumpe laut Datenblatt.",
           "rating": INFO_ONLY + " Liegt der Bedarf darunter, ist Takten physikalisch unvermeidbar.",
           "source": "Physikalisch, Datenblatt des Herstellers."},
    "C5": {"what": "Anteil des Heizstabs (elektrische Zusatzheizung) am Strom.",
           "rating": "Grün bis 2 %, Gelb bis 4 %, Rot darüber (Feldtest im Mittel 1,3–1,9 %). Ab 7 Tagen.",
           "source": "Abgeleitet aus dem Feldtest Fraunhofer ISE."},
    "C6": {"what": "Wie oft die Wärmepumpe pro Stunde Laufzeit abtaut.",
           "rating": INFO_ONLY,
           "source": "Abgeleitet."},
    "C7": {"what": "Wie viel ihrer Laufzeit die Wärmepumpe mit kleiner Leistung (niedrige Drehzahl) arbeitet.",
           "rating": INFO_ONLY + " Viel kleine Leistung ist effizient, solange sie nicht oft taktet.",
           "source": "Beschreibend."},
}
