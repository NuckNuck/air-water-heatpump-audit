"""Contract-Tests: Tage aus der Langzeitstatistik (Spezifikation 1.11, Issue #19).

Grundlage ist allein der Vertrag in docs/specification.md 1.11 und die Schnittstelle von run_audits/timeline.merge.
Anlage: die synthetische Anlage aus tests/synthetic.py (zehn Tage Rohdaten, ein Ereignis an Tag 6).
"""

from __future__ import annotations

import json
import unittest

from audit_core import days
from audit_core import timeline as tl
from audit_core.runner import run_audits
from audit_core.result import NOT_ASSESSABLE
from tests import synthetic as syn

TZ = "Europe/Berlin"
CONTROLLER_FACTOR = 0.8  # Steuerung zeigt die eigene Wärme ÷ 0,8 an → Korrekturfaktor 0,8
STAT_DAY_KWH = 10.0
STAT_DAY_CONTROLLER_HEAT = 40.0
STAT_DAY_OUTDOOR = 1.5
STAT_DAYS_BEFORE = 20
SERIES = syn.series()


def run(statistics=None, events=None, audits=None, series=None, master=None) -> dict:
    rep = run_audits(series or SERIES, syn.START, syn.END, recorder_keep_days=10, long_term_days=None,
                     heater_kw=syn.HEATER_KW, master=master or syn.MASTER, events=events, controls={}, tz=TZ,
                     audits=audits, statistics=statistics)
    return json.loads(json.dumps(rep, sort_keys=True, default=str))


def window_heat() -> dict[str, float]:
    """Selbst gerechnete Wärme der gültigen Tage im Fenster (aus dem Zeitstrahl ohne Statistik)."""
    return {d["day"]: d["efficiency"]["heat_kwh"] for d in run(audits=["efficiency"])["timeline"]["days"]
            if d["efficiency"].get("heat_kwh") is not None}


WINDOW_HEAT = window_heat()
BEFORE = [days.label(syn.START - (i + 1) * 86400 + 3600, TZ) for i in range(STAT_DAYS_BEFORE)]


def stats(*, window_days=None, before=None, electricity=STAT_DAY_KWH, heat=STAT_DAY_CONTROLLER_HEAT) -> dict:
    """Tageswerte wie aus der Langzeitstatistik: Steuerungswärme im Fenster = eigene Wärme ÷ CONTROLLER_FACTOR."""
    window = list(WINDOW_HEAT)[:window_days] if window_days is not None else list(WINDOW_HEAT)
    before = BEFORE if before is None else before
    return {"electricity_kwh": {d: electricity for d in before},
            "controller_heat_kwh": {d: WINDOW_HEAT[d] / CONTROLLER_FACTOR for d in window} | {d: heat for d in before},
            "outdoor_mean": {d: STAT_DAY_OUTDOOR for d in before}}


def stat_days(report: dict) -> list[dict]:
    return [d for d in report["timeline"]["days"] if d.get("source") == "statistics"]


class StatisticDaysTest(unittest.TestCase):
    def test_days_before_window_appear_in_timeline_marked_as_statistics(self):
        report = run(stats(), audits=["efficiency", "cost"])
        self.assertEqual(sorted(d["day"] for d in stat_days(report)), sorted(BEFORE))

    def test_heat_is_controller_heat_times_factor_from_window_days(self):
        report = run(stats(), audits=["efficiency"])
        for d in stat_days(report):
            self.assertAlmostEqual(d["efficiency"]["heat_kwh"], STAT_DAY_CONTROLLER_HEAT * CONTROLLER_FACTOR, places=1)

    def test_cop_is_corrected_heat_over_electricity(self):
        report = run(stats(), audits=["efficiency"])
        for d in stat_days(report):
            p = d["efficiency"]
            self.assertAlmostEqual(p["cop"], p["heat_kwh"] / p["electricity_kwh"], places=2)

    def test_statistic_day_has_no_carnot_efficiency(self):
        report = run(stats(), audits=["efficiency"])
        for d in stat_days(report):
            self.assertIsNone(d["efficiency"]["value"])
            self.assertEqual(d["efficiency"]["verdict"], NOT_ASSESSABLE)

    def test_fewer_than_seven_factor_days_give_no_statistic_days(self):
        report = run(stats(window_days=6), audits=["efficiency", "cost"])
        self.assertEqual(stat_days(report), [])

    def test_seven_factor_days_are_enough(self):
        report = run(stats(window_days=7), audits=["efficiency"])
        self.assertNotEqual(stat_days(report), [])

    def test_day_below_two_kwh_is_not_valid(self):
        report = run(stats(electricity=1.99), audits=["efficiency"])
        self.assertEqual(stat_days(report), [])

    def test_day_with_exactly_two_kwh_is_valid(self):
        report = run(stats(electricity=2.0), audits=["efficiency"])
        self.assertEqual(len(stat_days(report)), STAT_DAYS_BEFORE)

    def test_day_without_controller_heat_is_not_valid(self):
        report = run(stats(heat=0.0), audits=["efficiency"])
        self.assertEqual(stat_days(report), [])

    def test_window_days_in_statistics_stay_raw_days(self):
        window = {d: STAT_DAY_KWH for d in WINDOW_HEAT}
        s = stats()
        s["electricity_kwh"] |= window
        report = run(s, audits=["efficiency"])
        self.assertTrue(set(WINDOW_HEAT).isdisjoint(d["day"] for d in stat_days(report)))

    def test_cost_is_electricity_times_tariff_price(self):
        report = run(stats(), audits=["cost"])
        for d in stat_days(report):
            self.assertAlmostEqual(d["cost"]["cost_eur"], STAT_DAY_KWH * syn.MASTER["tariff_price"], places=2)

    def test_dynamic_price_uses_mean_paid_price_of_window(self):
        dynamic_price = 0.31
        series = SERIES | {"price_signal": [(syn.START - 86400, dynamic_price)]}
        report = run(stats(), audits=["cost"], series=series)
        for d in stat_days(report):
            self.assertAlmostEqual(d["cost"]["cost_eur"], STAT_DAY_KWH * dynamic_price, places=2)

    def test_audits_without_statistics_support_are_not_assessable(self):
        report = run(stats(), audits=["data_basis", "efficiency"])
        for d in stat_days(report):
            self.assertEqual(d["data_basis"], {"value": None, "verdict": NOT_ASSESSABLE})


class StatisticDaysUsageTest(unittest.TestCase):
    """F295: Statistik-Tage zählen für K2, nicht für die übrigen Prüfungen; Ereignisse trennen sie nicht (#39)."""

    @staticmethod
    def check(report: dict, audit: str, check_id: str) -> dict:
        return next(c for c in report["audits"][audit]["checks"] if c["check_id"] == check_id)

    def test_annual_projection_counts_statistic_days_without_event(self):
        without, with_stats = run(audits=["cost"]), run(stats(), audits=["cost"])
        self.assertGreater(self.check(with_stats, "cost", "K2")["progress"]["have"],
                           self.check(without, "cost", "K2")["progress"]["have"])

    def test_annual_projection_keeps_statistic_days_across_events(self):
        """#39: Ein Ereignis trennt nicht mehr; K2 rechnet mit denselben Statistik-Tagen wie ohne Ereignis."""
        plain = run(stats(), audits=["cost"])
        with_event = run(stats(), events=syn.EVENTS, audits=["cost"])
        self.assertEqual(self.check(with_event, "cost", "K2"), self.check(plain, "cost", "K2"))

    def test_efficiency_checks_use_raw_days_only(self):
        without, with_stats = run(audits=["efficiency"]), run(stats(), audits=["efficiency"])
        self.assertEqual(with_stats["audits"]["efficiency"], without["audits"]["efficiency"])

    def test_history_depth_names_statistic_days_without_changing_verdict(self):
        without, with_stats = run(audits=["data_basis"]), run(stats(), audits=["data_basis"])
        d1, d1_stats = self.check(without, "data_basis", "D1"), self.check(with_stats, "data_basis", "D1")
        self.assertEqual(d1_stats["verdict"], d1["verdict"])
        self.assertEqual(d1_stats["details"]["statistics_days"], STAT_DAYS_BEFORE)
        self.assertIn("Langzeitstatistik", d1_stats["text"])


class StatisticDaysMergeTest(unittest.TestCase):
    """Ein gespeicherter Tag aus Rohdaten wird nie durch einen Statistik-Tag ersetzt."""

    RAW_DAY = {"day": "2026-01-01", "efficiency": {"value": 0.4}}
    STAT_DAY = {"day": "2026-01-01", "source": "statistics", "efficiency": {"value": None, "cop": 3.0}}

    def test_statistic_day_does_not_replace_stored_raw_day(self):
        self.assertEqual(tl.merge([self.RAW_DAY], [self.STAT_DAY]), [self.RAW_DAY])

    def test_raw_day_replaces_stored_statistic_day(self):
        self.assertEqual(tl.merge([self.STAT_DAY], [self.RAW_DAY]), [self.RAW_DAY])

    def test_statistic_day_replaces_stored_statistic_day(self):
        newer = self.STAT_DAY | {"efficiency": {"value": None, "cop": 3.5}}
        self.assertEqual(tl.merge([self.STAT_DAY], [newer]), [newer])


if __name__ == "__main__":
    unittest.main()
