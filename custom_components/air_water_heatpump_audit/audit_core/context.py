"""Laufkontext: Zeitreihen je Rolle, Zeitraum, Stammdaten und die gemeinsamen Grundgrößen (facts).

Grundgrößen sind Zwischenergebnisse, die mehrere Audits brauchen (Fühler-Offset, Wärme, Zyklen, Datenqualität …).
Jede wird höchstens einmal je Lauf gerechnet und nur, wenn ein zugeschaltetes Audit sie anfordert. Eine Prüfung,
deren Ergebnis andere brauchen (D2, D4, D8, T2), ist selbst eine Grundgröße; das Audit, zu dem sie gehört, zeigt sie
nur an. So rechnet z. B. die Effizienz mit dem Offset, auch wenn das Datenbasis-Audit abgeschaltet ist.

Zwei Zeiträume: `start` (ganzes Fenster: Fühler, Datenbasis, Zeitstrahl) und `section_start` (ab dem letzten
Ereignis: Verhalten der Anlage, Spezifikation 1.5). Grundgrößen mit `_window` gelten fürs ganze Fenster.
"""

from __future__ import annotations

from functools import cached_property

from . import cost as k1
from . import cycles as c3
from . import data_basis as d0
from . import dhw as w1
from . import days, heat
from . import household as hh
from . import efficiency as e1
from . import flow_temp as t2
from .result import HINT, NOT_ASSESSABLE, OK, CheckResult
from .series import Interval, Series, clip, intervals_where

# Rollen-Keys (Spezifikation 1.3): herstellerneutral; was eine Rolle bedeutet, steht in den Übersetzungen.
ROLE_KEYS = (
    "electricity_meter", "compressor_running", "compressor_frequency", "flow_temp", "return_temp", "flow_rate",
    "outdoor_temp", "outdoor_temp_reference", "pump_running", "defrost", "dhw_active", "immersion_heater",
    "booster_heater", "booster_heater_2", "heartbeat", "controller_heating_consumed", "controller_dhw_consumed",
    "controller_date", "controller_heat_today", "flow_setpoint", "circuit_flow_temp", "circuit_return_temp", "circuit_pump_running",
    "room_temp", "dhw_tank_temp", "dhw_setpoint", "price_signal", "grid_lock",
)
HEATER_ROLES = ("immersion_heater", "booster_heater", "booster_heater_2")


def section_start(events: list[dict], start: float, end: float) -> tuple[float, dict | None]:
    """Beginn des aktuellen Abschnitts: letztes Ereignis im Fenster (Spezifikation 1.5), sonst Fensterbeginn."""
    inside = [e for e in events if start < e["time"] <= end]
    if not inside:
        return start, None
    last = max(inside, key=lambda e: e["time"])
    return last["time"], last


def meter_delta(meter: Series, start: float, end: float) -> float | None:
    values = [float(v) for _, v in clip(meter, start, end)]
    return (values[-1] - values[0]) if len(values) > 1 else None


def data_quality(coverage: CheckResult, offset: CheckResult, meter: CheckResult) -> str:
    """dq nach Spezifikation 2: high, wenn D2, D4, D8 ok; medium bei höchstens einer Abweichung; sonst low.

    Ein nicht bewertbares D4/D8 zählt wie ein hint (Qualität unbekannt, nicht belegt gut).
    """
    verdicts = [r.verdict for r in (coverage, offset, meter)]
    if any(v not in (OK, HINT, NOT_ASSESSABLE) for v in verdicts):
        return "low"
    misses = sum(1 for v in verdicts if v != OK)
    return "high" if misses == 0 else "medium" if misses == 1 else "low"


class Context:
    def __init__(self, s: dict[str, Series], start: float, end: float, *, recorder_keep_days: float | None,
                 long_term_days: float | None, heater_kw: dict[str, float | None], master: dict | None,
                 events: list[dict] | None, controls: dict[str, dict] | None, tz: str) -> None:
        self.s = {k: s.get(k) or [] for k in ROLE_KEYS}
        self.start, self.end = start, end
        self.section_start, self.event = section_start(events or [], start, end)
        self.recorder_keep_days, self.long_term_days = recorder_keep_days, long_term_days
        self.heater_kw = heater_kw
        self.master = master or {}
        self.controls = controls or {}
        self.tz = tz

    def since(self, section: str) -> float:
        return self.start if section == "window" else self.section_start

    # --- Datenbasis -------------------------------------------------------------------------------------------
    @cached_property
    def artifacts(self) -> list[Interval]:
        return d0.artifact_windows(self.s["heartbeat"], self.start, self.end)

    @cached_property
    def running(self) -> list[Interval]:
        return intervals_where(self.s["compressor_running"], lambda v: v in (1, 1.0, True, "on"), self.start,
                               self.end)

    @cached_property
    def coverage(self) -> CheckResult:  # D2
        return d0.check_coverage(self.s["heartbeat"], self.start, self.end)

    @cached_property
    def sensor_offset(self) -> CheckResult:  # D4
        s = self.s
        return d0.check_sensor_offset(s["flow_temp"], s["return_temp"], s["compressor_running"], s["pump_running"],
                                      s["defrost"], s["dhw_active"], self.start, self.end)

    @cached_property
    def meter_resolution(self) -> CheckResult:  # D8
        return d0.check_meter_resolution(self.s["electricity_meter"])

    @cached_property
    def dq(self) -> str:
        return data_quality(self.coverage, self.sensor_offset, self.meter_resolution)

    @cached_property
    def offset_k(self) -> float:
        return self.sensor_offset.value if self.sensor_offset.verdict != NOT_ASSESSABLE else 0.0

    @cached_property
    def offset_robust(self) -> bool:
        return bool(self.sensor_offset.details.get("robust"))

    @cached_property
    def meter_step(self) -> float | None:
        r = self.meter_resolution
        return r.value if r.verdict != NOT_ASSESSABLE else None

    # --- Wärme (Spezifikation 1.1, Grundsatz 2; Entscheid F74) -------------------------------------------------
    @cached_property
    def heat_corrected(self) -> Series:
        s = self.s
        return heat.heat_power(s["flow_rate"], s["flow_temp"], s["return_temp"], self.start, self.end, self.offset_k)

    @cached_property
    def heat_raw(self) -> Series:
        s = self.s
        return heat.heat_power(s["flow_rate"], s["flow_temp"], s["return_temp"], self.start, self.end)

    @cached_property
    def heat_summary(self) -> dict:
        return {"raw_kwh": round(heat.energy_kwh(self.heat_raw, [(self.start, self.end)]), 2),
                "offset_k": self.offset_k, "offset_robust": self.offset_robust,
                "corrected_kwh": round(heat.energy_kwh(self.heat_corrected, [(self.start, self.end)]), 2),
                "electricity_kwh": meter_delta(self.s["electricity_meter"], self.start, self.end)}

    @cached_property
    def carnot_ideal(self) -> Series:
        s = self.s
        return e1.carnot_power(self.heat_corrected, s["flow_temp"], s["return_temp"], s["outdoor_temp"], self.start,
                               self.end)

    def _daily_rows(self, since: float) -> list[dict]:
        s = self.s
        return e1.daily_rows(s["electricity_meter"], self.heat_raw, self.heat_corrected, self.carnot_ideal,
                             s["outdoor_temp"], s["dhw_active"], s["heartbeat"], since, self.end, self.tz,
                             heat_counter=s["controller_heat_today"], outdoor_load=s["outdoor_temp_reference"])

    @cached_property
    def daily_rows(self) -> list[dict]:
        return self._daily_rows(self.section_start)

    @cached_property
    def daily_rows_window(self) -> list[dict]:
        return self.daily_rows if self.section_start <= self.start else self._daily_rows(self.start)

    # --- Zyklen und Heizbetrieb --------------------------------------------------------------------------------
    def _cycles(self, since: float) -> list[c3.Cycle]:
        s = self.s
        return c3.detect_cycles(s["compressor_running"], since, self.end, self.artifacts, s["defrost"],
                                s["dhw_active"])

    @cached_property
    def cycles(self) -> list[c3.Cycle]:
        return self._cycles(self.section_start)

    @cached_property
    def cycles_window(self) -> list[c3.Cycle]:
        return self.cycles if self.section_start <= self.start else self._cycles(self.start)

    @cached_property
    def heating(self) -> tuple[list[Interval], int]:
        """Stationärer Heizbetrieb im Abschnitt und Zahl der beitragenden Zyklen."""
        s = self.s
        return t2.heating_windows(self.cycles, s["defrost"], s["dhw_active"], s["circuit_pump_running"],
                                  self.artifacts, self.section_start, self.end)

    @cached_property
    def pauses(self) -> list[Interval]:
        s = self.s
        return t2.pause_windows(s["compressor_running"], s["pump_running"], s["defrost"], s["dhw_active"],
                                self.start, self.end)

    @cached_property
    def circuit_offset(self) -> CheckResult:  # T2; wie D4 übers ganze Fenster: Ereignisse ändern nicht die Fühler
        return t2.check_circuit_sensor_offset(self.s["flow_temp"], self.s["circuit_flow_temp"], self.pauses,
                                              self.start, self.end)

    # --- Warmwasser (Audit 4) ----------------------------------------------------------------------------------
    def _charges(self, since: float) -> list[w1.Charge]:
        s = self.s
        return w1.detect_charges(s["dhw_active"], s["electricity_meter"], self.heat_corrected, self.carnot_ideal,
                                 s["dhw_tank_temp"], s["flow_temp"], s["return_temp"], s["outdoor_temp"],
                                 s["heartbeat"], self.artifacts, since, self.end)

    @cached_property
    def dhw_charges(self) -> list[w1.Charge]:
        return self._charges(self.section_start)

    @cached_property
    def dhw_charges_window(self) -> list[w1.Charge]:
        return self.dhw_charges if self.section_start <= self.start else self._charges(self.start)

    @cached_property
    def dhw_quiet_windows(self) -> list[tuple[float, float, float, float]]:
        s = self.s
        return w1.quiet_windows(s["dhw_tank_temp"], s["dhw_active"], s["heartbeat"], self.artifacts,
                                self.section_start, self.end, self.tz)

    @cached_property
    def dhw_standby(self) -> tuple[float, float] | None:
        """(Bereitschaftsverlust W, Speichertemperatur) aus W4, None solange zu wenige ruhige Nächte."""
        return w1.standby_w(self.dhw_quiet_windows, self.master.get("dhw_tank_volume_l"))

    @cached_property
    def cold_water_c(self) -> float:
        value = self.master.get("cold_water_c")
        return hh.COLD_WATER_C if value is None else float(value)

    @cached_property
    def dhw_draw(self) -> w1.Draw | None:
        """Zapfmenge im Abschnitt (W6); auch W2 und W4 nutzen sie für ihre Texte."""
        standby = self.dhw_standby
        return w1.draw_of(self.dhw_charges, self.section_start, self.end, self.master.get("dhw_tank_volume_l"),
                          standby[0] if standby else None, self.cold_water_c)

    # --- Haushalt ----------------------------------------------------------------------------------------------
    @cached_property
    def persons(self) -> list[hh.Person]:
        return hh.parse_persons(self.master.get("household"))

    @cached_property
    def section_dates(self) -> list:
        return hh.local_dates(self.section_start, self.end, self.tz)

    # --- Kosten (Audit 5) --------------------------------------------------------------------------------------
    @cached_property
    def day_costs(self) -> dict[str, float | None]:
        """Stromkosten je gültigem Tag (ganzes Fenster): dynamischer Preis, sonst Arbeitspreis aus den Stammdaten."""
        price = self.master.get("tariff_price")
        return {r["day"]: k1.day_cost(r, self.s["electricity_meter"], self.s["price_signal"],
                                      None if price is None else float(price), self.tz)
                for r in self.daily_rows_window}

    @cached_property
    def outdoor_daily(self) -> Series:
        """Außentemperatur für Gradtage: Wetterdienst bevorzugt, Außenfühler wird durch Abtauen verfälscht (D10)."""
        return self.s["outdoor_temp_reference"] or self.s["outdoor_temp"]

    # --- Tage --------------------------------------------------------------------------------------------------
    def full_days(self) -> list[tuple[float, float]]:
        return days.full_days(self.start, self.end, self.tz)
