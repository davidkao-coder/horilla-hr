"""
think4u/day_detail_views.py — 某員工某天的出勤明細頁
- 全部打卡進出（AttendanceActivity）
- 該日請假紀錄
- 該日加班紀錄
"""
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from attendance.models import AttendanceActivity
from employee.models import Employee
from leave.models import LeaveRequest
from think4u.attendance_rules import evaluate, format_minutes, leave_minutes_on_date
from think4u.models import OvertimeApplication, OvertimeAssignment


@login_required
def day_detail(request, emp_id: int, ymd: str):
    """例：/think4u/attendance/day/12/2026-05-21/"""
    try:
        the_date = datetime.strptime(ymd, "%Y-%m-%d").date()
    except ValueError:
        return render(request, "404.html", status=404)
    emp = get_object_or_404(Employee, pk=emp_id)

    punches = list(
        AttendanceActivity.objects.filter(
            employee_id=emp, attendance_date=the_date
        ).order_by("clock_in")
    )

    # 評估狀態
    first_in = next((p.clock_in for p in punches if p.clock_in), None)
    last_out = None
    for p in reversed(punches):
        if p.clock_out:
            last_out = p.clock_out
            break
    lv_mins = leave_minutes_on_date(emp, the_date)
    ev = evaluate(first_in, last_out, leave_minutes=lv_mins)

    # 週末 / 國定假日且當天沒打卡也沒請假 → 視為休息日（不算缺勤 / 工時不足）
    from think4u.attendance_rules import AttendanceEvaluation, is_workday
    from think4u.attendance_compute import _holiday_dates

    holiday_name = _holiday_dates(the_date, the_date).get(the_date)
    is_rest = (not is_workday(the_date)) or holiday_name is not None
    if is_rest and not punches and lv_mins == 0:
        ev = AttendanceEvaluation(
            status="rest",
            status_label=holiday_name or "休息日",
            work_minutes=0,
            late_minutes=0,
            early_minutes=0,
            short_minutes=0,
            is_complete=True,
            has_check_in=False,
            has_check_out=False,
        )

    leaves = list(
        LeaveRequest.objects.filter(
            employee_id=emp, start_date__lte=the_date, end_date__gte=the_date
        ).select_related("leave_type_id").order_by("created_at")
    )

    overtimes_apps = list(
        OvertimeApplication.objects.filter(employee=emp, overtime_date=the_date)
    )
    overtimes_assigns = list(
        OvertimeAssignment.objects.filter(employee=emp, overtime_date=the_date)
    )

    return render(
        request,
        "think4u/attendance/day_detail.html",
        {
            "employee": emp,
            "date": the_date,
            "punches": punches,
            "ev": ev,
            "work_label": format_minutes(ev.work_minutes),
            "leaves": leaves,
            "overtimes_apps": overtimes_apps,
            "overtimes_assigns": overtimes_assigns,
        },
    )
