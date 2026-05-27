"""
think4u/tests/test_annual_leave.py

WP-05 規格的 7 個 unit test。執行：
    python manage.py test think4u.tests.test_annual_leave
"""

from datetime import date
from django.test import TestCase

from think4u.services.annual_leave_calculator import (
    calculate_jan1_allocation,
    calculate_six_month_grant,
    calculate_prorated_days,
    days_by_full_years,
    get_service_months,
)


class TestJan1Allocation(TestCase):
    """規格表 7 個 case + 邊界"""

    def test_under_6_months(self):
        # 到職 2024/08/01，2025/1/1 年資 5 個月 → 0 天
        result = calculate_jan1_allocation(date(2024, 8, 1), 2025)
        self.assertEqual(result["days"], 0)

    def test_6_months_prorated_round_up(self):
        # 到職 2024/07/01，2025/1/1 年資 6 個月 → 比例 = 7 × 6/12 = 3.5 → 進位 4 天
        result = calculate_jan1_allocation(date(2024, 7, 1), 2025)
        self.assertEqual(result["days"], 4)

    def test_9_months_prorated_round_down(self):
        # 到職 2024/04/01，2025/1/1 年資 9 個月 → 比例 = 7 × 9/12 = 5.25 → 捨去 5 天
        result = calculate_jan1_allocation(date(2024, 4, 1), 2025)
        self.assertEqual(result["days"], 5)

    def test_1_year(self):
        # 到職 2024/01/01，2025/1/1 滿 1 年 → 7 天
        result = calculate_jan1_allocation(date(2024, 1, 1), 2025)
        self.assertEqual(result["days"], 7)

    def test_10_years(self):
        # 到職 2015/01/01，2025/1/1 滿 10 年 → 16 天
        result = calculate_jan1_allocation(date(2015, 1, 1), 2025)
        self.assertEqual(result["days"], 16)

    def test_20_years_capped(self):
        # 到職 2005/01/01，2025/1/1 滿 20 年 → 16 + (20-10) = 26 天
        result = calculate_jan1_allocation(date(2005, 1, 1), 2025)
        self.assertEqual(result["days"], 26)

    def test_30_years_cap(self):
        # 到職 1990/01/01，2025/1/1 滿 35 年 → 16 + 25 = 41 → capped 30
        result = calculate_jan1_allocation(date(1990, 1, 1), 2025)
        self.assertEqual(result["days"], 30)


class TestSixMonthGrant(TestCase):
    def test_should_grant_on_anniversary(self):
        # 到職 2025-01-15，今天 2025-07-15 → 應給
        r = calculate_six_month_grant(date(2025, 1, 15), date(2025, 7, 15))
        self.assertTrue(r["should_grant"])
        self.assertEqual(r["days"], 3)

    def test_should_not_grant_when_not_anniversary(self):
        r = calculate_six_month_grant(date(2025, 1, 15), date(2025, 7, 14))
        self.assertFalse(r["should_grant"])

    def test_should_not_grant_when_already_past(self):
        r = calculate_six_month_grant(date(2025, 1, 15), date(2025, 7, 16))
        self.assertFalse(r["should_grant"])


class TestProratedDays(TestCase):
    def test_round_half_up(self):
        # 7 × 6/12 = 3.5 → 4
        self.assertEqual(calculate_prorated_days(7, 6), 4)

    def test_round_down(self):
        # 7 × 9/12 = 5.25 → 5
        self.assertEqual(calculate_prorated_days(7, 9), 5)

    def test_zero(self):
        self.assertEqual(calculate_prorated_days(7, 0), 0)


class TestDaysByFullYears(TestCase):
    def test_tiered(self):
        self.assertEqual(days_by_full_years(1), 7)
        self.assertEqual(days_by_full_years(2), 10)
        self.assertEqual(days_by_full_years(4), 14)
        self.assertEqual(days_by_full_years(5), 15)
        self.assertEqual(days_by_full_years(10), 16)
        self.assertEqual(days_by_full_years(11), 17)
        self.assertEqual(days_by_full_years(25), 30)  # capped


class TestServiceMonths(TestCase):
    def test_exact_months(self):
        self.assertEqual(get_service_months(date(2024, 1, 1), date(2025, 1, 1)), 12)
        self.assertEqual(get_service_months(date(2024, 1, 15), date(2024, 7, 15)), 6)
        self.assertEqual(get_service_months(date(2024, 1, 15), date(2024, 7, 14)), 5)
