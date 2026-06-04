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

# 各假別「雇主給薪比例」(pay_ratio)：1.0 全薪 / 0.5 半薪 / 0.0 無薪
# 扣薪額 = (1 - pay_ratio) × 日薪 × 請假天數
#   依勞基法 / 勞工請假規則 / 性平法：
#   - 事假           無薪 (0.0)        勞工請假規則第7條
#   - 病假(普通傷病)  半薪 (0.5)        勞工請假規則第4條
#   - 生理假          半薪 (0.5)        性平法第14條
#   - 特休/公假/婚假/喪假/產假/產檢假/陪產假/公傷病假/補休  全薪 (1.0)
# 未列出的假別預設全薪（不扣），避免誤扣。
LEAVE_PAY_RATIO = {
    "特休假": 1.0,
    "事假": 0.0,
    "病假": 0.5,
    "生理假": 0.5,
    "婚假": 1.0,
    "公傷病假": 1.0,
    "喪假（父母/配偶）": 1.0,
    "喪假（祖父母/子女/配偶父母）": 1.0,
    "喪假（曾祖父母/兄弟姊妹/配偶祖父母）": 1.0,
    "產假": 1.0,
    "產檢假": 1.0,
    "陪產假": 1.0,
    "公假": 1.0,
    "補休": 1.0,
}

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


def leave_deduction(salary: float, leave_hours_by_type: dict) -> dict:
    """
    依各假別給薪比例計算「請假扣薪」。
      扣薪 = Σ (1 - pay_ratio) × 日薪 × (該假別時數 / 8)
    leave_hours_by_type: {假別名稱: 該月時數}
    回傳 {"total": 扣薪總額, "breakdown": [{type, hours, ratio, amount}, ...]}
    """
    daily = salary / PAYROLL_BASE_DAYS
    total = 0.0
    breakdown = []
    # 含所有假別（即使全薪不扣也列出，扣薪 0），方便表格顯示時數/扣薪明細
    for name, hours in (leave_hours_by_type or {}).items():
        if not hours:
            continue
        ratio = LEAVE_PAY_RATIO.get(name, 1.0)  # 未知假別預設全薪不扣
        days = float(hours) / 8.0
        amount = (1.0 - ratio) * daily * days
        total += amount
        # 給薪比例 → 中文標籤
        if ratio >= 1.0:
            ratio_label = "不扣"
        elif ratio <= 0.0:
            ratio_label = "全扣"
        else:
            ratio_label = "半扣"
        breakdown.append(
            {
                "type": name,
                "hours": round(float(hours), 1),
                "days": round(days, 2),
                "ratio": ratio,
                "ratio_label": ratio_label,
                "amount": round(amount),
            }
        )
    return {"total": round(total), "breakdown": breakdown}


def compute_hourly_salary(
    hourly_rate: float,
    worked_minutes: float,
    dependents: int = 0,
    extra_total: float = 0,
    labor_insured: int = None,
    health_insured: int = None,
) -> dict:
    """
    時薪制薪資試算（Think4U 規則）：
      工時薪資 = 實際工作時數 × 時薪          （請假時數一律不給薪：有上班才有錢）
      實領    = 工時薪資 + 其他加項(加班費/獎金…) − 勞保自付 − 健保自付

    勞健保以「投保薪資」為基準：
      - labor_insured / health_insured 有填（>0）→ 直接用該投保薪資（不跟工時薪資連動）。
      - 未填 → fallback 以工時薪資估算（向下相容）。
    回傳的 key 與 compute_salary 盡量相容（gross 視為「工時薪資」），方便共用模板。
    """
    rate = int(round(hourly_rate or 0))
    worked_hours = round(float(worked_minutes or 0) / 60.0, 2)
    work_pay = int(round(worked_hours * rate))
    labor_base = int(labor_insured) if labor_insured else work_pay
    health_base = int(health_insured) if health_insured else work_pay
    labor = labor_insurance_employee(labor_base) if labor_base > 0 else 0
    health = health_insurance_employee(health_base, dependents) if health_base > 0 else 0
    extra_total = int(round(extra_total or 0))
    net = work_pay + extra_total - labor - health
    return {
        "pay_type": "hourly",
        "hourly_rate": rate,
        "worked_hours": worked_hours,
        "work_pay": work_pay,
        "gross": work_pay,          # 模板相容：工時薪資視為 gross
        "labor": labor,
        "health": health,
        "leave_ded": 0,
        "leave_breakdown": [],
        "extra_total": extra_total,
        "net": net,
        "daily": rate,              # 顯示用：時薪
        "labor_grade": _grade(labor_base, LABOR_GRADES) if labor_base > 0 else 0,
        "health_grade": _grade(health_base, HEALTH_GRADES) if health_base > 0 else 0,
    }


def compute_salary(
    salary: float,
    dependents: int = 0,
    leave_hours_by_type: dict = None,
    extra_total: float = 0,
    labor_insured: int = None,
    health_insured: int = None,
) -> dict:
    """
    回傳薪資明細：
      gross / labor / health / leave_ded / extra_total / net / daily（日薪 = gross / 30）
      net = gross − 勞保 − 健保 − 請假扣薪 + 其他加項

    勞健保以「投保薪資」為基準（與本薪/全薪不連動）：
      - labor_insured / health_insured 有填（>0）→ 直接用該投保薪資。
      - 未填 → fallback 以 gross（全薪）為投保基準（向下相容）。
    extra_total（加班費 / 禮金 / 全勤獎等不定期項目）不計入投保薪資，僅在最後加回實領。
    """
    gross = int(round(salary))
    labor_base = int(labor_insured) if labor_insured else gross
    health_base = int(health_insured) if health_insured else gross
    labor = labor_insurance_employee(labor_base)
    health = health_insurance_employee(health_base, dependents)
    ld = leave_deduction(gross, leave_hours_by_type)
    leave_ded = ld["total"]
    extra_total = int(round(extra_total or 0))
    net = gross - labor - health - leave_ded + extra_total
    daily = round(gross / PAYROLL_BASE_DAYS)
    return {
        "gross": gross,
        "labor": labor,
        "health": health,
        "leave_ded": leave_ded,
        "leave_breakdown": ld["breakdown"],
        "extra_total": extra_total,
        "net": net,
        "daily": daily,
        "labor_grade": _grade(labor_base, LABOR_GRADES),
        "health_grade": _grade(health_base, HEALTH_GRADES),
    }
