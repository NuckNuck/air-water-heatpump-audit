"""Laufkontext: Zeitreihen je Rolle, Zeitraum, Stammdaten und die gemeinsamen Grundgrößen (facts).

Grundgrößen sind Zwischenergebnisse, die mehrere Audits brauchen (Fühler-Offset, Wärme, Zyklen, Datenqualität …).
Jede wird höchstens einmal je Lauf gerechnet und nur, wenn ein zugeschaltetes Audit sie anfordert. Eine Prüfung,
deren Ergebnis andere brauchen (D2, D4, D8, T2), ist selbst eine Grundgröße; das Audit, zu dem sie gehört, zeigt sie
nur an. So rechnet z. B. die Effizienz mit dem Offset, auch wenn das Datenbasis-Audit abgeschaltet ist.

Ereignisse sind Markierungen, keine Trenner (Spezifikation 1.5, #39): Alle Audits rechnen über das ganze Fenster,
`section_start` und `dhw_section_start` sind gleich `start`. Gemerkt wird nur das letzte Ereignis (`event`) bzw. das
letzte Warmwasser-Ereignis (`dhw_event`); der Runner vergleicht damit das Urteil von heute mit dem zum Ereigniszeitpunkt.
Die Namen `section_start` und `_window` bleiben, damit die Prüfungen unverändert bleiben.
"""

from __future__ import annotations

from functools import cached_property

from . import cost as k1
from . import cycles as c3
from . import data_basis as d0
from . import dhw as w1
from . import days, heat
from . import household as hh
from . import impact
from . import long_term as lt
from . import efficiency as e1
from . import flow_temp as t2
from . import heating_prices as hp
from .result import HINT, NOT_ASSESSABLE, OK, CheckResult, round_floats
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


def section_start(events: list[dict], start: float, end: float,
                  kinds: tuple[str, ...] | None = None) -> tuple[float, dict | None]:
    """Beginn des aktuellen Abschnitts: letztes Ereignis im Fenster (Spezifikation 1.5), sonst Fensterbeginn.
    kinds: nur Ereignisse dieser Arten zählen; None = alle."""
    inside = [e for e in events if start < e["time"] <= end and (kinds is None or e.get("kind") in kinds)]
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


HOUSEHOLD_PRICE_REF = "master:household_price"  # Vergleichslinie Stromdirektheizung aus den Stammdaten


class Context:
    def __init__(self, s: dict[str, Series], start: float, end: float, *, recorder_keep_days: float | None,
                 long_term_days: float | None, heater_kw: dict[str, float | None], master: dict | None,
                 events: list[dict] | None, controls: dict[str, dict] | None, tz: str,
                 price_refs: list[dict] | None = None, statistics: dict | None = None) -> None:
        self.s = {k: s.get(k) or [] for k in ROLE_KEYS}
        self.start, self.end = start, end
        # Tageswerte der Langzeitstatistik (long_term.py, Spezifikation 1.11); None = keine
        self.statistics = statistics
        # Ereignisse nur merken, nicht ab ihnen rechnen (Spezifikation 1.5, #39)
        _, self.event = section_start(events or [], start, end)
        _, self.dhw_event = section_start(events or [], start, end, w1.EVENT_KINDS)
        self.section_start = self.dhw_section_start = start
        self.recorder_keep_days, self.long_term_days = recorder_keep_days, long_term_days
        self.heater_kw = heater_kw
        self.master = master or {}
        # Preis-Sensoren anderer Heizsysteme ({id, system, unit, name, source, source_kind, as_of, series});
        # None = Vergleich abgeschaltet. Die Angaben ohne Zeitreihe stehen für die Zeitstrahl-Skala in den Stammdaten.
        self.price_refs = None if price_refs is None else [r for r in price_refs if hp.usable(r)]
        household = self.master.get("household_price")
        if self.price_refs is not None and household:
            # Stromdirektheizung (Entscheid F277): Arbeitspreis des Haushaltsstroms, Nutzungsgrad 1, ohne Sensor
            self.price_refs.append({"id": HOUSEHOLD_PRICE_REF, "system": "direct_electric", "unit": "€/kWh",
                                    "name": "Stromdirektheizung (Haushaltsstrom)",
                                    "source": "Stammdaten: Arbeitspreis Haushaltsstrom", "source_kind": "local",
                                    "as_of": None, "series": [(0.0, float(household))]})
        self.controls = controls or {}
        self.tz = tz

    def since(self, section: str) -> float:
        return {"window": self.start, "dhw": self.dhw_section_start}.get(section, self.section_start)

    def event_of(self, section: str) -> dict | None:
        """Das letzte Ereignis, das ein Audit mit diesem Zeitraum betrifft; None = keines (Datenbasis: nie)."""
        return {"window": None, "dhw": self.dhw_event}.get(section, self.event)

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
                "offset_k": round(self.offset_k, 2), "offset_robust": self.offset_robust,
                "corrected_kwh": round(heat.energy_kwh(self.heat_corrected, [(self.start, self.end)]), 2),
                "electricity_kwh": round_floats(meter_delta(self.s["electricity_meter"], self.start, self.end))}

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

    # --- Statistik-Tage (Spezifikation 1.11) -------------------------------------------------------------------
    @cached_property
    def statistic_rows(self) -> list[dict]:
        """Gültige Statistik-Tage vor dem ersten vollen Tag des Fensters (für den Zeitstrahl alle)."""
        first = self.full_days()
        before = days.label(first[0][0], self.tz) if first else days.label(self.end, self.tz)
        return lt.statistic_rows(self.statistics, self.daily_rows_window, before)

    @cached_property
    def statistic_rows_section(self) -> list[dict]:
        """Statistik-Tage für K2, Jahreswärme und Wirkung; seit #39 alle, Ereignisse trennen nicht mehr."""
        return self.statistic_rows

    @cached_property
    def year_rows(self) -> list[dict]:
        """Tage für die Hochrechnung K2 und die Jahreswärme: Statistik-Tage + gültige Tage."""
        return self.statistic_rows_section + self.daily_rows

    @cached_property
    def year_rows_window(self) -> list[dict]:
        """Tage für die Jahreswerte der Wirkung (1.10): Statistik-Tage + ganzes Fenster."""
        return self.statistic_rows_section + self.daily_rows_window

    def timeline_row(self, day: str) -> dict | None:
        """Tageswerte für den Zeitstrahl: gültiger Tag aus Rohdaten, sonst Statistik-Tag."""
        return self._timeline_rows.get(day)

    @cached_property
    def _timeline_rows(self) -> dict[str, dict]:
        return {r["day"]: r for r in self.statistic_rows} | {r["day"]: r for r in self.daily_rows_window}

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
        return self._charges(self.dhw_section_start)

    @cached_property
    def dhw_charges_window(self) -> list[w1.Charge]:
        return self.dhw_charges if self.dhw_section_start <= self.start else self._charges(self.start)

    @cached_property
    def dhw_quiet_windows(self) -> list[tuple[float, float, float, float]]:
        s = self.s
        return w1.quiet_windows(s["dhw_tank_temp"], s["dhw_active"], s["heartbeat"], self.artifacts,
                                self.dhw_section_start, self.end, self.tz)

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
        return w1.draw_of(self.dhw_charges, self.dhw_section_start, self.end, self.master.get("dhw_tank_volume_l"),
                          standby[0] if standby else None, self.cold_water_c)

    # --- Haushalt ----------------------------------------------------------------------------------------------
    @cached_property
    def persons(self) -> list[hh.Person]:
        return hh.parse_persons(self.master.get("household"))

    @cached_property
    def dhw_dates(self) -> list:
        return hh.local_dates(self.dhw_section_start, self.end, self.tz)

    # --- Kosten (Audit 5) --------------------------------------------------------------------------------------
    @cached_property
    def day_costs(self) -> dict[str, float | None]:
        """Stromkosten je gültigem Tag (ganzes Fenster): dynamischer Preis, sonst Arbeitspreis aus den Stammdaten."""
        price = self.master.get("tariff_price")
        price = None if price is None else float(price)
        out = {r["day"]: k1.day_cost(r, self.s["electricity_meter"], self.s["price_signal"], price, self.tz)
               for r in self.daily_rows_window}
        if self.statistic_rows:
            # Statistik-Tage (1.11): Arbeitspreis; mit dynamischem Preis der mittlere gezahlte Preis des Fensters
            if self.s["price_signal"]:
                paid = [(out[r["day"]], r["electricity_kwh"]) for r in self.daily_rows_window
                        if out.get(r["day"]) is not None]
                kwh = sum(k for _, k in paid)
                price = sum(c for c, _ in paid) / kwh if paid and kwh > 0 else None
            for r in self.statistic_rows:
                out[r["day"]] = None if price is None else r["electricity_kwh"] * price
        return out

    @cached_property
    def year_projection(self) -> dict | None:
        """Hochrechnung aufs Jahr wie K2 (Gradtage des Standorts); None ohne Gradtage oder mit zu wenigen Tagen."""
        year_dd = self.master.get("heating_degree_days")
        return k1.project_year(self.year_rows, self.outdoor_daily, self.tz, float(year_dd)) if year_dd else None

    @cached_property
    def fixed_costs(self) -> dict:
        """Feste Kosten der Wärmepumpe je kWh Wärme (cost.fixed_costs), Jahreswärme aus K2 oder der Abrechnung."""
        year = self.year_projection
        return k1.fixed_costs(self.master, year["heat_kwh"] if year else None)

    @cached_property
    def timeline_master(self) -> dict:
        """Stammdaten für die Zeitstrahl-Skalen, ergänzt um feste Kosten und die Preis-Sensoren (ohne Zeitreihe)."""
        out = self.master | {"fixed_costs": self.fixed_costs}
        if self.price_refs is not None:
            heat = self.fixed_costs["annual_heat_kwh"]
            out["price_references"] = [hp.meta(r, self.master, heat) for r in self.price_refs]
        return out

    @cached_property
    def outdoor_daily(self) -> Series:
        """Außentemperatur für Gradtage: Wetterdienst bevorzugt, Außenfühler wird durch Abtauen verfälscht (D10)."""
        return self.s["outdoor_temp_reference"] or self.s["outdoor_temp"]

    @cached_property
    def year_basis(self) -> impact.YearBasis:
        """Jahreswerte für die Wirkung der Aktionen (impact.py)."""
        return impact.YearBasis(self)

    # --- Tage --------------------------------------------------------------------------------------------------
    def full_days(self) -> list[tuple[float, float]]:
        return days.full_days(self.start, self.end, self.tz)
