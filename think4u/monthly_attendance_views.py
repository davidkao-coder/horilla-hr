"""
think4u/monthly_attendance_views.py — 月度出勤統計頁

- HR / superuser：看全公司
- 主管：看部屬（依 ApprovalWorkflow / Department.manager 推導；暫用直屬部門員工）
- 員工：只看自己
"""
import calendar
from collections import defaultdict
from datetime import date, datetime

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from attendance.models import AttendanceActivity
from base.models import Holidays
from employee.models import Employee, EmployeeWorkInformation
from leave.models import LeaveRequest, LeaveType
from think4u.attendance_rules import evaluate, format_minutes, is_workday
from think4u.models import (
    EXTRA_PAY_FIELDS,
    SALARY_COMPONENT_FIELDS,
    EmployeeSalary,
    MonthlyPayExtra,
    get_hidden_in_reports_employees,
)
from think4u.payroll_rules import compute_salary


# 薪資組成預設值（無 EmployeeSalary 紀錄時）
_DEFAULT_COMPONENTS = {"base_salary": 50000}


def _components_of(sal_row):
    """從 EmployeeSalary 取出各組成欄位 dict（無紀錄則預設本薪 50000）"""
    comp = {}
    for key, _label, _grp in SALARY_COMPONENT_FIELDS:
        if sal_row is not None:
            comp[key] = int(getattr(sal_row, key, 0) or 0)
        else:
            comp[key] = _DEFAULT_COMPONENTS.get(key, 0)
    return comp


def _extras_of(extra_row):
    """從 MonthlyPayExtra 取出各加項 dict（無紀錄則全 0）"""
    return {
        key: int(getattr(extra_row, key, 0) or 0) if extra_row else 0
        for key, _label in EXTRA_PAY_FIELDS
    }


def _build_salary(sal_row, leave_hours, extra_row=None):
    """組合薪資明細：組成欄位 + 全薪 + 勞健保 + 請假扣薪 + 其他加項 + 實領"""
    comp = _components_of(sal_row)
    gross = sum(comp.values())
    deps = int(getattr(sal_row, "dependents", 0) or 0) if sal_row else 0
    extras = _extras_of(extra_row)
    extra_total = sum(extras.values())
    s = compute_salary(
        gross, deps, leave_hours_by_type=leave_hours, extra_total=extra_total
    )
    s["components"] = comp
    s["components_pairs"] = [
        (key, comp[key]) for key, _label, _grp in SALARY_COMPONENT_FIELDS
    ]
    s["extras"] = extras
    s["extras_pairs"] = [(key, extras[key]) for key, _label in EXTRA_PAY_FIELDS]
    # 群組小計（摺疊時顯示）
    s["allowance_subtotal"] = comp["meal_allowance"] + comp["transport_allowance"]
    s["addition_subtotal"] = (
        comp["management_allowance"]
        + comp["tech_management_allowance"]
        + comp["salary_addition"]
    )
    s["dependents"] = deps
    return s


def _is_hr(user) -> bool:
    return user.is_superuser or user.groups.filter(name__in=["人資 HR", "系統管理員"]).exists()


def _scope_employees(user) -> "QuerySet[Employee]":
    """依角色決定可看的員工 queryset"""
    if _is_hr(user):
        return Employee.objects.filter(is_active=True).select_related(
            "employee_work_info__department_id"
        )
    # 主管：看自己部門 + 子部門員工
    me = getattr(user, "employee_get", None)
    if me:
        info = getattr(me, "employee_work_info", None)
        my_dept = info.department_id if info else None
        if my_dept:
            # 包含子部門遞迴
            from base.models import Department

            dept_ids = {my_dept.id}
            queue = [my_dept.id]
            while queue:
                pid = queue.pop()
                for cid in Department.objects.filter(
                    parent_department_id=pid
                ).values_list("id", flat=True):
                    if cid not in dept_ids:
                        dept_ids.add(cid)
                        queue.append(cid)
            return Employee.objects.filter(
                is_active=True,
                employee_work_info__department_id__in=dept_ids,
            ).select_related("employee_work_info__department_id")
    # 一般員工：只看自己
    return Employee.objects.filter(pk=me.pk) if me else Employee.objects.none()


@login_required
def monthly_attendance(request):
    """月度出勤統計：員工 × 日期矩陣 + 每人月度摘要"""
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month

    _, last_day = calendar.monthrange(year, month)
    dates_in_month = [date(year, month, d) for d in range(1, last_day + 1)]

    # 國定假日（該月內）
    holidays_qs = Holidays.objects.entire().filter(
        start_date__lte=date(year, month, last_day),
    )
    holiday_dates = {}  # date -> name
    for h in holidays_qs:
        e = h.end_date or h.start_date
        s = h.start_date
        if h.recurring:
            try:
                s = s.replace(year=year)
                e = e.replace(year=year)
            except ValueError:
                pass
        cur = s
        while cur <= e:
            if cur.year == year and cur.month == month:
                holiday_dates[cur] = h.name
            cur = cur.fromordinal(cur.toordinal() + 1)
    workdays_in_month = [
        d for d in dates_in_month if is_workday(d) and d not in holiday_dates
    ]

    # Think4U: HR / 主管模式才排除「不顯示在報表」的角色（高管）
    # 個人模式（員工只看自己）即使他自己被標記也仍應看到自己
    scope_qs = _scope_employees(request.user)
    me = getattr(request.user, "employee_get", None)
    is_personal_scope = (
        me and scope_qs.count() == 1 and scope_qs.filter(pk=me.pk).exists()
    )
    if not is_personal_scope:
        hidden_ids = list(
            get_hidden_in_reports_employees().values_list("id", flat=True)
        )
        scope_qs = scope_qs.exclude(id__in=hidden_ids)
    employees = list(scope_qs.order_by("employee_first_name"))
    emp_ids = [e.id for e in employees]

    # Think4U: 預取每位員工月薪（無紀錄預設 50000）
    salary_map = {
        s.employee_id: s
        for s in EmployeeSalary.objects.filter(employee_id__in=emp_ids)
    }
    # 預取該年月的變動加項（其他）
    extra_map = {
        x.employee_id: x
        for x in MonthlyPayExtra.objects.filter(
            employee_id__in=emp_ids, year=year, month=month
        )
    }

    # 一次撈該月所有 AttendanceActivity
    activities = AttendanceActivity.objects.filter(
        employee_id__in=emp_ids,
        attendance_date__gte=date(year, month, 1),
        attendance_date__lte=date(year, month, last_day),
    ).order_by("employee_id_id", "attendance_date", "clock_in")

    by_emp_date: dict = defaultdict(lambda: {"in": None, "out": None})
    for a in activities:
        key = (a.employee_id_id, a.attendance_date)
        if a.clock_in and (by_emp_date[key]["in"] is None or a.clock_in < by_emp_date[key]["in"]):
            by_emp_date[key]["in"] = a.clock_in
        if a.clock_out and (by_emp_date[key]["out"] is None or a.clock_out > by_emp_date[key]["out"]):
            by_emp_date[key]["out"] = a.clock_out

    # 一次撈該月所有 LeaveRequest（approved 才算）
    # 同時考慮跨月份的 leave (起訖日有任一日在本月內)
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)
    leaves = LeaveRequest.objects.filter(
        employee_id__in=emp_ids,
        start_date__lte=month_end,
        end_date__gte=month_start,
        status="approved",
    ).select_related("leave_type_id")
    # group by (emp_id, date) → list of (leave_name, hours)；每日攤分後的時數
    leaves_by_emp_date: dict = defaultdict(list)
    # group by emp_id → {leave_type_name: total_hours}
    leaves_by_emp_type: dict = defaultdict(lambda: defaultdict(float))
    # 每日分鐘 (供 evaluate() 使用)
    leave_minutes_by_emp_date: dict = defaultdict(int)
    for r in leaves:
        span = (r.end_date - r.start_date).days + 1
        if span <= 0:
            span = 1
        daily_days = float(r.requested_days or 0) / span
        daily_hours = daily_days * 8.0
        daily_minutes = int(min(daily_days, 1.0) * 480)
        # 在 leave 的每個跨日撒一筆
        cur = max(r.start_date, month_start)
        last = min(r.end_date, month_end)
        while cur <= last:
            leaves_by_emp_date[(r.employee_id_id, cur)].append(
                (r.leave_type_id.name, daily_hours)
            )
            leave_minutes_by_emp_date[(r.employee_id_id, cur)] = min(
                leave_minutes_by_emp_date[(r.employee_id_id, cur)] + daily_minutes, 480
            )
            cur = cur.fromordinal(cur.toordinal() + 1)
        # 月度合計（總時數）
        leaves_by_emp_type[r.employee_id_id][r.leave_type_id.name] += daily_hours * span

    # 為每位員工建一列：包含每日 cell + 月度摘要
    rows = []
    for emp in employees:
        cells = []
        sum_work = sum_late = sum_early = 0
        cnt_late = cnt_early = cnt_absent = cnt_normal = cnt_incomplete = 0
        for d in dates_in_month:
            if not is_workday(d):
                cells.append({"date": d, "is_workday": False, "cell_class": "weekend"})
                continue
            if d in holiday_dates:
                cells.append({
                    "date": d, "is_workday": False,
                    "cell_class": "holiday",
                    "holiday_name": holiday_dates[d],
                })
                continue
            data = by_emp_date.get((emp.id, d), {"in": None, "out": None})
            lvs_today = leaves_by_emp_date.get((emp.id, d), [])
            # Think4U: 用預先算好的當日請假分鐘（避免在 loop 內計算）
            lv_mins = leave_minutes_by_emp_date.get((emp.id, d), 0)
            ev = evaluate(data["in"], data["out"], leave_minutes=lv_mins)
            # 決定 cell color 同步「工作記錄」: FDP/ABS/partial leave
            has_att = bool(data["in"])
            has_lv = bool(lvs_today)
            if has_att and has_lv:
                cell_class = "wr-partial"   # 橘 = 請假+有打卡
            elif has_att:
                cell_class = "wr-present"   # 綠 = 出勤
            elif has_lv:
                cell_class = "wr-leave"     # 灰 = 請假
            else:
                cell_class = "wr-empty"
            cell = {
                "date": d,
                "is_workday": True,
                "check_in": data["in"],
                "check_out": data["out"],
                "ev": ev,
                "work_label": format_minutes(ev.work_minutes),
                "leaves": lvs_today,
                "cell_class": cell_class,
            }
            cells.append(cell)
            sum_work += ev.work_minutes
            sum_late += ev.late_minutes
            sum_early += ev.early_minutes
            if ev.status == "absent":
                cnt_absent += 1
            elif ev.status == "incomplete":
                cnt_incomplete += 1
            elif ev.status == "on_time":
                cnt_normal += 1
            else:
                if ev.late_minutes > 0:
                    cnt_late += 1
                if ev.early_minutes > 0:
                    cnt_early += 1

        rows.append(
            {
                "employee": emp,
                "department": (
                    emp.employee_work_info.department_id
                    if hasattr(emp, "employee_work_info")
                    and emp.employee_work_info
                    and emp.employee_work_info.department_id
                    else None
                ),
                "cells": cells,
                "summary": {
                    "workdays": len(workdays_in_month),
                    "normal": cnt_normal,
                    "late": cnt_late,
                    "early": cnt_early,
                    "absent": cnt_absent,
                    "incomplete": cnt_incomplete,
                    "total_work": format_minutes(sum_work),
                    "total_late": format_minutes(sum_late),
                    "total_early": format_minutes(sum_early),
                },
                # 該員工該月各假別總時數 e.g. {"事假": 4.5, "病假": 8.0}
                "leave_by_type": dict(leaves_by_emp_type.get(emp.id, {})),
                # 即時試算薪資（全薪 − 勞健保 − 請假扣薪）
                # 全薪 = 本薪 + 津貼 + 加給；請假扣薪：事假全扣、病假/生理假半扣
                "salary": _build_salary(
                    salary_map.get(emp.id),
                    dict(leaves_by_emp_type.get(emp.id, {})),
                    extra_map.get(emp.id),
                ),
            }
        )

    # 計薪基準：30 天（台灣慣例，日薪 = 月薪 / 30）
    payroll_base_days = 30
    payroll_base_hours = 30 * 8

    # 上 / 下個月導航
    if month == 1:
        prev_y, prev_m = year - 1, 12
    else:
        prev_y, prev_m = year, month - 1
    if month == 12:
        next_y, next_m = year + 1, 1
    else:
        next_y, next_m = year, month + 1

    return render(
        request,
        "think4u/attendance/monthly.html",
        {
            "year": year,
            "month": month,
            "dates_in_month": dates_in_month,
            "rows": rows,
            "prev_y": prev_y,
            "prev_m": prev_m,
            "next_y": next_y,
            "next_m": next_m,
            "is_hr": _is_hr(request.user),
            "payroll_base_days": payroll_base_days,
            "payroll_base_hours": payroll_base_hours,
            "holiday_dates": holiday_dates,
        },
    )


@login_required
@require_POST
def update_salary(request):
    """HR 即時更新員工薪資組成（本薪/津貼/加給/眷屬）→ 回傳重算結果（JSON）"""
    if not _is_hr(request.user):
        return JsonResponse({"ok": False, "error": "no_permission"}, status=403)
    try:
        emp_id = int(request.POST.get("employee_id"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "bad_input"}, status=400)

    import calendar as _calendar
    from datetime import date as _date

    from employee.models import Employee
    from think4u.attendance_compute import leave_hours_by_type

    if not Employee.objects.filter(id=emp_id).exists():
        return JsonResponse({"ok": False, "error": "no_employee"}, status=404)

    row, _ = EmployeeSalary.objects.get_or_create(employee_id=emp_id)
    update_fields = ["updated_at"]
    # 各薪資組成欄位（標準月薪 → EmployeeSalary）
    for key, _label, _grp in SALARY_COMPONENT_FIELDS:
        if key in request.POST:
            try:
                setattr(row, key, max(0, int(request.POST.get(key) or 0)))
                update_fields.append(key)
            except (TypeError, ValueError):
                pass
    # 健保眷屬
    if "dependents" in request.POST:
        try:
            row.dependents = max(0, int(request.POST.get("dependents") or 0))
            update_fields.append("dependents")
        except (TypeError, ValueError):
            pass
    row.save(update_fields=update_fields)

    # 所在年月
    today = timezone.localdate()
    try:
        year = int(request.POST.get("year", today.year))
        month = int(request.POST.get("month", today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month

    # 每月變動加項（其他）→ MonthlyPayExtra(year, month)
    extra_keys = [k for k, _ in EXTRA_PAY_FIELDS]
    if any(k in request.POST for k in extra_keys):
        extra_row, _ = MonthlyPayExtra.objects.get_or_create(
            employee_id=emp_id, year=year, month=month
        )
        ex_fields = []
        for k in extra_keys:
            if k in request.POST:
                try:
                    setattr(extra_row, k, int(request.POST.get(k) or 0))
                    ex_fields.append(k)
                except (TypeError, ValueError):
                    pass
        if ex_fields:
            extra_row.save(update_fields=ex_fields + ["updated_at"])
    else:
        extra_row = MonthlyPayExtra.objects.filter(
            employee_id=emp_id, year=year, month=month
        ).first()

    last_day = _calendar.monthrange(year, month)[1]
    lh = leave_hours_by_type(emp_id, _date(year, month, 1), _date(year, month, last_day))

    return JsonResponse({"ok": True, **_build_salary(row, lh, extra_row)})


@login_required
def export_salary(request):
    """匯出 {year}/{month} 薪資試算成 Excel（與月度頁同一份計算）"""
    import calendar as _calendar
    import io
    from datetime import date as _date

    import pandas as pd
    from django.http import HttpResponse

    from think4u.attendance_compute import leave_hours_by_type
    from think4u.payroll_rules import PAYROLL_BASE_DAYS

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month
    last_day = _calendar.monthrange(year, month)[1]
    m_start, m_end = _date(year, month, 1), _date(year, month, last_day)

    # 員工範圍（與月度頁一致：scope + 排除不顯示在報表角色）
    scope_qs = _scope_employees(request.user)
    hidden_ids = list(get_hidden_in_reports_employees().values_list("id", flat=True))
    me = getattr(request.user, "employee_get", None)
    is_personal = me and scope_qs.count() == 1 and scope_qs.filter(pk=me.pk).exists()
    if not is_personal:
        scope_qs = scope_qs.exclude(id__in=hidden_ids)
    employees = list(
        scope_qs.select_related("employee_work_info__department_id").order_by(
            "employee_first_name"
        )
    )
    emp_ids = [e.id for e in employees]
    salary_map = {
        s.employee_id: s for s in EmployeeSalary.objects.filter(employee_id__in=emp_ids)
    }
    extra_map = {
        x.employee_id: x
        for x in MonthlyPayExtra.objects.filter(
            employee_id__in=emp_ids, year=year, month=month
        )
    }

    comp_labels = [(k, lbl) for k, lbl, _g in SALARY_COMPONENT_FIELDS]
    extra_labels = list(EXTRA_PAY_FIELDS)

    rows = []
    for emp in employees:
        lh = leave_hours_by_type(emp.id, m_start, m_end)
        s = _build_salary(salary_map.get(emp.id), lh, extra_map.get(emp.id))
        detail = "；".join(
            f"{b['type']} {b['hours']}h({b['ratio_label']} -{b['amount']})"
            for b in s["leave_breakdown"]
        )
        row = {
            "員工": emp.get_full_name(),
            "部門": (
                emp.employee_work_info.department_id.department
                if getattr(emp, "employee_work_info", None)
                and emp.employee_work_info.department_id
                else ""
            ),
        }
        for key, lbl in comp_labels:
            row[lbl] = s["components"][key]
        row["全薪"] = s["gross"]
        for key, lbl in extra_labels:
            row[lbl] = s["extras"][key]
        row["其他合計"] = s["extra_total"]
        row.update(
            {
                f"日薪(÷{PAYROLL_BASE_DAYS})": s["daily"],
                "勞保自付": -s["labor"],
                "健保眷屬": s["dependents"],
                "健保自付": -s["health"],
                "請假明細": detail,
                "請假扣薪": -s["leave_ded"],
                "計算式": f"{s['gross']} +{s['extra_total']} -{s['labor']} -{s['health']} -{s['leave_ded']} = {s['net']}",
                "實領": s["net"],
            }
        )
        rows.append(row)

    columns = (
        ["員工", "部門"]
        + [lbl for _k, lbl in comp_labels]
        + ["全薪"]
        + [lbl for _k, lbl in extra_labels]
        + ["其他合計"]
        + [
            f"日薪(÷{PAYROLL_BASE_DAYS})", "勞保自付", "健保眷屬",
            "健保自付", "請假明細", "請假扣薪", "計算式", "實領",
        ]
    )
    df = pd.DataFrame(rows, columns=columns)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="薪資試算")
        wb, ws = writer.book, writer.sheets["薪資試算"]
        header_fmt = wb.add_format(
            {"bold": True, "bg_color": "#4a5dc7", "font_color": "#ffffff", "border": 1}
        )
        for ci, col in enumerate(df.columns):
            ws.write(0, ci, col, header_fmt)
            series = df[col].astype(str)
            ws.set_column(ci, ci, max([len(col)] + [len(v) for v in series]) + 2)
    output.seek(0)
    resp = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="salary_{year}{month:02d}.xlsx"'
    return resp
