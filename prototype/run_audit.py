"""Prototyp: rechnet Audit 0 und Audit 3 für einen Zeitraum aus InfluxDB und schreibt einen Bericht.

Aufruf: python3 -m prototype.run_audit [START] [ENDE] [--out VERZEICHNIS]
START/ENDE als ISO-Zeit in Ortszeit (z. B. 2026-10-24T15:46); Standard: Einbau Mahtanar bis jetzt.
Ändert nichts an Home Assistant, liest nur.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from audit_core.profiles import HEATING_HOURS_EXAMPLE_SITE, PUD_SHWM140_MIN_CAPACITY_KW
from audit_core.result import num
from audit_core.runner import run_audits

from .influx_source import InfluxSource

TZ = ZoneInfo("Europe/Berlin")
DEFAULT_START = "2026-10-24T15:46"

# Rollen → Entitäten der Mahtanar-Anlage (Spezifikation 1.3)
ROLES = {
    "electricity_meter": ("sensor.wp_zaehler_bezug", "value"),
    "compressor_running": ("binary_sensor.heatpump_compressor", "value"),
    "compressor_frequency": ("sensor.heatpump_compressor_frequency", "value"),
    "flow_temp": ("sensor.heatpump_feed_temp", "value"),
    "return_temp": ("sensor.heatpump_return_temp", "value"),
    "flow_rate": ("sensor.heatpump_flow_rate", "value"),
    "outdoor_temp": ("sensor.heatpump_outside_temp", "value"),
    "pump_running": ("binary_sensor.heatpump_water_pump_status", "value"),
    "defrost": ("binary_sensor.heatpump_defrost", "value"),
    "dhw_active": ("binary_sensor.heatpump_3_way_valve", "value"),
    "immersion_heater": ("binary_sensor.heatpump_immersion_heater", "value"),
    "booster_heater": ("binary_sensor.heatpump_booster_heater", "value"),
    "booster_heater_2": ("binary_sensor.heatpump_booster_heater_2", "value"),
    "heartbeat": ("sensor.heatpump_esp_uptime", "value"),
    "outdoor_temp_reference": ("weather.home", "temperature"),
    "ftc_heating_consumed": ("sensor.heatpump_heating_consumed", "value"),
    "ftc_dhw_consumed": ("sensor.heatpump_dhw_consumed", "value"),
    "ftc_controller_date": ("sensor.heatpump_controller_date", "state"),
    "flow_setpoint": ("sensor.heatpump_zone_1_setpoint_value", "value"),
    "circuit_flow_temp": ("sensor.heatpump_z1_feed_temp", "value"),
    "circuit_return_temp": ("sensor.heatpump_z1_return_temp", "value"),
}
MASTER = {"hydraulic_separation": "parallel_buffer", "flow_rate_min_lpm": 14.3, "room_temp_target": 21.5,
          "capacity_min_table": PUD_SHWM140_MIN_CAPACITY_KW, "heating_hours": HEATING_HOURS_EXAMPLE_SITE}
RECORDER_KEEP_DAYS = 10  # HA-Standard, configuration.yaml hat keinen recorder-Block
INFLUX_SINCE = "2026-10-18T11:02"  # HA schreibt seit dann nach InfluxDB
HEATER_KW = {"immersion_heater": 3.0, "booster_heater": 0.0, "booster_heater_2": 0.0}  # EHPT20X, Tab. 9.5.2

LABEL = {"ok": "🟢 ok", "hint": "🟡 Hinweis", "warn": "🔴 Warnung", "info": "🔵 Info", "not_assessable": "⚪ nicht bewertbar"}


def _value(value) -> str:
    return num(value, ",") if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


def _ts(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=TZ).timestamp()


def _local(t: float) -> str:
    return datetime.fromtimestamp(t, TZ).strftime("%d.%m. %H:%M")


def run(start: float, end: float) -> dict:
    src = InfluxSource()
    series = {role: src.series(eid, start, end, field) for role, (eid, field) in ROLES.items()}
    return run_audits(series, start, end, recorder_keep_days=RECORDER_KEEP_DAYS,
                      long_term_days=(time.time() - _ts(INFLUX_SINCE)) / 86400, heater_kw=HEATER_KW, master=MASTER)


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
    ap.add_argument("start", nargs="?", default=DEFAULT_START)
    ap.add_argument("end", nargs="?")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    start, end = _ts(a.start), (_ts(a.end) if a.end else time.time())
    report = run(start, end)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = datetime.fromtimestamp(end, TZ).strftime("audit_%Y-%m-%d_%H%M")
    (out / f"{stem}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (out / f"{stem}.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))


if __name__ == "__main__":
    main()
