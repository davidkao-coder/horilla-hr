"""
think4u/services/annual_leave_calculator.py

WP-05 台灣勞基法第 38 條 — 歷年制特休計算邏輯。

公司決策三原則（已寫入程式）：
1. 比例天數 ≥ 0.5 進位，< 0.5 捨去
2. 到職未滿 6 個月遇 1/1：給 0 天；滿 6 個月當天另外補給 3 天
3. 年底未休完允許遞延至隔年，最多遞延 1 年；隔年 12/31 未休則歸零
"""

import math
from datetime import date

from dateutil.relativedelta import relativedelta


# ---------------------------------------------------------------------------
# 基礎工具
# ---------------------------------------------------------------------------


def get_service_months(hire_date: date, reference_date: date) -> int:
    """到職滿幾個整月（不足月不計）"""
    if hire_date is None or reference_date is None:
        return 0
    if reference_date < hire_date:
        return 0
    delta = relativedelta(reference_date, hire_date)
    return delta.years * 12 + delta.months


def calculate_prorated_days(full_days: int, remaining_months: int) -> int:
    """
    比例計算：≥ 0.5 進位（即四捨五入但對 0.5 規則統一進位）。

    full_days：年資 1 年時應給的天數（勞基法為 7）
    remaining_months：到職月起算當年度還剩幾個月
    """
    if remaining_months <= 0:
        return 0
    ratio = remaining_months / 12.0
    raw = full_days * ratio
    # math.floor(raw + 0.5) — 對 0.5 進位
    return math.floor(raw + 0.5)


# ---------------------------------------------------------------------------
# 年資 ≥ 1 年 級距表
# ---------------------------------------------------------------------------


def days_by_full_years(service_years: int) -> int:
    """依年資年數查級距：勞基法第 38 條"""
    if service_years < 1:
        return 0
    if service_years < 2:
        return 7
    if service_years < 3:
        return 10
    if service_years < 5:
        return 14
    if service_years < 10:
        return 15
    # 滿 10 年起，每年 +1，上限 30
    return min(16 + (service_years - 10), 30)


# ---------------------------------------------------------------------------
# 主計算入口
# ---------------------------------------------------------------------------


def calculate_jan1_allocation(hire_date: date, reset_year: int) -> dict:
    """
    每年 1/1 應給天數計算。
    回傳 {'days': int, 'source': str, 'note': str}
    """
    reference_date = date(reset_year, 1, 1)
    service_months = get_service_months(hire_date, reference_date)

    if service_months < 6:
        return {
            "days": 0,
            "source": "annual_reset",
            "note": f"年資 {service_months} 個月未滿 6 個月，1/1 不給假",
        }

    if service_months < 12:
        # 比例給假
        # 到職月份 = hire_date.month；計算當年從到職月起算的剩餘月數
        # 規格：剩餘月數 = 12 - 到職月 + 1
        remaining_months = 12 - hire_date.month + 1
        days = calculate_prorated_days(7, remaining_months)
        return {
            "days": days,
            "source": "annual_reset",
            "note": f"年資 {service_months} 個月 → 比例 {remaining_months}/12 → {days} 天",
        }

    # 年資 ≥ 1 年
    service_years = service_months // 12
    days = days_by_full_years(service_years)
    return {
        "days": days,
        "source": "annual_reset",
        "note": f"年資 {service_years} 年 → {days} 天",
    }


def calculate_six_month_grant(hire_date: date, today: date) -> dict:
    """
    每日 cron 用：偵測員工今天剛滿 6 個月，給 3 天。
    only 給的條件：reference_date - hire_date = 滿 6 個月
    回傳 {'should_grant': bool, 'days': 3, 'effective_from': today, 'note': ...}
    """
    if not hire_date:
        return {"should_grant": False, "days": 0, "note": "無到職日"}

    six_month_anniversary = hire_date + relativedelta(months=6)
    if today != six_month_anniversary:
        return {
            "should_grant": False,
            "days": 0,
            "note": f"今日 {today} 非到職滿 6 個月（應為 {six_month_anniversary}）",
        }
    return {
        "should_grant": True,
        "days": 3,
        "source": "six_month_grant",
        "effective_from": today,
        "note": f"到職 {hire_date} 滿 6 個月補給 3 天",
    }
