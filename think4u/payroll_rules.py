"""
think4u/payroll_rules.py — 台灣 2025（民國114年）勞健保員工自付額計算

來源：勞動部勞工保險局 / 衛福部健保署 投保薪資（金額）分級表。
- 勞保（普通事故 11.5% + 就保 1% = 12.5%），員工自付比例 20%，月投保薪資上限 45,800。
- 健保（一般保險費率 5.17%），員工（受僱者）自付比例 30%，本人 + 眷屬人數（眷屬上限 3）。
- 勞退 6% 為雇主全額負擔，不從薪資扣除（不計入）。

投保級距 = 取「第一個 >= 實際月薪」的級距；超過最高級距則用最高級距。

NT$50,000 範例：
  勞保 = min(45800) × 12.5% × 20% = 1,145
  健保 = 50,600（首個 >= 50000 的級距）× 5.17% × 30% = 785
  實領 = 50,000 − 1,145 − 785 = 48,070
"""
import math

# 勞保費率 2025
LABOR_RATE = 0.125          # 普通事故 11.5% + 就保 1%
LABOR_EMPLOYEE_SHARE = 0.20  # 一般受僱者自付 20%

# 健保費率 2025
HEALTH_RATE = 0.0517
HEALTH_EMPLOYEE_SHARE = 0.30  # 受僱者自付 30%

PAYROLL_BASE_DAYS = 30        # 計薪基準 30 天

# 勞保投保薪資分級表（2025 全時，月投保薪資，上限 45,800）
LABOR_GRADES = [
    28590, 30300, 31800, 33300, 34800, 36300,
    38200, 40100, 42000, 43900, 45800,
]

# 健保投保金額分級表（2025，自 28,590 起，部分級距至高薪）
HEALTH_GRADES = [
    28590, 30300, 31800, 33300, 34800, 36300, 38200, 40100, 42000, 43900,
    45800, 48200, 50600, 53000, 55400, 57800, 60800, 63800, 66800, 69800,
    72800, 76500, 80200, 83900, 87600, 92100, 96600, 101100, 105600, 110100,
    115500, 120900, 126300, 131700, 137100, 142500, 147900, 150000, 156400,
    162800, 169200, 175600, 182000, 189500, 197000, 204500, 212000, 219500,
]


def _grade(salary: float, grades) -> int:
    """取第一個 >= salary 的級距；超過上限取最高級距；低於下限取最低級距。"""
    s = max(0, int(round(salary)))
    for g in grades:
        if s <= g:
            return g
    return grades[-1]


def labor_insurance_employee(salary: float) -> int:
    """勞保員工自付額（四捨五入到元）"""
    insured = _grade(salary, LABOR_GRADES)
    return round(insured * LABOR_RATE * LABOR_EMPLOYEE_SHARE)


def health_insurance_employee(salary: float, dependents: int = 0) -> int:
    """健保員工自付額（本人 + 眷屬，眷屬上限 3；四捨五入到元）"""
    insured = _grade(salary, HEALTH_GRADES)
    deps = max(0, min(int(dependents), 3))
    per_person = insured * HEALTH_RATE * HEALTH_EMPLOYEE_SHARE
    return round(per_person * (1 + deps))


def compute_salary(salary: float, dependents: int = 0) -> dict:
    """
    回傳薪資明細：
      gross / labor / health / net / daily（日薪 = gross / 30）
    """
    gross = int(round(salary))
    labor = labor_insurance_employee(gross)
    health = health_insurance_employee(gross, dependents)
    net = gross - labor - health
    daily = round(gross / PAYROLL_BASE_DAYS)
    return {
        "gross": gross,
        "labor": labor,
        "health": health,
        "net": net,
        "daily": daily,
        "labor_grade": _grade(gross, LABOR_GRADES),
        "health_grade": _grade(gross, HEALTH_GRADES),
    }
