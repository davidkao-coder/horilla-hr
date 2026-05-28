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
from django.shortcuts import render
from django.utils import timezone

from attendance.models import AttendanceActivity
from employee.models import Employee, EmployeeWorkInformation
from think4u.attendance_rules import evaluate, format_minutes, is_workday


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
    workdays_in_month = [d for d in dates_in_month if is_workday(d)]

    employees = list(_scope_employees(request.user).order_by("employee_first_name"))
    emp_ids = [e.id for e in employees]

    # 一次撈該月所有 AttendanceActivity
    activities = AttendanceActivity.objects.filter(
        employee_id__in=emp_ids,
        attendance_date__gte=date(year, month, 1),
        attendance_date__lte=date(year, month, last_day),
    ).order_by("employee_id_id", "attendance_date", "clock_in")

    # group by (emp_id, date) — 取該日「最早 in / 最晚 out」
    by_emp_date: dict = defaultdict(lambda: {"in": None, "out": None})
    for a in activities:
        key = (a.employee_id_id, a.attendance_date)
        if a.clock_in and (by_emp_date[key]["in"] is None or a.clock_in < by_emp_date[key]["in"]):
            by_emp_date[key]["in"] = a.clock_in
        if a.clock_out and (by_emp_date[key]["out"] is None or a.clock_out > by_emp_date[key]["out"]):
            by_emp_date[key]["out"] = a.clock_out

    # 為每位員工建一列：包含每日 cell + 月度摘要
    rows = []
    for emp in employees:
        cells = []
        sum_work = sum_late = sum_early = 0
        cnt_late = cnt_early = cnt_absent = cnt_normal = cnt_incomplete = 0
        for d in dates_in_month:
            if not is_workday(d):
                cells.append({"date": d, "is_workday": False})
                continue
            data = by_emp_date.get((emp.id, d), {"in": None, "out": None})
            ev = evaluate(data["in"], data["out"])
            cell = {
                "date": d,
                "is_workday": True,
                "check_in": data["in"],
                "check_out": data["out"],
                "ev": ev,
                "work_label": format_minutes(ev.work_minutes),
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
            }
        )

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
        },
    )
