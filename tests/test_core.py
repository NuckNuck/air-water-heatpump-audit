"""Tests für Zykluserkennung und Datenbasis mit konstruierten Zeitreihen. Aufruf: python3 -m unittest"""

import unittest

from audit_core import cycles as c3
from audit_core import data_basis as d0
from audit_core.result import HINT, INFO, NOT_ASSESSABLE, OK, WARN, CheckResult, count, num, overall
from audit_core.series import combine, intersect, intervals_where, subtract, weighted_median, weighted_values

M = 60
H = 3600


def onoff(*switches, start_value=0):
    """Ein/Aus-Zeitreihe: Wechsel zu den angegebenen Zeitpunkten (in Sekunden)."""
    out, v = [(0, start_value)], start_value
    for t in switches:
        v = 1 - v
        out.append((t, v))
    return out


class SeriesTest(unittest.TestCase):
    def test_intervals_where_merges_repeated_values(self):
        s = [(0, 0), (10, 1), (20, 1), (30, 0)]
        self.assertEqual(intervals_where(s, lambda v: v == 1, 0, 100), [(10, 30)])

    def test_value_before_start_is_carried(self):
        s = [(0, 1), (50, 0)]
        self.assertEqual(intervals_where(s, lambda v: v == 1, 20, 100), [(20, 50)])

    def test_intersect_and_subtract(self):
        self.assertEqual(intersect([(0, 10)], [(5, 20)]), [(5, 10)])
        self.assertEqual(subtract([(0, 10)], [(3, 4), (8, 12)]), [(0, 3), (4, 8)])

    def test_combine_and_weighted_median(self):
        diff = combine([(0, 30.0), (100, 31.0)], [(0, 29.0)], lambda a, b: a - b, 0, 200)
        self.assertEqual(diff, [(0, 1.0), (100, 2.0)])
        self.assertEqual(weighted_median(weighted_values(diff, [(0, 150)])), 1.0)


class CycleTest(unittest.TestCase):
    def test_simple_cycles_and_pause(self):
        s = onoff(10 * M, 40 * M, 50 * M, 90 * M)
        cyc = c3.detect_cycles(s, 0, 2 * H)
        self.assertEqual([(c.start, c.end) for c in cyc], [(10 * M, 40 * M), (50 * M, 90 * M)])
        self.assertEqual(cyc[1].pause_before, 10 * M)
        self.assertTrue(all(c.closed for c in cyc))

    def test_short_stop_is_bridged(self):
        s = onoff(10 * M, 20 * M, 20 * M + 20, 40 * M)
        self.assertEqual(len(c3.detect_cycles(s, 0, H)), 1)

    def test_stop_in_artifact_window_is_bridged(self):
        # 2-min-Stopp mitten in einem Neustart-Fenster ist kein echter Stopp
        s = onoff(10 * M, 20 * M, 22 * M, 40 * M)
        cyc = c3.detect_cycles(s, 0, H, artifacts=[(19 * M, 23 * M)])
        self.assertEqual(len(cyc), 1)

    def test_defrost_stop_counted_separately(self):
        s = onoff(10 * M, 30 * M, 33 * M, 50 * M)
        defrost = onoff(25 * M, 30 * M)
        cyc = c3.detect_cycles(s, 0, H, defrost=defrost)
        self.assertEqual(len(cyc), 1)
        self.assertEqual(cyc[0].defrost_stops, 1)

    def test_open_ends(self):
        s = onoff(30 * M, 50 * M, start_value=1)
        cyc = c3.detect_cycles(s, 0, H)
        self.assertTrue(cyc[0].open_start)
        self.assertTrue(cyc[1].open_end)
        self.assertEqual(c3.starts(cyc), [50 * M])

    def test_first_data_point_on_counts_as_open(self):
        s = [(5 * M, 1), (20 * M, 0)]
        self.assertTrue(c3.detect_cycles(s, 0, H)[0].open_start)

    def test_kind_classification(self):
        s = onoff(0, 60 * M, 70 * M, 80 * M, 90 * M, 100 * M)
        dhw = onoff(40 * M, 60 * M, 69 * M, 81 * M)
        kinds = [c.kind for c in c3.detect_cycles(s, 0, 2 * H, dhw=dhw)]
        self.assertEqual(kinds, [c3.MIXED, c3.DHW, c3.HEATING])

    def test_max_starts_per_hour_grades(self):
        many = onoff(*[i * 4 * M + d for i in range(14) for d in (0, 2 * M)])
        r = c3.check_max_starts_per_hour(c3.detect_cycles(many, 0, 2 * H), 0, 2 * H)
        self.assertEqual(r.verdict, WARN)
        self.assertGreater(r.value, 12)

    def test_projection_capped_at_hint(self):
        s = onoff(*[i * 30 * M + d for i in range(14 * 48) for d in (0, 10 * M)])
        cyc = c3.detect_cycles(s, 0, 14 * 24 * H)
        r = c3.check_starts_per_year(cyc, 0, 14 * 24 * H, 6279)
        self.assertGreater(r.value, 5500)
        self.assertEqual(r.verdict, HINT)

    def test_projection_needs_heating_hours(self):
        r = c3.check_starts_per_year([], 0, 14 * 24 * H, None)
        self.assertEqual(r.verdict, NOT_ASSESSABLE)
        self.assertIn("Stammdaten fehlen", r.text)

    def test_backup_heater_share(self):
        heater = onoff(0, 10 * H)  # 10 h × 3 kW = 30 kWh
        r = c3.check_backup_heater({"immersion_heater": heater}, {"immersion_heater": 3.0}, 1000, 0, 7 * 24 * H)
        self.assertEqual((r.value, r.verdict), (3.0, HINT))

    def test_backup_heater_without_power_is_not_assessable(self):
        heater = onoff(0, 10 * H)
        r = c3.check_backup_heater({"immersion_heater": heater}, {"immersion_heater": None}, 1000, 0, 7 * 24 * H)
        self.assertEqual(r.verdict, NOT_ASSESSABLE)
        self.assertIn("Stammdaten fehlen", r.text)
        # Lief der Heizstab nie, braucht es seine Leistung nicht
        r = c3.check_backup_heater({"immersion_heater": []}, {"immersion_heater": None}, 1000, 0, 7 * 24 * H)
        self.assertEqual((r.value, r.verdict), (0.0, OK))


class ShortCycleAndDefrostTest(unittest.TestCase):
    """C3 zählt sehr kurze Läufe nach Tagen, C6 bewertet Abtauungen über +5 °C außen."""

    @staticmethod
    def heating_cycles(very_short_starts):
        day = 24 * H
        normal = [c3.Cycle(i * day / 20, i * day / 20 + 30 * 60) for i in range(20)]
        return normal + [c3.Cycle(t, t + 120) for t in very_short_starts]

    def test_very_short_cycles_on_one_day_are_green(self):
        r = c3.check_short_cycles(self.heating_cycles([2 * H, 5 * H]), tz="UTC")
        self.assertEqual(r.verdict, OK)
        self.assertEqual(r.details["very_short_days"], ["1970-01-01"])
        self.assertIn("an 1 Tag", r.text)

    def test_very_short_cycles_on_two_days_are_hint(self):
        r = c3.check_short_cycles(self.heating_cycles([2 * H, 26 * H]), tz="UTC")
        self.assertEqual(r.verdict, HINT)
        self.assertIn("an 2 Tagen", r.text)

    def test_frequent_defrost_above_five_degrees_is_hint(self):
        runs = [c3.Cycle(0, 6 * H)]
        # je Stunde 3 Abtauungen à 5 min
        defrost = [(t * H + m * 60, v) for t in range(6) for m, v in ((5, 1), (10, 0), (25, 1), (30, 0), (45, 1), (50, 0))]
        warm = c3.check_defrost([(0, 0)] + defrost, runs, 0, 6 * H, outdoor=[(0, 8.0)])
        self.assertEqual(warm.verdict, HINT)
        self.assertEqual(warm.details["warm_events"], 18)
        cold = c3.check_defrost([(0, 0)] + defrost, runs, 0, 6 * H, outdoor=[(0, 1.0)])
        self.assertEqual(cold.verdict, OK)  # unter +5 °C ist häufiges Abtauen normal
        short = c3.check_defrost([(0, 0)] + defrost, [c3.Cycle(0, 2 * H)], 0, 6 * H, outdoor=[(0, 8.0)])
        self.assertEqual(short.verdict, OK)  # unter 5 h Lauf über +5 °C gibt es noch keinen Grund für Gelb


class DataBasisTest(unittest.TestCase):
    def test_heartbeat_gaps_and_coverage(self):
        hb = [(t, t) for t in range(0, 3600, 60) if not 1200 <= t < 1800]
        gaps = d0.heartbeat_gaps(hb, 0, 3600)
        self.assertEqual(gaps, [(1140, 1800)])
        self.assertEqual(d0.check_coverage(hb, 0, 3600).verdict, WARN)

    def test_restarts_detected_from_uptime_drop(self):
        hb = [(0, 500.0), (60, 560.0), (120, 5.0), (180, 65.0)]
        self.assertEqual(d0.restarts(hb), [(115.0, 120)])

    def test_single_restart_in_short_period_is_green(self):
        hb = [(0, 500.0), (60, 5.0)]
        self.assertEqual(d0.check_restarts(hb, 0, 4 * H).verdict, OK)

    def test_resolution(self):
        s = [(i, 30 + 0.5 * (i % 7)) for i in range(100)]
        self.assertEqual(d0.resolution(s), 0.5)
        self.assertEqual(d0.resolution([(i, 30 + 0.01 * i) for i in range(100)]), 0.01)

    def test_sensor_offset(self):
        comp = onoff(0, 30 * M, 60 * M, 90 * M, 120 * M, 150 * M, 180 * M, start_value=1)
        pump = [(0, 1)]
        # Verdichter aus 0–30, 60–90, 120–150, 180–200 min: dort 0,5 K, im Lauf 5 K
        flow = sorted([(t, 30.5) for t in (0, 60 * M, 120 * M, 180 * M)] + [(t, 35.0) for t in (30 * M, 90 * M, 150 * M)])
        ret = [(0, 30.0)]
        r = d0.check_sensor_offset(flow, ret, comp, pump, [(0, 0)], [(0, 0)], 0, 200 * M)
        self.assertEqual((r.value, r.verdict), (0.5, OK))

    def test_sensor_offset_is_time_mean(self):
        # Fühler in 0,5-K-Schritten: Differenz pendelt je halbe Pause zwischen 0 und 0,5 K → 0,25 K, nicht 0 oder 0,5
        comp = onoff(0, 30 * M, 60 * M, 90 * M, 120 * M, 150 * M, 180 * M, start_value=1)
        flow = sorted([(t, 30.0) for t in (0, 60 * M, 120 * M, 180 * M)] + [(t + 1050, 30.5) for t in (0, 60 * M, 120 * M)]
                      + [(t, 35.0) for t in (30 * M, 90 * M, 150 * M)])
        r = d0.check_sensor_offset(flow, [(0, 30.0)], comp, [(0, 1)], [(0, 0)], [(0, 0)], 0, 180 * M)
        self.assertAlmostEqual(r.value, 0.25, places=2)

    def test_sensor_offset_needs_windows(self):
        r = d0.check_sensor_offset([(0, 30.0)], [(0, 30.0)], [(0, 1)], [(0, 1)], [], [], 0, H)
        self.assertEqual(r.verdict, NOT_ASSESSABLE)


class OverallTest(unittest.TestCase):
    def test_overall(self):
        mk = lambda v: CheckResult("X", "x", v)
        self.assertEqual(overall([mk(OK), mk(INFO), mk(HINT)]), HINT)
        self.assertEqual(overall([mk(INFO), mk(NOT_ASSESSABLE)]), INFO)
        self.assertEqual(overall([mk(NOT_ASSESSABLE)]), NOT_ASSESSABLE)

    def test_num_german_format(self):
        self.assertEqual(num(2.77, ".1f"), "2,8")
        self.assertEqual(num(0.5, "+.2f"), "+0,50")
        self.assertEqual(num(14.3), "14,3")
        self.assertEqual(num(2964, ","), "2.964")
        self.assertEqual(num(12345.6, ",.1f"), "12.345,6")

    def test_count_singular_plural(self):
        self.assertEqual(count(1, "Tag", "Tage"), "1 Tag")
        self.assertEqual(count(0, "Tag", "Tage"), "0 Tage")
        self.assertEqual(count(7, "gültiger Tag", "gültige Tage"), "7 gültige Tage")


if __name__ == "__main__":
    unittest.main()


from audit_core import heat
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("profiles", __import__("pathlib").Path(__file__).parents[1]
                                     / "custom_components" / "air_water_heatpump_audit" / "profiles.py")
_profiles = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_profiles)
TABLE = _profiles.MODEL_PROFILES["mitsubishi_pud_shwm140"]["capacity_min_table"]
from datetime import datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")


def local(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=BERLIN).timestamp()


class HeatTest(unittest.TestCase):
    def test_heat_power_and_energy(self):
        # 15 l/min, ΔT 5 K → 15/60 × 5 × 4,153 ≈ 5,19 kW; 1 h → 5,19 kWh
        p = heat.heat_power([(0, 15.0)], [(0, 35.0)], [(0, 30.0)], 0, H)
        self.assertAlmostEqual(heat.energy_kwh(p, [(0, H)]), 5.19, places=2)
        p = heat.heat_power([(0, 15.0)], [(0, 35.0)], [(0, 30.0)], 0, H, offset_k=0.5)
        self.assertAlmostEqual(heat.energy_kwh(p, [(0, H)]), 4.67, places=2)

    def test_defrost_heat_is_negative(self):
        p = heat.heat_power([(0, 15.0)], [(0, 28.0)], [(0, 30.0)], 0, H)
        self.assertLess(heat.energy_kwh(p, [(0, H)]), 0)

    def test_min_capacity_interpolation(self):
        t = TABLE
        self.assertEqual(heat.min_capacity_kw(7, 35, t), 3.5)
        self.assertAlmostEqual(heat.min_capacity_kw(9.5, 35, t), 3.7)
        self.assertAlmostEqual(heat.min_capacity_kw(7, 40, t), 3.35)
        self.assertEqual(heat.min_capacity_kw(-30, 70, t), 5.4)

    def test_capacity_table_from_json_storage(self):
        # Im JSON-Speicher von HA werden Zahlenschlüssel zu Text.
        t = heat.parse_capacity_table({"35": {"-7": "3.9", "7": 3.5}})
        self.assertEqual(t, {35.0: {-7.0: 3.9, 7.0: 3.5}})
        self.assertIsNone(heat.parse_capacity_table(None))
        self.assertIsNone(heat.parse_capacity_table({}))

    def test_capacity_table_rejects_garbage(self):
        for raw in ([1, 2], {"35": 3.5}, {"35": {"7": "viel"}}, {"35": {"7": 0}}):
            with self.assertRaises(ValueError):
                heat.parse_capacity_table(raw)


class DailyChecksTest(unittest.TestCase):
    def setUp(self):
        self.start, self.end = local(2026, 10, 25), local(2026, 11, 3, 13)
        self.hb = [(t, t - self.start) for t in range(int(self.start), int(self.end), 60)]

    def test_dst_day_has_25_hours(self):
        from audit_core import days
        a, b = days.full_days(self.start, self.end)[0]
        self.assertEqual(b - a, 25 * H)

    def test_meter_vs_controller(self):
        meter = [(m, 10.0 * i) for i, m in enumerate(self._midnights())]  # 10 kWh/Tag laut Zähler
        ctrl = [(m + 600, 11.0) for m in self._midnights()]  # Steuerung meldet je Vortag 11 kWh
        r = d0.check_meter_vs_controller(meter, [ctrl], self.hb, self.start, self.end)
        self.assertEqual((r.value, r.verdict), (1.1, OK))

    def test_controller_day_boundary(self):
        dates = [(m + 2 * M, str(i)) for i, m in enumerate(self._midnights())]
        self.assertEqual(d0.check_controller_day_boundary(dates, self.start, self.end).verdict, OK)
        late = [(m - 60 * M, str(i)) for i, m in enumerate(self._midnights())]
        r = d0.check_controller_day_boundary(late, self.start - 2 * H, self.end)
        self.assertEqual((r.value, r.verdict), (-60, HINT))

    def test_outdoor_sensor(self):
        r = d0.check_outdoor_sensor([(0, 12.0)], [(0, 10.0)], [(0, 0)], self.start, self.end)
        self.assertEqual((r.value, r.verdict), (2.0, HINT))

    def test_history_depth(self):
        self.assertEqual(d0.check_history_depth(10, None).verdict, HINT)
        self.assertEqual(d0.check_history_depth(10, 6.4).verdict, OK)
        self.assertEqual(d0.check_history_depth(3, None).verdict, WARN)

    def test_load_vs_min_capacity(self):
        # 2 kW Dauerlast bei 10 °C außen und 35 °C Vorlauf → unter der Mindestleistung (≈ 3,7 kW)
        power = [(self.start, 2.0)]
        r = c3.check_load_vs_min_capacity(power, [(0, 10.0)], [(0, 35.0)], [(0, 1)], [(0, 0)], self.hb,
                                          self.start, self.end, TABLE)
        self.assertEqual(r.verdict, INFO)
        self.assertLess(r.value, 1)

    def test_load_vs_min_capacity_needs_table(self):
        r = c3.check_load_vs_min_capacity([], [], [], [], [], self.hb, self.start, self.end, None)
        self.assertEqual(r.verdict, NOT_ASSESSABLE)

    def _midnights(self):
        from audit_core import days
        return days.midnights(self.start, self.end)


class RunnerTest(unittest.TestCase):
    def test_data_quality(self):
        from audit_core.runner import data_quality
        dq = lambda d2, d4, d8: data_quality(CheckResult("D2", "", d2), CheckResult("D4", "", d4),
                                             CheckResult("D8", "", d8))
        self.assertEqual(dq(OK, OK, OK), "high")
        self.assertEqual(dq(OK, OK, HINT), "medium")
        self.assertEqual(dq(OK, NOT_ASSESSABLE, OK), "medium")
        self.assertEqual(dq(OK, NOT_ASSESSABLE, HINT), "low")
        self.assertEqual(dq(WARN, OK, OK), "low")

    def test_missing_roles_give_not_assessable(self):
        from audit_core.runner import run_audits
        rep = run_audits({}, 0, 2 * H, recorder_keep_days=10, long_term_days=None, heater_kw={})
        checks = {r["check_id"]: r["verdict"] for a in rep["audits"].values() for r in a["checks"]}
        self.assertEqual(checks["D4"], NOT_ASSESSABLE)
        self.assertEqual(checks["C3"], NOT_ASSESSABLE)
        self.assertEqual(rep["audits"]["data_basis"]["dq"], "low")
        self.assertEqual(rep["cycles"], [])


class FlowTemperatureTest(unittest.TestCase):
    """Audit 2 mit drei Heizzyklen à 2 h, dazwischen 20 min Pause mit laufender Pumpe."""

    def setUp(self):
        from audit_core import flow_temp as t2
        self.t2 = t2
        self.end = 7 * H
        # Zyklen 0:20–2:20, 2:40–4:40, 5:00–7:00 (der letzte läuft am Ende noch)
        self.comp = onoff(20 * M, 140 * M, 160 * M, 280 * M, 300 * M)
        self.pump = [(0, 1)]
        self.cycles = c3.detect_cycles(self.comp, 0, self.end)
        self.heating, self.used = t2.heating_windows(self.cycles, [], [], [], [], 0, self.end)
        self.pauses = t2.pause_windows(self.comp, self.pump, [], [], 0, self.end)

    def offset(self, flow, circuit):
        return self.t2.check_circuit_sensor_offset(flow, circuit, self.pauses, 0, self.end)

    def test_windows_skip_settling(self):
        self.assertEqual(self.used, 3)
        self.assertEqual(self.heating[0], (30 * M, 140 * M))
        self.assertEqual(len(self.pauses), 3)  # vor dem 1. Zyklus und zwei Pausen, je 20 min − 5 min Einschwingen

    def test_buffer_loss_graded_and_capped_without_robust_offset(self):
        flow, circuit = [(0, 38.0)], [(0, 33.0)]
        r = self.t2.check_buffer_flow_loss(flow, circuit, "parallel_buffer", self.heating, self.used,
                                           self.offset(flow, circuit), 0, self.end)
        self.assertEqual(r.value, 5.0)
        self.assertEqual(r.verdict, HINT)  # > 4 K wäre rot, aber T2 ist nicht belastbar
        self.assertIn("Höchstens gelb", r.text)
        small = self.t2.check_buffer_flow_loss([(0, 34.0)], circuit, "parallel_buffer", self.heating, self.used,
                                               self.offset(flow, circuit), 0, self.end)
        self.assertEqual(small.verdict, OK)

    def test_robust_zero_offset_counts_as_matched_sensors(self):
        # T2 belastbar mit ±0,00 K: nichts abzuziehen, aber die Fühler sind abgeglichen → rot erlaubt, kein „vorläufig“
        matched = CheckResult("T2", "circuit_sensor_offset", OK, 0.0, "K", details={"robust": True})
        r = self.t2.check_buffer_flow_loss([(0, 38.0)], [(0, 33.0)], "parallel_buffer", self.heating, self.used,
                                           matched, 0, self.end)
        self.assertEqual(r.verdict, WARN)
        self.assertIn("abgeglichen", r.text)
        self.assertNotIn("vorläufig", r.text)

    def test_sensor_offset_within_tolerance_is_green(self):
        small = self.offset([(0, 34.15)], [(0, 34.0)])
        self.assertEqual(small.verdict, OK)
        self.assertIn("stimmen überein", small.text)
        self.assertIn("+0,1 K", small.text)
        self.assertEqual(self.offset([(0, 35.5)], [(0, 34.0)]).verdict, HINT)

    def test_buffer_loss_not_applicable_or_missing(self):
        r = self.t2.check_buffer_flow_loss([(0, 38.0)], [], "none", self.heating, self.used,
                                           self.offset([], []), 0, self.end)
        self.assertEqual(r.verdict, INFO)
        r = self.t2.check_buffer_flow_loss([(0, 38.0)], [], "parallel_buffer", self.heating, self.used,
                                           self.offset([], []), 0, self.end)
        self.assertEqual(r.verdict, NOT_ASSESSABLE)
        self.assertIn("Eingang fehlt", r.text)

    def test_buffer_loss_gate(self):
        heating, used = self.t2.heating_windows([], [], [], [], [], 0, self.end)
        r = self.t2.check_buffer_flow_loss([(0, 38.0)], [(0, 33.0)], "parallel_buffer", heating, used,
                                           self.offset([], []), 0, self.end)
        self.assertEqual(r.verdict, NOT_ASSESSABLE)
        self.assertIn("vorläufiges Urteil ab 1 h aus 1 Zyklus", r.text)

    def test_sensor_offset_in_pauses(self):
        # in den Pausen 0,5 K Unterschied, im Heizbetrieb 5 K
        flow = [(0, 30.5), (20 * M, 38.0), (140 * M, 30.5), (160 * M, 38.0), (280 * M, 30.5), (300 * M, 38.0)]
        r = self.offset(flow, [(0, 30.0), (20 * M, 33.0), (140 * M, 30.0), (160 * M, 33.0), (280 * M, 30.0),
                               (300 * M, 33.0)])
        self.assertEqual((r.verdict, r.value), (OK, 0.5))
        self.assertFalse(r.details["robust"])

    def test_flow_ratio_from_mixing(self):
        # WP 38/34, Heizkreis 33/32, WP-Rücklauf ≈ Heizkreis-Rücklauf → V_HK/V_WP = (38 − 32) / (33 − 32) = 6
        r = self.t2.check_flow_ratio([(0, 38.0)], [(0, 32.0)], [(0, 33.0)], [(0, 32.0)], [(0, 14.0)], self.heating,
                                     self.used, 0, self.end)
        self.assertEqual((r.verdict, r.value, r.details["circuit_lpm"]), (INFO, 6.0, 84))
        warmer_return = self.t2.check_flow_ratio([(0, 38.0)], [(0, 34.0)], [(0, 37.5)], [(0, 32.0)], [], self.heating,
                                                 self.used, 0, self.end)
        self.assertIn("mehr Wasser als der Heizkreis", warmer_return.text)

    def test_flow_ratio_capped_by_pump_maximum(self):
        # Mischungsbilanz ergibt 6 × 14 = 84 l/min, die Pumpe schafft höchstens 57 l/min
        r = self.t2.check_flow_ratio([(0, 38.0)], [(0, 32.0)], [(0, 33.0)], [(0, 32.0)], [(0, 14.0)], self.heating,
                                     self.used, 0, self.end, circuit_max_lpm=57)
        self.assertEqual((r.value, r.details["circuit_lpm"], r.details["estimate_lpm"]), (4.1, 57, 84))
        self.assertIn("höchstens 4,1-mal", r.text)
        self.assertIn("ergäbe ≈ 84 l/min", r.text)
        below = self.t2.check_flow_ratio([(0, 38.0)], [(0, 32.0)], [(0, 33.0)], [(0, 32.0)], [(0, 14.0)],
                                         self.heating, self.used, 0, self.end, circuit_max_lpm=100)
        self.assertEqual((below.value, below.details["circuit_lpm"]), (6.0, 84))
        self.assertNotIn("estimate_lpm", below.details)

    def test_spread_and_flow_minimum(self):
        r = self.t2.check_heat_pump_spread([(0, 38.0)], [(0, 34.0)], [(0, 14.0)], 14.3, self.heating, self.used, 0,
                                           self.end)
        self.assertEqual(r.verdict, OK)  # 0,3 l/min unter dem Minimum liegt in der Messtoleranz
        self.assertIn("Untergrenze", r.text)
        r = self.t2.check_heat_pump_spread([(0, 38.0)], [(0, 34.0)], [(0, 12.0)], 14.3, self.heating, self.used, 0,
                                           self.end)
        self.assertEqual(r.verdict, HINT)
        r = self.t2.check_heat_pump_spread([(0, 45.0)], [(0, 34.0)], [], None, self.heating, self.used, 0, self.end)
        self.assertEqual(r.verdict, HINT)  # Spreizung 11 K

    def test_setpoint(self):
        r = self.t2.check_flow_vs_setpoint([(0, 38.0)], [(0, 35.0)], [(0, 34.0)], self.heating, self.used, 0,
                                           self.end)
        self.assertEqual((r.verdict, r.value, r.details["circuit_minus_setpoint_k"]), (INFO, 4.0, 1.0))
        self.assertIn("Heizkreis-Fühler", r.text)

    def test_room_headroom(self):
        day = 24 * H
        start, end = 0, 8 * day
        comp, t = [], 0
        while t < end:  # jeden Tag 4 h heizen
            comp += [(t + 6 * H, 1), (t + 10 * H, 0)]
            t += day
        cycles = c3.detect_cycles([(0, 0)] + comp, start, end)
        heating, _ = self.t2.heating_windows(cycles, [], [], [], [], start, end)
        warm = self.t2.check_heating_curve_headroom([(0, 23.0)], 21.5, heating, start, end, "UTC")
        self.assertEqual(warm.verdict, HINT)
        near = self.t2.check_heating_curve_headroom([(0, 21.8)], 21.5, heating, start, end, "UTC")
        self.assertEqual(near.verdict, OK)
        cold = self.t2.check_heating_curve_headroom([(0, 20.5)], 21.5, heating, start, end, "UTC")
        self.assertEqual(cold.verdict, INFO)
        none = self.t2.check_heating_curve_headroom([], 21.5, heating, start, end, "UTC")
        self.assertEqual(none.verdict, NOT_ASSESSABLE)

    def test_room_headroom_skips_day_where_sensor_starts_late(self):
        """Fühler ab 18:30 des ersten Tags: Der Abendwert ist kein Tagesmittel, der Tag zählt nicht."""
        day = 24 * H
        start, end = 0, 6 * day
        comp, t = [], 0
        while t < end:
            comp += [(t + 6 * H, 1), (t + 10 * H, 0)]
            t += day
        heating, _ = self.t2.heating_windows(c3.detect_cycles([(0, 0)] + comp, start, end), [], [], [], [], start, end)
        late = self.t2.check_heating_curve_headroom([(18.5 * H, 23.0)], 21.5, heating, start, end, "UTC")
        self.assertEqual([d for d, _ in late.details["days"]], ["1970-01-02", "1970-01-03", "1970-01-04", "1970-01-05",
                                                               "1970-01-06"])
        early = self.t2.check_heating_curve_headroom([(0.5 * H, 23.0)], 21.5, heating, start, end, "UTC")
        self.assertEqual(len(early.details["days"]), 6)  # ab 00:30 sind ≥ 90 % des Tags abgedeckt


from audit_core import efficiency as e1


class EfficiencyTest(unittest.TestCase):
    """Synthetische Woche: 15 l/min, Spreizung 2 K (≈ 2,08 kW), 7 °C außen, Senke 34 °C, 13 kWh Strom je Tag."""

    def setUp(self):
        self.start, self.end = local(2026, 11, 2), local(2026, 11, 10, 12)
        span = range(int(self.start), int(self.end), 60)
        self.hb = [(t, float(t - self.start)) for t in span]
        self.meter = [(self.start + d * 24 * H, 1000.0 + 13 * d) for d in range(9)]
        self.flow, self.ret, self.out = [(self.start, 35.0)], [(self.start, 33.0)], [(self.start, 7.0)]
        # Warmwasser täglich 2 h
        self.dhw = [p for d in range(9) for p in ((local(2026, 11, 2, 10) + d * 24 * H, "on"),
                                                  (local(2026, 11, 2, 12) + d * 24 * H, "off"))]

    def rows(self):
        power = heat.heat_power([(self.start, 15.0)], self.flow, self.ret, self.start, self.end)
        ideal = e1.carnot_power(power, self.flow, self.ret, self.out, self.start, self.end)
        return e1.daily_rows(self.meter, power, power, ideal, self.out, self.dhw, self.hb, self.start, self.end)

    def test_carnot_power(self):
        ideal = e1.carnot_power([(0, 5.0)], [(0, 37.0)], [(0, 33.0)], [(0, 5.0)], 0, H)
        self.assertAlmostEqual(ideal[0][1], 5.0 / (308.15 / 30), places=4)
        # Hub < 5 K zählt nicht
        self.assertEqual(e1.carnot_power([(0, 5.0)], [(0, 30.0)], [(0, 28.0)], [(0, 27.0)], 0, H)[0][1], 0.0)

    def test_weekly_checks(self):
        rows = self.rows()
        self.assertEqual(len(rows), 8)
        self.assertAlmostEqual(rows[0]["cop"], 49.84 / 13, places=1)
        self.assertEqual(e1.check_daily_cop(rows, False, 1.0).verdict, INFO)
        weekly = e1.check_weekly_cop(rows)
        self.assertAlmostEqual(weekly.details["field_cop"], 2.7 + 1.1 * 5 / 11)
        eta = e1.check_carnot_efficiency(rows, "medium", True)
        self.assertEqual(eta.verdict, OK)
        self.assertAlmostEqual(eta.value, 2.0767 * 24 / (307.15 / 27) / 13, places=2)
        self.assertEqual(e1.check_carnot_efficiency(rows, "low", True).verdict, NOT_ASSESSABLE)
        self.assertAlmostEqual(e1.check_dhw_share(rows).value, 100 * 2 / 24, places=0)

    def test_low_efficiency_needs_robust_offset_for_warn(self):
        self.meter = [(t, 1000 + (v - 1000) * 2.5) for t, v in self.meter]  # 32,5 kWh/Tag → Gütegrad ≈ 0,13
        rows = self.rows()
        self.assertEqual(e1.check_carnot_efficiency(rows, "high", True).verdict, WARN)
        self.assertEqual(e1.check_carnot_efficiency(rows, "high", False).verdict, HINT)

    def drop_heartbeat(self, a, b):
        self.hb = [p for p in self.hb if not a <= p[0] < b]

    def test_gap_filled_from_counter(self):
        # Sicherung aus: 52 min ohne Daten am Mittag; der Wärmezähler der Steuerung zählt weiter (F175)
        g0, g1 = local(2026, 11, 2, 12), local(2026, 11, 2, 12, 52)
        self.drop_heartbeat(g0, g1)
        power = heat.heat_power([(self.start, 15.0)], self.flow, self.ret, self.start, self.end)
        kw = power[0][1]
        counter = [(t, kw * ((t - self.start) % (24 * H)) / H) for t, _ in self.hb]
        ideal = e1.carnot_power(power, self.flow, self.ret, self.out, self.start, self.end)
        rows = e1.daily_rows(self.meter, power, power, ideal, self.out, self.dhw, self.hb, self.start, self.end,
                             heat_counter=counter)
        day = rows[0]
        self.assertEqual((day["gap_min"], day["gap_method"]), (53, e1.GAP_COUNTER))
        self.assertAlmostEqual(day["heat_kwh"], kw * 24, delta=0.05)  # nicht mit dem letzten Wert überbrückt
        self.assertIn("Lücke 53 min", e1.check_daily_cop(rows[:1], True, 0.1).text)

    def test_gap_filled_by_heating_load(self):
        self.drop_heartbeat(local(2026, 11, 2, 12), local(2026, 11, 2, 12, 52))
        day = self.rows()[0]
        self.assertEqual(day["gap_method"], e1.GAP_LOAD)
        self.assertAlmostEqual(day["heat_kwh"], 49.84, delta=0.05)  # konstante Last: wie der Zeitanteil

    def test_night_gap_weighs_more_than_noon_gap(self):
        day = (local(2026, 11, 2), local(2026, 11, 3))
        out = [(day[0], 0.0), (local(2026, 11, 2, 8), 12.0), (local(2026, 11, 2, 20), 0.0)]  # nachts kalt
        def share(g0, g1):
            gaps = [(g0, g1)]
            heat_gap, method = e1.gap_heat(100.0, gaps, subtract([day], gaps), [], out)
            return heat_gap
        self.assertGreater(share(local(2026, 11, 2, 2), local(2026, 11, 2, 3)),
                           2 * share(local(2026, 11, 2, 12), local(2026, 11, 2, 13)))

    def test_gap_too_large_or_at_midnight_drops_day(self):
        self.drop_heartbeat(local(2026, 11, 2, 8), local(2026, 11, 2, 12))  # 4 h ≈ 17 % der Wärme
        self.drop_heartbeat(local(2026, 11, 3, 23, 50), local(2026, 11, 4, 0, 10))  # Zählerstand um Mitternacht fehlt
        days = [r["day"] for r in self.rows()]
        self.assertNotIn("2026-11-02", days)
        self.assertNotIn("2026-11-03", days)
        self.assertNotIn("2026-11-04", days)
        self.assertIn("2026-11-05", days)

    def test_counter_reset_in_gap_falls_back_to_load(self):
        gaps = [(local(2026, 11, 2, 12), local(2026, 11, 2, 13))]
        counter = [(gaps[0][0] - 60, 30.0), (gaps[0][1], 0.5)]
        _, method = e1.gap_heat(50.0, gaps, subtract([(self.start, self.start + 24 * H)], gaps), counter, self.out)
        self.assertEqual(method, e1.GAP_LOAD)

    def test_too_few_days(self):
        # vorläufig ab drei Tagen (Entscheid F239), darunter nicht bewertbar
        for check in (e1.check_weekly_cop, e1.check_dhw_share):
            self.assertEqual(check(self.rows()[:2]).verdict, NOT_ASSESSABLE)
            self.assertEqual(check(self.rows()[:3]).verdict, INFO)


from audit_core.actions import INSTALLER, NONE, OWNER, attach_actions


class ActionTest(unittest.TestCase):
    def test_only_yellow_and_red_get_an_action(self):
        results = attach_actions([CheckResult("T1", "buffer_flow_loss", v) for v in (OK, HINT, WARN, INFO,
                                                                                      NOT_ASSESSABLE)])
        self.assertEqual([r.action is not None for r in results], [False, True, True, False, False])
        self.assertEqual(results[1].action["who"], OWNER)
        self.assertIn("Heizkreispumpe", results[1].action["steps"][0])

    def test_unknown_check_has_no_action(self):
        self.assertIsNone(attach_actions([CheckResult("X9", "unknown", HINT)])[0].action)

    def test_implausibly_high_carnot_is_info_not_hint(self):
        self.assertEqual(e1.carnot_verdict(0.55, True), INFO)
        self.assertEqual(e1.carnot_verdict(0.40, True), OK)
        self.assertEqual(e1.carnot_verdict(0.27, True), HINT)
        self.assertEqual(e1.carnot_verdict(0.20, True), WARN)

    def test_carnot_action_depends_on_value(self):
        high, low = attach_actions([CheckResult("E3", "carnot_efficiency", HINT, 0.55),
                                    CheckResult("E3", "carnot_efficiency", HINT, 0.27)])
        self.assertEqual(high.action["who"], NONE)
        self.assertEqual(low.action["who"], OWNER)

    def test_action_is_part_of_the_result_dict(self):
        r = attach_actions([CheckResult("D8", "meter_resolution", HINT)])[0]
        self.assertIn("PIN", r.as_dict()["action"]["text"])

    def test_buffer_loss_target_uses_flow_ratio(self):
        t1 = CheckResult("T1", "buffer_flow_loss", HINT, 2.8, "K")
        t3 = CheckResult("T3", "flow_ratio", INFO, 4.5, "×", details={"heat_pump_lpm": 14.0, "circuit_lpm": 63})
        attach_actions([t1, t3])
        self.assertEqual(t1.action["target"], "Heizkreis fördert etwa so viel wie die Wärmepumpe: ≈ 14–18 statt "
                                              "≈ 63 l/min; Vorlauf-Unterschied höchstens 1,5 K (heute 2,8 K)")

    def test_curve_target_uses_setpoint(self):
        t5 = CheckResult("T5", "flow_vs_setpoint", INFO, 0.5, "K", details={"setpoint_c": 33.6})
        t6 = CheckResult("T6", "heating_curve_headroom", HINT, 22.6, "°C")
        attach_actions([t5, t6])
        self.assertIn("≈ 32,6 statt 33,6 °C", t6.action["target"])

    def test_day_boundary_direction(self):
        late, early = attach_actions([CheckResult("D6", "controller_day_boundary", HINT, 60.0, "min"),
                                      CheckResult("D6", "controller_day_boundary", HINT, -60.0, "min")])
        self.assertEqual(late.action["target"], "Uhr um 60 min vorstellen")
        self.assertEqual(early.action["target"], "Uhr um 60 min zurückstellen")


    MAHTANAR_CONTROLS = {
        "short_cycle_lockout": {"entity_id": "select.heatpump_short_cycle_lockout_duration_min", "state": "0",
                                "options": ["0", "15", "30", "45", "60", "120", "240"]},
        "short_cycle_min_run": {"entity_id": "number.heatpump_short_cycle_minimum_on_time", "state": "5.0",
                                "min": 1.0, "max": 20.0, "step": 1.0, "unit": "min"},
    }

    def test_control_proposal_only_for_mapped_roles_and_matching_checks(self):
        c3_, t1 = attach_actions([CheckResult("C3", "short_cycles", HINT, 12.0, "%", details={"very_short": 3}),
                                  CheckResult("T1", "buffer_flow_loss", HINT, 2.8, "K")], self.MAHTANAR_CONTROLS)
        # Sperre 0 → 30 min; Mindestlaufzeit 5 min reicht schon, daher kein Vorschlag
        self.assertEqual([(p["role"], p["current"], p["value"], p["domain"]) for p in c3_.action["controls"]],
                         [("short_cycle_lockout", "0", "30", "select")])
        self.assertNotIn("controls", t1.action)  # Heizkreispumpe ist nicht zugeordnet

    def test_no_proposal_for_green_or_reached_value(self):
        reached = self.MAHTANAR_CONTROLS | {"short_cycle_lockout": self.MAHTANAR_CONTROLS["short_cycle_lockout"]
                                            | {"state": "45"}}
        r = attach_actions([CheckResult("C3", "short_cycles", HINT)], reached)[0]
        self.assertNotIn("controls", r.action)
        self.assertIsNone(attach_actions([CheckResult("C3", "short_cycles", OK)], self.MAHTANAR_CONTROLS)[0].action)

    def test_number_and_select_one_step_lower(self):
        pump = {"circuit_pump_speed": {"entity_id": "number.pump", "state": "3", "min": 1, "max": 5, "step": 1}}
        r = attach_actions([CheckResult("T1", "buffer_flow_loss", HINT)], pump)[0]
        self.assertEqual((r.action["controls"][0]["value"], r.action["controls"][0]["event_kind"]), (2.0, "pump_setting"))
        lowest = {"circuit_pump_speed": {"entity_id": "select.pump", "state": "I", "options": ["I", "II", "III"]}}
        self.assertNotIn("controls", attach_actions([CheckResult("T1", "buffer_flow_loss", HINT)], lowest)[0].action)
        curve = {"heating_curve_shift": {"entity_id": "number.shift", "state": "-4.5", "min": -5, "max": 5}}
        r = attach_actions([CheckResult("T6", "heating_curve_headroom", HINT)], curve)[0]
        self.assertEqual(r.action["controls"][0]["value"], -5.0)  # an der Untergrenze gekappt

    def test_unavailable_control_is_ignored(self):
        broken = {"short_cycle_lockout": {"entity_id": "select.x", "state": "unavailable", "options": ["0", "30"]}}
        self.assertNotIn("controls", attach_actions([CheckResult("C3", "short_cycles", HINT)], broken)[0].action)


class SectionTest(unittest.TestCase):
    def test_last_event_inside_window_starts_the_section(self):
        from audit_core.runner import section_start
        events = [{"time": 50.0, "kind": "valves"}, {"time": 150.0, "kind": "heating_curve"},
                  {"time": 500.0, "kind": "other"}]
        self.assertEqual(section_start(events, 100, 400), (150.0, events[1]))
        self.assertEqual(section_start(events[:1], 100, 400), (100, None))

    def test_audits_after_event_ignore_cycles_before(self):
        from audit_core.runner import run_audits
        s = {"compressor_running": onoff(*[i * 20 * M for i in range(1, 24)]),
             "heartbeat": [(t, t + 100) for t in range(0, 8 * H + 1, 60)]}  # lückenlos, keine Neustarts
        before = run_audits(s, 0, 8 * H, recorder_keep_days=10, long_term_days=None, heater_kw={})
        after = run_audits(s, 0, 8 * H, recorder_keep_days=10, long_term_days=None, heater_kw={},
                           events=[{"time": 6 * H, "kind": "heating_curve", "note": ""}])
        starts = lambda rep: next(r for r in rep["audits"]["capacity"]["checks"] if r["check_id"] == "C2")["value"]
        self.assertGreater(starts(before), 0)
        self.assertEqual(after["section"]["start"], 6 * H)
        self.assertEqual(after["period"]["start"], 0)
        self.assertLess(len(after["cycles"]), len(before["cycles"]))


from audit_core import timeline as tl


class TimelineTest(unittest.TestCase):
    """Drei volle Tage, 20 min an / 20 min aus, Puffer kostet 2 K, Ereignis am zweiten Tag."""

    def setUp(self):
        self.start, self.end = local(2026, 11, 2), local(2026, 11, 5, 6)
        t0 = int(self.start)
        n = int((self.end - self.start) // (20 * M))
        self.s = {
            "compressor_running": [(t0, 0)] + [(t0 + i * 20 * M, i % 2) for i in range(1, n + 1)],
            "heartbeat": [(t, float(t - t0)) for t in range(t0, int(self.end) + 1, 60)],
            "electricity_meter": [(t0 + d * 24 * H, 1000.0 + 10 * d) for d in range(4)],
            "flow_temp": [(t0, 35.0)], "return_temp": [(t0, 31.0)], "flow_rate": [(t0, 15.0)],
            "outdoor_temp": [(t0, 7.0)], "circuit_flow_temp": [(t0, 33.0)],
        }
        self.master = {"heating_hours": 6279, "hydraulic_separation": "parallel_buffer"}

    def run_with(self, events=None):
        from audit_core.runner import run_audits
        return run_audits(self.s, self.start, self.end, recorder_keep_days=10, long_term_days=None, heater_kw={},
                          master=self.master, events=events)

    def test_one_point_per_full_day_with_real_values(self):
        tl = self.run_with()["timeline"]
        self.assertEqual([d["day"] for d in tl["days"]], ["2026-11-02", "2026-11-03", "2026-11-04"])
        day = tl["days"][1]
        self.assertEqual(day["data_basis"], {"value": 100.0, "verdict": OK})
        self.assertEqual(day["capacity"]["value"], 36)
        self.assertEqual(day["capacity"]["verdict"], HINT)  # 36/Tag > 2.000 × 24 ÷ 6.279 ≈ 7,6
        self.assertAlmostEqual(day["flow_temperature"]["value"], 2.0)
        self.assertEqual(day["flow_temperature"]["verdict"], HINT)
        self.assertIsNotNone(day["efficiency"]["value"])
        self.assertEqual(day["efficiency"]["verdict"], e1.carnot_verdict(day["efficiency"]["value"], False))

    def test_event_does_not_cut_the_timeline(self):
        plain = self.run_with()["timeline"]["days"]
        cut = self.run_with([{"time": local(2026, 11, 3, 12), "kind": "valves", "note": ""}])["timeline"]["days"]
        self.assertEqual(plain, cut)

    def test_scales_follow_check_thresholds(self):
        from audit_core.audits import BY_ID
        scale = lambda audit, hours: BY_ID[audit].timeline.scale({"heating_hours": hours})
        self.assertEqual(scale("flow_temperature", 6279)["bands"][0], [0, 1.5, OK])
        self.assertAlmostEqual(scale("capacity", 6279)["bands"][0][1], 7.6)
        self.assertEqual(scale("capacity", None)["bands"], [])

    def test_merge_keeps_old_days_and_replaces_recomputed(self):
        day = lambda d, x: {"day": d, "data_basis": {"value": 100.0, "x": x}}
        old = [day("2026-01-01", 1), day("2026-01-02", 1)]
        new = [day("2026-01-02", 2), day("2026-01-03", 2)]
        self.assertEqual([d["data_basis"]["x"] for d in tl.merge(old, new)], [1, 2, 2])
        self.assertEqual(len(tl.merge(old, new, keep_days=2)), 2)

    def test_merge_drops_empty_days_before_first_data(self):
        empty = lambda d: {"day": d, "start": 0, "end": 0, "data_basis": {"value": 0.0}, "efficiency": None}
        full = lambda d: {"day": d, "data_basis": {"value": 96.0}, "efficiency": {"value": 0.3}}
        stored = [empty("2026-01-01"), empty("2026-01-02"), full("2026-01-03")]
        merged = tl.merge(stored, [empty("2026-01-04"), full("2026-01-05")])
        self.assertEqual([d["day"] for d in merged], ["2026-01-03", "2026-01-04", "2026-01-05"])
        self.assertEqual(tl.merge([empty("2026-01-01")], []), [])


class HelpTest(unittest.TestCase):
    def test_every_check_has_help(self):
        from audit_core.help import CHECK_HELP
        checks = ["D1", "D2", "D3", "D4", "D5", "D6", "D8", "D9", "D10", "E1", "E2", "E3", "E4",
                           "T1", "T2", "T3", "T4", "T5", "T6", "C1", "C2", "C3", "C4", "C5", "C6", "C7"]
        for cid in checks:
            self.assertEqual(set(CHECK_HELP[cid]), {"what", "rating", "source"}, cid)
        self.assertIn("1,5 K", CHECK_HELP["T1"]["rating"])  # Grenze aus der Konstante, deutsch formatiert


from audit_core import readiness as rd
from audit_core.result import ELAPSED, FULL_DAYS, RATE, progress


class ReadinessTest(unittest.TestCase):
    def test_full_days_count_from_the_next_midnight(self):
        # Abschnitt seit 25.10. 19:31, jetzt 26.10. 21:00: der 26.10. zählt mit, 7 Tage sind am 02.11. 00:00 voll
        p = progress(0, 7, "days", FULL_DAYS, local(2026, 10, 25, 19, 31))
        self.assertEqual(rd.check_eta(p, local(2026, 10, 26, 21)), (False, local(2026, 11, 2)))
        # Beginnt der Abschnitt heute, ist der heutige Tag nicht voll: einen Tag später
        p = progress(0, 1, "days", FULL_DAYS, local(2026, 10, 26, 8))
        self.assertEqual(rd.check_eta(p, local(2026, 10, 26, 21)), (False, local(2026, 10, 28)))

    def test_full_days_lag_and_reached(self):
        p = progress(1, 7, "days", FULL_DAYS, local(2026, 10, 24, 15, 46), lag_h=12)  # D5: Wert der Steuerung erst mittags
        self.assertEqual(rd.check_eta(p, local(2026, 10, 26, 21)), (False, local(2026, 11, 1, 12)))
        p = progress(3, 3, "days", FULL_DAYS, local(2026, 10, 24, 15, 46))
        self.assertEqual(rd.check_eta(p, local(2026, 10, 30)), (True, local(2026, 10, 28)))

    def test_rate_extrapolates_and_needs_a_first_value(self):
        self.assertEqual(rd.check_eta(progress(17, 20, "cycles", RATE, 0), 17 * H), (False, 20 * H))
        self.assertEqual(rd.check_eta(progress(0, 3, "heating_hours", RATE, 0), 5 * H), (False, None))
        self.assertEqual(rd.check_eta(progress(40, 20, "windows", RATE, 0), 10 * H), (True, 5 * H))

    def test_elapsed_is_exact(self):
        self.assertEqual(rd.check_eta(progress(25, 14 * 24, "hours", ELAPSED, 100), 200), (False, 100 + 14 * 24 * H))

    def test_audit_takes_the_latest_check_and_ignores_checks_without_minimum(self):
        a = CheckResult("C1", "", NOT_ASSESSABLE, progress=progress(24, 48, "hours", ELAPSED, 0))
        b = CheckResult("C3", "", NOT_ASSESSABLE, progress=progress(5, 20, "cycles", RATE, 0))
        c = CheckResult("C6", "", INFO)
        r = rd.audit_readiness(0, [a, b, c], 24 * H)
        self.assertFalse(r["reached"])
        self.assertEqual(r["eta"], 96 * H)  # C3: 15 weitere Zyklen bei 5 je 24 h
        self.assertEqual([x["check_id"] for x in r["checks"]], ["C1", "C3"])
        r = rd.audit_readiness(0, [a, CheckResult("C3", "", NOT_ASSESSABLE,
                                                  progress=progress(0, 20, "cycles", RATE, 0))], 24 * H)
        self.assertIsNone(r["eta"])  # nicht absehbar, solange ein Wert fehlt

    def test_runner_reports_readiness_per_audit(self):
        from audit_core.runner import run_audits
        s = {"compressor_running": onoff(*[i * 20 * M for i in range(1, 24)]),
             "heartbeat": [(t, t + 100) for t in range(0, 8 * H + 1, 60)]}
        rep = run_audits(s, 0, 8 * H, recorder_keep_days=10, long_term_days=None, heater_kw={},
                         master={"heating_hours": 6279}, events=[{"time": 2 * H, "kind": "heating_curve", "note": ""}])
        ready = rep["readiness"]
        self.assertEqual(set(ready), {"data_basis", "efficiency", "flow_temperature", "capacity", "dhw", "cost"})
        self.assertEqual(ready["data_basis"]["start"], 0)
        self.assertEqual(ready["capacity"]["start"], 2 * H)
        c1 = next(c for c in ready["capacity"]["checks"] if c["check_id"] == "C1")
        self.assertEqual((c1["reached"], c1["eta"]), (False, 2 * H + 14 * 24 * H))
        # Ohne Vor-/Rücklauf haben T1/T3–T5 keine Mindestmenge (Eingang fehlt), ohne Raumfühler auch T6 nicht
        self.assertFalse({"T1", "T3", "T4", "T5", "T6"} & {c["check_id"] for c in ready["flow_temperature"]["checks"]})


class RegistryTest(unittest.TestCase):
    """Umbau auf Audit-Module (docs/audit_modules_design.md): Ergebnis bleibt gleich, Audits laufen auch einzeln."""

    @classmethod
    def setUpClass(cls):
        from tests import synthetic as syn
        cls.syn, cls.series = syn, syn.series()

    def run_with(self, audits=None, roles=None):
        from audit_core.runner import run_audits
        s = self.series if roles is None else {k: v for k, v in self.series.items() if k in roles}
        rep = run_audits(s, self.syn.START, self.syn.END, recorder_keep_days=10, long_term_days=None,
                         heater_kw=self.syn.HEATER_KW, master=self.syn.MASTER, events=self.syn.EVENTS, controls={},
                         tz="Europe/Berlin", audits=audits)
        return __import__("json").loads(__import__("json").dumps(rep, sort_keys=True, default=str))

    def test_provisional_verdict_with_state_before_event(self):
        """F239: Nach dem Ereignis urteilt E3 schon vorläufig; darunter steht das Urteil aus dem Abschnitt davor."""
        e3 = next(c for c in self.run_with(["efficiency"])["audits"]["efficiency"]["checks"] if c["check_id"] == "E3")
        self.assertTrue(e3["provisional"])
        self.assertEqual(e3["verdict"], OK)
        self.assertEqual((e3["before"]["verdict"], e3["before"]["end"]), (OK, self.syn.EVENTS[0]["time"]))
        self.assertEqual(e3["before"]["start"], self.syn.START)
        # ohne Ereignis kein Vergleich
        from audit_core.runner import run_audits
        rep = run_audits(self.series, self.syn.START, self.syn.END, recorder_keep_days=10, long_term_days=None,
                         heater_kw=self.syn.HEATER_KW, master=self.syn.MASTER, events=[], controls={},
                         tz="Europe/Berlin", audits=["efficiency"])
        self.assertTrue(all(c["before"] is None for c in rep["audits"]["efficiency"]["checks"]))

    def test_early_and_mark_provisional(self):
        from audit_core.result import CheckResult, early, mark_provisional, progress
        self.assertEqual((early(7), early(14), early(20), early(1), early(168, 24), early(5, 24)), (3, 5, 7, 1, 56, 5))
        r = CheckResult("X1", "x", OK, progress=progress(3, 7, "days", "full_days", 0))
        mark_provisional(r)
        self.assertTrue(r.provisional)
        r.progress["have"] = 7
        mark_provisional(r)
        self.assertFalse(r.provisional)
        r = CheckResult("X1", "x", NOT_ASSESSABLE, progress=progress(1, 7, "days", "full_days", 0))
        mark_provisional(r)
        self.assertFalse(r.provisional)

    def test_golden_report_unchanged(self):
        """Vergleichsbericht der synthetischen Anlage, erzeugt vor dem Umbau (tests/golden)."""
        golden = __import__("pathlib").Path(__file__).with_name("golden") / "synthetic_report.json"
        # Die Vergleichsdatei kennt nur die ersten vier Audits; Warmwasser und Kosten kamen später dazu, ebenso das
        # Ereignis je Audit (es steht weiter auch unter „section“).
        report = self.run_with(["data_basis", "efficiency", "flow_temperature", "capacity"])
        for audit in report["audits"].values():
            self.assertEqual(audit.pop("event"), None if audit is report["audits"]["data_basis"] else
                             report["section"]["event"])
        self.assertEqual(report, __import__("json").loads(golden.read_text(encoding="utf-8")))

    def test_dhw_section_ignores_heating_events(self):
        """Eine verstellte Heizkreispumpe beginnt den Abschnitt der Audits 1–3 neu, nicht den des Warmwassers."""
        from audit_core.context import Context
        events = [{"time": 5 * H, "kind": "pump_setting"}, {"time": 2 * H, "kind": "dhw_setting"}]
        ctx = Context({}, 0, 10 * H, recorder_keep_days=None, long_term_days=None, heater_kw={}, master={},
                      events=events, controls={}, tz="UTC")
        self.assertEqual((ctx.section_start, ctx.dhw_section_start), (5 * H, 2 * H))
        self.assertEqual(ctx.event_of("dhw")["kind"], "dhw_setting")
        self.assertIsNone(ctx.event_of("window"))

    def test_each_audit_alone_with_only_its_roles(self):
        """Ein Audit allein, nur mit seinen angemeldeten Rollen, urteilt wie im Gesamtlauf."""
        from audit_core.audits import REGISTRY
        full = self.run_with()
        for spec in REGISTRY:
            alone = self.run_with([spec.audit_id], set(spec.roles))
            self.assertEqual(list(alone["audits"]), [spec.audit_id])
            self.assertEqual(alone["audits"][spec.audit_id], full["audits"][spec.audit_id], spec.audit_id)
            self.assertEqual(list(alone["timeline"]["scales"]), [spec.audit_id])
            for a, b in zip(alone["timeline"]["days"], full["timeline"]["days"]):
                self.assertEqual(a[spec.audit_id], b[spec.audit_id], spec.audit_id)

    def test_registry_is_valid(self):
        from audit_core.audits import REGISTRY
        from audit_core.context import ROLE_KEYS
        from audit_core.registry import validate
        validate(REGISTRY, ROLE_KEYS)
        dup = REGISTRY[0].__class__(**{**REGISTRY[0].__dict__, "audit_id": REGISTRY[1].audit_id})
        with self.assertRaises(ValueError):
            validate([dup, REGISTRY[1]], ROLE_KEYS)


class DhwTest(unittest.TestCase):
    """Audit 4 – Warmwasser (Spezifikation 6)."""

    @staticmethod
    def charge(day: int, tank_after: float = 46.0, electricity: float = 1.5, hour: float = 15.0, heat: float = 4.5,
               ideal: float = 0.55, sink: float = 40.0, outdoor: float = 8.0):
        from audit_core.dhw import Charge
        t = day * 24 * H + hour * H
        return Charge(t, t + 40 * M, electricity, heat, ideal, tank_after, sink, outdoor)

    def test_disinfection_has_one_kelvin_tolerance(self):
        self.assertTrue(self.charge(0, 59.0).disinfection)
        self.assertFalse(self.charge(0, 58.5).disinfection)

    def test_efficiency_needs_fine_meter_and_enough_charges(self):
        from audit_core import dhw as w1
        charges = [self.charge(d) for d in range(8)]
        self.assertEqual(w1.check_dhw_efficiency(charges, "high", True, 1.0, 0).verdict, NOT_ASSESSABLE)
        self.assertEqual(w1.check_dhw_efficiency(charges[:2], "high", True, 0.001, 0).verdict, NOT_ASSESSABLE)
        self.assertEqual(w1.check_dhw_efficiency(charges[:3], "high", True, 0.001, 0).verdict, OK)
        r = w1.check_dhw_efficiency(charges, "high", True, 0.001, 0)
        self.assertEqual((r.verdict, r.value, r.details["cop"]), (OK, 0.367, 3.0))
        low = [self.charge(d, ideal=0.3) for d in range(8)]
        self.assertEqual(w1.check_dhw_efficiency(low, "high", True, 0.001, 0).verdict, WARN)
        self.assertEqual(w1.check_dhw_efficiency(low, "high", False, 0.001, 0).verdict, HINT)

    def test_temperature_hygiene_and_efficiency(self):
        from audit_core import dhw as w1
        end = 10 * 24 * H
        cool = [self.charge(d, 45.0) for d in range(9)]
        r = w1.check_dhw_temperature(cool, 0, end, [(0, 45.0)])
        self.assertEqual(r.verdict, HINT)
        self.assertIn("nicht zu sehen", r.text)
        # Aufheizen auf 60 °C zählt nicht in den Median
        r = w1.check_dhw_temperature(cool + [self.charge(8, 60.0, hour=16)], 0, end, [])
        self.assertEqual((r.verdict, r.value), (OK, 45.0))
        self.assertIn("regelmäßig auf 60 °C", r.text)
        self.assertEqual(w1.check_dhw_temperature([self.charge(d, 49.5) for d in range(9)], 0, end, []).verdict, OK)
        self.assertEqual(w1.check_dhw_temperature([self.charge(d, 55.0) for d in range(9)], 0, end, []).verdict, OK)
        r = w1.check_dhw_temperature([self.charge(d, 62.0) for d in range(9)], 0, end, [])
        self.assertEqual(r.verdict, HINT)  # immer auf 62 °C: zu warm, auch wenn jede Ladung über 60 °C liegt
        self.assertIn("Heizstab", r.text)
        always = w1.check_disinfection([self.charge(d, 61.0) for d in range(14)], [], 3.0, 0, 14 * 24 * H)
        self.assertEqual((always.verdict, always.value), (OK, None))

    def test_temperature_below_50_depends_on_regular_disinfection(self):
        from audit_core import dhw as w1
        cool = [self.charge(d, 45.0) for d in range(30)]
        # zu kurz, um das Fehlen zu beurteilen: 7 Tage Abstand + 1 Tag Spielraum
        r = w1.check_dhw_temperature(cool[:8], 0, 8 * 24 * H, [])
        self.assertEqual((r.verdict, r.value, r.progress["need"]), (NOT_ASSESSABLE, 45.0, 192))
        weekly = [self.charge(d, 60.0, hour=16) for d in (2, 9, 16, 23)]
        r = w1.check_dhw_temperature(cool, 0, 30 * 24 * H, [], cool + weekly, 0, 7, 1.8)
        self.assertEqual(r.verdict, OK)
        self.assertIn("alle 1,8 Tage", r.text)
        # letzte Aufheizung zu lange her
        r = w1.check_dhw_temperature(cool, 0, 30 * 24 * H, [], cool + weekly[:2], 0, 7)
        self.assertEqual((r.verdict, r.details["days_since_disinfection"]), (HINT, 20.3))
        # Abstand aus den Stammdaten: alle 15 Tage reicht dann
        fortnight = [self.charge(d, 60.0, hour=16) for d in (5, 20)]
        self.assertEqual(w1.check_dhw_temperature(cool, 0, 30 * 24 * H, [], cool + fortnight, 0, 15).verdict, OK)
        self.assertEqual(w1.check_dhw_temperature(cool, 0, 30 * 24 * H, [], cool + fortnight, 0, 7).verdict, HINT)

    def test_draw_turnover_and_reserve(self):
        from datetime import date, timedelta
        from audit_core import dhw as w1
        from audit_core import household as hh
        end = 10 * 24 * H
        # zwei Ladungen am Tag zu je 3 kWh, 40 min → 6 kWh/Tag geladen; Verlust 46 W ≈ 1,1 kWh/Tag
        charges = [Charge for d in range(10) for Charge in (self.charge(d, 45.0, heat=3.0, hour=7.0),
                                                              self.charge(d, 45.0, heat=3.0, hour=18.0))]
        for c in charges:
            c.tank_before = 39.5
        draw = w1.draw_of(charges, 0, end, 200, 46.0)
        self.assertAlmostEqual(draw.drawn_kwh_day, 6.0 - 1.104, places=3)
        self.assertEqual(round(draw.mixed_l_day), 141)
        self.assertEqual(round(draw.turnover_days, 1), 1.6)
        self.assertEqual((draw.trigger_c, round(draw.charge_kw, 1)), (39.5, 4.5))
        d0 = date(2026, 11, 2)
        dates = [d0 + timedelta(days=i) for i in range(14)]
        persons = hh.parse_persons([{"name": "A", "birth_year": 1985}, {"name": "B", "birth_year": 1987},
                                    {"name": "K", "birth_year": 2016, "presence": "rotation", "weeks_present": 1,
                                     "weeks_absent": 1, "rotation_start": "2026-11-02"}])
        r = w1.check_dhw_draw(draw, 200, persons, dates, 0, end)
        self.assertEqual((r.verdict, r.value, r.details["persons_mean"]), (OK, 1.6, 2.5))
        self.assertEqual(r.details["reserve_l"], {"45": 233, "50": 267, "55": 300})
        self.assertIn("Nachgeladen wird erst", r.text)
        rare = w1.draw_of(charges[::6], 0, end, 200, None)  # 1,2 kWh am Tag → alle 6,7 Tage
        self.assertEqual(w1.check_dhw_draw(rare, 200, [], [], 0, end).verdict, HINT)
        very_rare = w1.draw_of(charges[:1], 0, end, 200, None)
        self.assertEqual(w1.check_dhw_draw(very_rare, 200, [], [], 0, end).verdict, WARN)
        self.assertEqual(w1.check_dhw_draw(draw, None, [], [], 0, end).verdict, NOT_ASSESSABLE)
        r = w1.check_dhw_draw(draw, 200, [], [], 0, 2 * 24 * H)
        self.assertEqual((r.verdict, r.value), (NOT_ASSESSABLE, 1.6))
        self.assertIn("Vorläufig aus 2,0 Tagen", r.text)
        self.assertEqual(w1.check_dhw_draw(draw, 200, [], [], 0, 5 * 24 * H).verdict, OK)
        self.assertEqual(w1.check_dhw_draw(draw, 200, [], [], 0, 12 * H).verdict, NOT_ASSESSABLE)

    def test_disinfection_frequency_and_heater(self):
        from audit_core import dhw as w1
        end = 14 * 24 * H
        daily = [self.charge(d, 46.0, hour=7.0) for d in range(14)]
        found = [self.charge(d, 60.0) for d in (1, 3, 5, 8, 10, 12)]
        heater = [(c.start, c.start + 20 * M) for c in found]
        r = w1.check_disinfection(daily + found, heater, 3.0, 0, end)
        self.assertEqual((r.verdict, r.value, r.details["heater_kwh"]), (HINT, 3.0, 6.0))
        r = w1.check_disinfection(daily + found[:2], heater, 3.0, 0, end)
        self.assertEqual(r.verdict, OK)
        self.assertEqual(w1.check_disinfection(found, heater, 3.0, 0, 6 * 24 * H).verdict, NOT_ASSESSABLE)
        r = w1.check_disinfection(found, heater, 3.0, 0, 10 * 24 * H)  # vorläufig nach einer Woche
        self.assertNotEqual(r.verdict, NOT_ASSESSABLE)
        self.assertLess(r.progress["have"], r.progress["need"])

    def test_quiet_windows_skip_charges_and_draws(self):
        from audit_core import dhw as w1
        tz = "UTC"
        tank = []
        for d in range(4):
            tank += [(d * 24 * H, 45.0), (d * 24 * H + 5 * H, 44.0)]
        tank[-1] = (3 * 24 * H + 2 * H, 30.0)  # Zapfen in Nacht 3
        dhw = onoff(1 * 24 * H + 1 * H, 1 * 24 * H + 2 * H)  # Ladung in Nacht 1
        windows = w1.quiet_windows(tank, dhw, [], [], 0, 4 * 24 * H, tz)
        self.assertEqual([round(a / H) for a, _, _, _ in windows], [0, 48])

    def test_standby_loss_classes(self):
        from audit_core import dhw as w1
        windows = [(d * 24 * H, d * 24 * H + 5 * H, 44.0, 43.0) for d in range(5)]
        r = w1.check_standby_loss(windows, 200, 0)
        # 200 l × 4,153 kJ/(l·K) × 5 K ÷ 25 h = 46 W bei 43,5 °C → 88 W bei 45 K: Klasse D, noch grün
        self.assertEqual((r.verdict, r.value, r.details["erp_class"]), (OK, 88, "D"))
        self.assertIn("Schätzgenauigkeit", r.text)
        leaky = [(a, b, t0, t0 - 2.0) for a, b, t0, _ in windows]
        self.assertEqual(w1.check_standby_loss(leaky, 200, 0).verdict, HINT)
        self.assertEqual(w1.check_standby_loss(windows, None, 0).verdict, NOT_ASSESSABLE)
        self.assertEqual(w1.check_standby_loss(windows[:1], 200, 0).verdict, NOT_ASSESSABLE)
        self.assertEqual(w1.check_standby_loss(windows[:2], 200, 0).verdict, OK)
        self.assertEqual(w1.erp_class(40.0, 200), "A")

    def test_timing_against_warmest_hours(self):
        from audit_core import dhw as w1
        outdoor = []
        for d in range(9):  # nachts 0 °C, 12–18 Uhr 10 °C
            outdoor += [(d * 24 * H, 0.0), (d * 24 * H + 12 * H, 10.0), (d * 24 * H + 18 * H, 0.0)]
        night = [self.charge(d, hour=6.0) for d in range(8)]
        r = w1.check_dhw_timing(night, outdoor, 0, "UTC")
        self.assertEqual(r.verdict, HINT)
        self.assertEqual(r.details["colder_k"], 10.0)
        noon = [self.charge(d, hour=13.0) for d in range(8)]
        self.assertEqual(w1.check_dhw_timing(noon, outdoor, 0, "UTC").value, 0.0)
        from audit_core import household as hh
        morning = hh.parse_persons([{"name": "A", "shower_time": "morning"}, {"name": "B", "shower_time": "evening",
                                                                             "showers_per_week": 3}])
        self.assertIn("morgens geduscht", w1.check_dhw_timing(night, outdoor, 0, "UTC", morning).text)


class ImpactTest(unittest.TestCase):
    """Wirkung der Aktionen in kWh und €/Jahr, Zielkonflikte (Spezifikation 1.10)."""

    class Basis:
        def __init__(self, **kw):
            self.ctx = type("Ctx", (), {"master": kw.pop("master", {})})()
            self.electricity_kwh, self.dhw_electricity_kwh = kw.get("el", 4000.0), kw.get("dhw", 700.0)
            self.heating_electricity_kwh = self.electricity_kwh - self.dhw_electricity_kwh
            self.cop, self.dhw_cop, self.price = kw.get("cop", 3.5), 3.0, kw.get("price", 0.25)

    def test_savings_and_costs_per_check(self):
        from audit_core.impact import annotate
        from audit_core.result import CheckResult
        rs = [CheckResult("T1", "buffer_flow_loss", HINT, 3.5, "K", action={}),
              CheckResult("W5", "dhw_timing", HINT, 10.8, "%", action={}),
              CheckResult("W2", "dhw_temperature", HINT, 45.0, "°C", details={"interval_days": 7}, action={}),
              CheckResult("C5", "backup_heater_share", HINT, 3.0, "%", action={}),
              CheckResult("K3", "tariff_benefit", HINT, -40, "€/a", action={}),
              CheckResult("E3", "carnot_efficiency", OK, 0.4, "", action=None)]
        annotate(rs, self.Basis(master={"dhw_tank_volume_l": 200}))
        t1, w5, w2, c5, k3, e3 = (r.action for r in rs)
        self.assertEqual(t1["impact"], {"kwh_year": round(3300 * 2 * 0.025), "eur_year": round(165 * 0.25),
                                        "basis": t1["impact"]["basis"]})
        self.assertIn("Abgleich", t1["conflicts"][0])
        self.assertEqual(w5["impact"]["kwh_year"], round(700 * 0.108))
        self.assertIn("K4", w5["conflicts"][1])
        # Legionellenschaltung alle 7 Tage: 52 × 200 l × 15 K → kostet
        self.assertEqual(w2["impact"]["kwh_year"], -round(365 / 7 * 200 * 4.153 * 15 / 3600))
        self.assertLess(w2["impact"]["eur_year"], 0)
        self.assertEqual(c5["impact"]["kwh_year"], round(4000 * 0.01 * (1 - 1 / 3.5)))
        self.assertEqual((k3["impact"]["kwh_year"], k3["impact"]["eur_year"]), (None, 40))
        self.assertIsNone(e3)

    def test_without_price_only_kwh(self):
        from audit_core.impact import annotate
        from audit_core.result import CheckResult
        r = CheckResult("T6", "heating_curve_headroom", HINT, 21.0, "°C", action={})
        annotate([r], self.Basis(price=None))
        self.assertEqual((r.action["impact"]["kwh_year"], r.action["impact"]["eur_year"]), (round(3300 * 0.025), None))


class HouseholdTest(unittest.TestCase):
    """Haushalt: Anwesenheit und erwarteter Warmwasserbedarf."""

    def test_presence_patterns(self):
        from datetime import date
        from audit_core import household as hh
        rot, days_, share = hh.parse_persons([
            {"name": "K", "presence": "rotation", "weeks_present": 2, "weeks_absent": 1, "rotation_start": "2026-11-02"},
            {"name": "W", "presence": "weekdays", "weekdays": ["fri", "sat", "sun"], "every_n_weeks": 2,
             "rotation_start": "2026-11-02"},
            {"name": "S", "presence": "share", "share_pct": 30}])
        self.assertEqual([rot.presence_on(date(2026, 11, d)) for d in (2, 15, 16, 23)], [1, 1, 0, 1])
        self.assertEqual([days_.presence_on(date(2026, 11, d)) for d in (6, 9, 13, 20)], [1, 0, 0, 1])
        self.assertEqual(share.presence_on(date(2026, 11, 2)), 0.3)
        # vor dem Anker zählt das Muster rückwärts weiter
        self.assertEqual(rot.presence_on(date(2026, 10, 26)), 0)

    def test_habits_by_age_and_expected_demand(self):
        from datetime import date
        from audit_core import household as hh
        toddler, adult, custom = hh.parse_persons([{"name": "T", "birth_year": 2023}, {"name": "A"},
                                                   {"name": "C", "showers_per_week": 14, "baths_per_week": 0}])
        on = date(2026, 11, 2)
        self.assertEqual(toddler.habits(on), (0.0, 2.0))
        self.assertAlmostEqual(toddler.mixed_l_per_day(on), 2 * 60 / 7 + 10)
        self.assertEqual(adult.habits(on), (6.0, 0.0))
        self.assertAlmostEqual(custom.mixed_l_per_day(on), 14 * 40 / 7 + 10)
        self.assertIsNone(hh.expected_mixed_l([], [on]))
        self.assertEqual(round(hh.reserve_mixed_l(200, 45)), 233)
        self.assertEqual(hh.parse_persons([{"birth_year": "x"}]), [])


class CostTest(unittest.TestCase):
    """Audit 5 – Kosten (Spezifikation 7)."""

    MASTER = {"tariff_price": 0.25, "tariff_base_fee": 73.0, "household_price": 0.32, "reference_fuel_price": 0.12,
              "reference_efficiency": 0.9, "heating_degree_days": 3500}

    @staticmethod
    def rows(n: int, electricity: float = 10.0, heat: float = 35.0, start_day: int = 1):
        from datetime import date, timedelta
        d0 = date(2026, 1, 1)
        return [{"day": (d0 + timedelta(days=start_day + i)).isoformat(), "electricity_kwh": electricity,
                 "heat_kwh": heat} for i in range(n)]

    def test_energy_cost_uses_price_at_each_step(self):
        from audit_core.cost import energy_cost
        meter = [(0, 100.0), (H, 101.0), (2 * H, 103.0)]
        price = [(0, 0.20), (H, 0.40)]
        self.assertAlmostEqual(energy_cost(meter, price, 0, 2 * H), 0.2 + 0.8)
        self.assertIsNone(energy_cost(meter, [(H, 0.4)], 0, 2 * H))

    def test_heat_price_against_reference(self):
        from audit_core import cost as k1
        rows = self.rows(7)
        costs = {r["day"]: r["electricity_kwh"] * 0.25 for r in rows}
        r = k1.check_heat_price(rows, costs, self.MASTER, 0)
        # (7 × 2,50 € + 73 € × 7/365) ÷ 245 kWh = 7,7 ct; Gas 12 ct ÷ 0,9 = 13,3 ct
        self.assertEqual((r.verdict, r.value, r.details["reference_ct"]), (OK, 7.7, 13.3))
        expensive = {k: v * 2.5 for k, v in costs.items()}
        self.assertEqual(k1.check_heat_price(rows, expensive, self.MASTER, 0).verdict, HINT)
        self.assertEqual(k1.check_heat_price(rows, costs, {"tariff_price": 0.25}, 0).verdict, INFO)
        self.assertEqual(k1.check_heat_price(rows[:2], costs, self.MASTER, 0).verdict, NOT_ASSESSABLE)
        self.assertEqual(k1.check_heat_price(rows[:3], costs, self.MASTER, 0).verdict, OK)
        self.assertEqual(k1.check_heat_price(rows, {}, self.MASTER, 0).verdict, NOT_ASSESSABLE)

    def test_projection_splits_base_load_and_degree_days(self):
        from audit_core import cost as k1
        from audit_core import days
        tz = "Europe/Berlin"
        rows, outdoor = [], []
        for i in range(14):
            mean = -2.0 + i  # Gradtage 22 … 9
            r = self.rows(1, start_day=i)[0]
            g = 20 - mean
            r["electricity_kwh"], r["heat_kwh"] = 3.0 + 0.5 * g, 10.0 + 1.6 * g
            rows.append(r)
            outdoor.append((days.parse(r["day"], tz), mean))
        year = k1.project_year(rows, outdoor, tz, 3500)
        self.assertEqual(year["method"], "fit")
        self.assertAlmostEqual(year["electricity_kwh"], 365 * 3 + 0.5 * 3500)
        costs = {r["day"]: r["electricity_kwh"] * 0.25 for r in rows}
        r = k1.check_annual_cost(rows, outdoor, costs, self.MASTER, tz, 0)
        self.assertEqual((r.verdict, r.value), (INFO, round(2845 * 0.25 + 73)))
        self.assertIn("Ersparnis", r.text)
        t = k1.check_tariff(r, self.MASTER, False)
        self.assertEqual((t.verdict, t.value), (OK, round(0.07 * 2845 - 73)))
        self.assertEqual(k1.check_tariff(r, self.MASTER | {"tariff_base_fee": 300}, False).verdict, HINT)
        self.assertEqual(k1.check_tariff(r, self.MASTER, True).verdict, NOT_ASSESSABLE)
        self.assertEqual(k1.degree_days(16.0), 0.0)
        # Wohnfläche und Personen: 2845 kWh ÷ (1,2 × 100 m²) ≈ 24 kWh/m² → Klasse A+
        r = k1.check_annual_cost(rows, outdoor, costs, self.MASTER | {"living_area_m2": 100}, tz, 0, 3.0)
        self.assertEqual((r.details["electricity_kwh_m2"], r.details["energy_class"]), (28, "A+"))
        self.assertEqual(r.details["cost_per_person_eur"], round((2845 * 0.25 + 73) / 3))
        self.assertIn("Klasse A+", r.text)
        self.assertEqual([k1.energy_class(x) for x in (29, 30, 99, 250)], ["A+", "A", "C", "H"])

    def test_price_timing_and_grid_lock(self):
        from audit_core import cost as k1
        week = 7 * 24 * H
        price = [(i * H, 0.40 if i % 2 else 0.20) for i in range(7 * 24 + 1)]
        meter = [(i * H, 100.0 + i // 2) for i in range(7 * 24 + 1)]  # nur in teuren Stunden Strom
        r = k1.check_price_timing(meter, price, 0, week)
        self.assertEqual(r.verdict, HINT)
        self.assertEqual(k1.check_price_timing(meter, [], 0, week).verdict, NOT_ASSESSABLE)
        late = k1.check_price_timing(meter, price[2:], 0, week + 2 * H)  # Preis erst ab 2 Uhr aufgezeichnet
        self.assertEqual(late.verdict, HINT)
        locks = onoff(*[t for d in range(7) for t in (d * 24 * H + 12 * H, d * 24 * H + 13 * H)])
        self.assertEqual(k1.check_grid_lock(locks, [], 0, week).verdict, OK)
        heater = [(12 * H + 3600, 12 * H + 2 * 3600)]
        r = k1.check_grid_lock(locks, heater, 0, week)
        self.assertEqual((r.verdict, r.details["heater_after_h"]), (HINT, 1.0))
        long = onoff(12 * H, 15 * H)  # Dauer allein ist seit § 14a kein Befund
        r = k1.check_grid_lock(long, [], 0, week)
        self.assertEqual((r.verdict, r.details["longest_h"]), (OK, 3.0))
