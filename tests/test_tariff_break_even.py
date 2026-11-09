"""Contract-Tests K3: Ab wann lohnt sich der eigene Zähler? (Spezifikation 7.2.1)"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "air_water_heatpump_audit"))

from audit_core import cost as k1  # noqa: E402
from audit_core.result import HINT, INFO, OK, CheckResult  # noqa: E402

ANNUAL_ELECTRICITY_KWH = 6000.0
TARIFF = 0.25          # €/kWh Wärmepumpentarif
HOUSEHOLD = 0.28       # €/kWh Haushaltsstrom
METER_FEE_PER_YEAR = 200.0
BASE_FEE_PER_YEAR = 100.0
FIXED = METER_FEE_PER_YEAR + BASE_FEE_PER_YEAR


def annual(kwh: float = ANNUAL_ELECTRICITY_KWH) -> CheckResult:
    return CheckResult("K2", "annual_cost", INFO, details={"electricity_kwh": kwh})


def master(**kw) -> dict:
    return {"heat_pump_meter": "separate_meter", "tariff_price": TARIFF, "household_price": HOUSEHOLD,
            "tariff_base_fee": BASE_FEE_PER_YEAR, "meter_fee": METER_FEE_PER_YEAR} | kw


class TariffBreakEvenTest(unittest.TestCase):

    def test_verdict_gives_prices_in_cent(self):
        d = k1.check_tariff(annual(), master(), False).details
        self.assertAlmostEqual(d["tariff_ct"], 100 * TARIFF)
        self.assertAlmostEqual(d["household_ct"], 100 * HOUSEHOLD)

    def test_break_even_household_price_makes_benefit_zero(self):
        d = k1.check_tariff(annual(), master(), False).details
        at_break_even = k1.check_tariff(annual(), master(household_price=d["break_even_household_ct"] / 100), False)
        self.assertAlmostEqual(at_break_even.value, 0, delta=ANNUAL_ELECTRICITY_KWH * 0.0005)

    def test_break_even_household_price_has_one_decimal(self):
        d = k1.check_tariff(annual(7000.0), master(), False).details
        self.assertEqual(d["break_even_household_ct"], round(d["break_even_household_ct"], 1))

    def test_break_even_gap_is_household_minus_tariff_at_break_even(self):
        d = k1.check_tariff(annual(), master(), False).details
        self.assertAlmostEqual(d["tariff_ct"] + d["break_even_gap_ct"], d["break_even_household_ct"], delta=0.1)

    def test_break_even_gap_does_not_depend_on_price_level(self):
        price_rise = 0.05
        cheap = k1.check_tariff(annual(), master(), False).details
        dear = k1.check_tariff(annual(), master(tariff_price=TARIFF + price_rise,
                                                 household_price=HOUSEHOLD + price_rise), False).details
        self.assertEqual(cheap["break_even_gap_ct"], dear["break_even_gap_ct"])

    def test_no_fixed_costs_gives_zero_gap(self):
        d = k1.check_tariff(annual(), master(tariff_base_fee=0, meter_fee=0), False).details
        self.assertEqual(d["break_even_gap_ct"], 0)

    def test_text_names_needed_and_current_gap(self):
        self.assertIn("ct/kWh Abstand zum Haushaltsstrom, heute", k1.check_tariff(annual(), master(), False).text)

    def test_break_even_kwh_makes_benefit_zero(self):
        d = k1.check_tariff(annual(), master(), False).details
        at_break_even = k1.check_tariff(annual(d["break_even_kwh"]), master(), False)
        self.assertAlmostEqual(at_break_even.value, 0, delta=1)

    def test_consumption_above_break_even_is_ok_below_is_hint(self):
        d = k1.check_tariff(annual(), master(), False).details
        above = k1.check_tariff(annual(d["break_even_kwh"] * 1.1), master(), False).verdict
        below = k1.check_tariff(annual(d["break_even_kwh"] * 0.9), master(), False).verdict
        self.assertEqual((above, below), (OK, HINT))

    def test_no_fixed_costs_gives_tariff_price_and_zero_kwh(self):
        d = k1.check_tariff(annual(), master(tariff_base_fee=0, meter_fee=0), False).details
        self.assertEqual((d["break_even_household_ct"], d["break_even_kwh"]), (100 * TARIFF, 0))

    def test_household_not_dearer_than_tariff_gives_no_break_even_kwh(self):
        r = k1.check_tariff(annual(), master(household_price=TARIFF), False)
        self.assertIsNone(r.details["break_even_kwh"])
        self.assertIn("bei keinem Verbrauch", r.text)

    def test_text_names_both_limits(self):
        r = k1.check_tariff(annual(), master(), False)
        self.assertIn("ct/kWh Haushaltsstrom", r.text)
        self.assertIn("kWh Wärmepumpenstrom im Jahr", r.text)

    def test_reduced_grid_fee_set_text_mentions_section_14a(self):
        self.assertIn("§ 14a EnWG", k1.check_tariff(annual(), master(reduced_grid_fee=True), False).text)

    def test_reduced_grid_fee_unset_text_has_no_section_14a(self):
        self.assertNotIn("§ 14a", k1.check_tariff(annual(), master(), False).text)

    def test_details_give_annual_electricity_and_fixed_costs(self):
        d = k1.check_tariff(annual(), master(), False).details
        self.assertEqual((d["electricity_kwh"], d["base_fee_eur"]), (ANNUAL_ELECTRICITY_KWH, FIXED))


if __name__ == "__main__":
    unittest.main()
