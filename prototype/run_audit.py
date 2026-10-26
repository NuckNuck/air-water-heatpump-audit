"""Prototyp: rechnet alle Audits für einen Zeitraum direkt aus InfluxDB und schreibt einen Bericht.

Aufruf: python3 -m prototype.run_audit [START] [ENDE] [--site DATEI] [--out VERZEICHNIS]
START/ENDE als ISO-Zeit in Ortszeit (z. B. 2026-10-24T15:46); Standard: `data_since` der Anlage bis jetzt.
Die Anlage (Rollen → Entitäten, Stammdaten) steht in einer JSON-Datei, Vorlage `prototype/site.example.json`.
Ändert nichts an Home Assistant, liest nur.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from audit_core.result import num
from audit_core.runner import run_audits

from .influx_source import InfluxSource

TZ = ZoneInfo("Europe/Berlin")
DEFAULT_SITE = Path(__file__).with_name("site.json")
_PROFILES = Path(__file__).parents[1] / "custom_components" / "heatpump_audit" / "profiles.py"


def _profiles():
    """profiles.py der Integration ohne das HA-Paket zu importieren (das bräuchte Home Assistant)."""
    spec = importlib.util.spec_from_file_location("profiles", _PROFILES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_site(path: Path) -> dict:
    """Anlage aus JSON. `interface_profile`/`model_profile` füllen Rollen und Stammdaten vor, die Datei gewinnt."""
    site = json.loads(path.read_text(encoding="utf-8"))
    profiles = _profiles()
    roles = profiles.COMMON_ROLE_SUGGESTIONS | profiles.INTERFACE_PROFILES.get(site.get("interface_profile"), {})
    site["roles"] = roles | site.get("roles", {})
    model = profiles.MODEL_PROFILES.get(site.get("model_profile"), {})
    site["master"] = {k: v for k, v in model.items() if k != "immersion_heater_kw"} | site.get("master", {})
    site["heater_kw"] = {"immersion_heater": model.get("immersion_heater_kw")} | site.get("heater_kw", {})
    return site


LABEL = {"ok": "🟢 ok", "hint": "🟡 Hinweis", "warn": "🔴 Warnung", "info": "🔵 Info", "not_assessable": "⚪ nicht bewertbar"}


def _value(value) -> str:
    return num(value, ",") if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


def _ts(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=TZ).timestamp()


def _local(t: float) -> str:
    return datetime.fromtimestamp(t, TZ).strftime("%d.%m. %H:%M")


def _field(entity_id: str) -> str:
    """Spalte in InfluxDB: Wetter liefert die Temperatur als Attribut, Text-Rollen den Zustand."""
    if entity_id.startswith("weather."):
        return "temperature"
    return "state" if entity_id.endswith("_date") else "value"


def run(site: dict, start: float, end: float) -> dict:
    src = InfluxSource()
    series = {role: src.series(eid, start, end, _field(eid)) for role, eid in site["roles"].items() if eid}
    long_term = (time.time() - _ts(site["influx_since"])) / 86400 if site.get("influx_since") else None
    return run_audits(series, start, end, recorder_keep_days=site.get("recorder_keep_days", 10),
                      long_term_days=long_term, heater_kw=site["heater_kw"], master=site["master"])


def markdown(report: dict) -> str:
    p = report["period"]
    lines = [f"# WP-Audit – Prototyp-Bericht", "",
             f"Zeitraum: {_local(p['start'])} – {_local(p['end'])}", ""]
    h = report["heat"]
    lines += [f"Wärme im Zeitraum (Durchfluss × Spreizung): {h['raw_kwh']} kWh roh, {h['corrected_kwh']} kWh mit "
              f"Offset {h['offset_k']:+g} K. Zählerstrom: {h['electricity_kwh']} kWh (ganze kWh).", ""]
    titles = {"data_basis": "Audit 0 – Datenbasis", "efficiency": "Audit 1 – Effizienz gesamt",
              "flow_temperature": "Audit 2 – Vorlauf so niedrig wie möglich",
              "capacity": "Audit 3 – Leistung passt zum Bedarf"}
    for key, audit in report["audits"].items():
        lines += [f"## {titles[key]}: {LABEL[audit['verdict']]} (Datenqualität {audit['dq']})", "", "| ID | Prüfung | Urteil | Wert | Erläuterung | Herkunft |",
                  "|---|---|---|---|---|---|"]
        for r in audit["checks"]:
            value = "" if r["value"] is None or isinstance(r["value"], dict) else f"{_value(r['value'])} {r['unit']}".strip()
            lines.append(f"| {r['check_id']} | `{r['key']}` | {LABEL[r['verdict']]} | {value} | {r['text']} | {r['origin']} |")
        lines.append("")
    lines += ["## Verdichterzyklen", "", "| Start | Ende | Dauer | Pause davor | Klasse | Hinweis |", "|---|---|---|---|---|---|"]
    for c in report["cycles"]:
        note = ", ".join(n for n, f in (("lief schon", c["open_start"]), ("läuft noch", c["open_end"])) if f)
        if c["defrost_stops"]:
            note += f" {c['defrost_stops']} Abtau-Stopp(s)"
        pause = "" if c["pause_before"] is None else f"{num(c['pause_before'] / 60, '.1f')} min"
        lines.append(f"| {_local(c['start'])} | {_local(c['end'])} | {num(c['duration_min'], '.1f')} min | {pause} | {c['kind']} | {note} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("start", nargs="?")
    ap.add_argument("end", nargs="?")
    ap.add_argument("--site", type=Path, default=DEFAULT_SITE)
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    site = load_site(a.site)
    start_text = a.start or site.get("data_since")
    if not start_text:
        ap.error("START fehlt und die Anlagendatei hat kein data_since.")
    start, end = _ts(start_text), (_ts(a.end) if a.end else time.time())
    report = run(site, start, end)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = datetime.fromtimestamp(end, TZ).strftime("audit_%Y-%m-%d_%H%M")
    (out / f"{stem}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (out / f"{stem}.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))


if __name__ == "__main__":
    main()
