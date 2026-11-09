"""Contract-Tests zu Spezifikation 4.3: Arbeitszahl der letzten 365 Tage."""

import unittest

from audit_core.timeline import rolling_cop

TODAY = "2026-11-09"
FIRST_DAY_OF_YEAR = "2025-11-09"  # 365 Tage vor heute
DAY_BEFORE_YEAR = "2025-11-08"


def day(label: str, heat: float | None, electricity: float | None, **extra) -> dict:
    point = {"value": None, "verdict": "not_assessable"}
    if electricity is not None:
        point |= {"heat_kwh": heat, "electricity_kwh": electricity, "cop": 0, "cop_raw": 0}
    return {"day": label, "start": 0, "end": 0, "efficiency": point} | extra


class RollingCop(unittest.TestCase):
    def test_days_in_range_ratio_of_sums(self):
        result = rolling_cop([day("2026-11-07", 30.0, 10.0), day("2026-11-08", 10.0, 10.0)], TODAY)
        self.assertEqual(result["cop"], 2.0)  # 40 ÷ 20, nicht Mittel der Tageswerte (3,0 und 1,0)
        self.assertEqual((result["heat_kwh"], result["electricity_kwh"]), (40.0, 20.0))

    def test_cop_rounded_to_two_decimals(self):
        result = rolling_cop([day("2026-11-08", 10.0, 3.0)], TODAY)
        self.assertEqual(result["cop"], 3.33)

    def test_today_does_not_count(self):
        result = rolling_cop([day("2026-11-08", 30.0, 10.0), day(TODAY, 99.0, 1.0)], TODAY)
        self.assertEqual((result["days"], result["last_day"]), (1, "2026-11-08"))

    def test_first_day_of_year_counts_and_day_before_does_not(self):
        result = rolling_cop([day(DAY_BEFORE_YEAR, 99.0, 1.0), day(FIRST_DAY_OF_YEAR, 30.0, 10.0)], TODAY)
        self.assertEqual((result["days"], result["first_day"], result["cop"]), (1, FIRST_DAY_OF_YEAR, 3.0))

    def test_complete_once_first_day_is_a_year_ago(self):
        result = rolling_cop([day(FIRST_DAY_OF_YEAR, 30.0, 10.0), day("2026-11-08", 30.0, 10.0)], TODAY)
        self.assertTrue(result["complete"])

    def test_partial_year_not_complete(self):
        result = rolling_cop([day("2026-10-25", 30.0, 10.0), day("2026-11-08", 30.0, 10.0)], TODAY)
        self.assertEqual((result["complete"], result["days"], result["first_day"]), (False, 2, "2026-10-25"))

    def test_days_without_electricity_are_skipped(self):
        days_ = [day("2026-11-06", 5.0, 0.0), day("2026-11-07", None, None), day("2026-11-08", 30.0, 10.0),
                 {"day": "2026-11-05", "start": 0, "end": 0}]
        result = rolling_cop(days_, TODAY)
        self.assertEqual((result["days"], result["cop"]), (1, 3.0))

    def test_statistics_days_count(self):
        result = rolling_cop([day("2026-10-01", 20.0, 10.0, source="statistics"), day("2026-11-08", 40.0, 10.0)], TODAY)
        self.assertEqual((result["days"], result["cop"]), (2, 3.0))

    def test_no_usable_day_returns_none(self):
        self.assertIsNone(rolling_cop([day(TODAY, 30.0, 10.0), day("2026-11-08", None, None)], TODAY))

    def test_empty_timeline_returns_none(self):
        self.assertIsNone(rolling_cop([], TODAY))


if __name__ == "__main__":
    unittest.main()
