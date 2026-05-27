"""
WP-03 出勤 / 計薪時數匯出（.xlsx）

欄位（依規格）：
  員工編號 / 員工姓名 / 部門 / 日期 / 打卡類型 / 上班時間 / 下班時間
  實際工作時數 / 加班時數 / 計薪時數 / 備註

權限：
- superuser / HR：可匯出全公司
- 主管：可匯出自部門
- 員工：可匯出個人
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from attendance.models import AttendanceActivity
from base.templatetags.basefilters import is_reportingmanager
from employee.models import Employee
from think4u.models import OvertimeAssignment

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
except ImportError:
    Workbook = None


def _is_hr(user):
    return user.is_superuser or user.groups.filter(
        name__in=["人資 HR", "系統管理員"]
    ).exists()


def _accessible_employees(user):
    """根據角色決定可匯出的員工 queryset"""
    if _is_hr(user):
        return Employee.objects.filter(is_active=True)
    emp = getattr(user, "employee_get", None)
    if not emp:
        return Employee.objects.none()
    if is_reportingmanager(user):
        # 主管：自己 + 直屬下屬
        from django.db.models import Q
        return Employee.objects.filter(
            Q(employee_work_info__reporting_manager_id=emp)
            | Q(employee_user_id=user),
            is_active=True,
        ).distinct()
    return Employee.objects.filter(employee_user_id=user)


def _month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def _daily_aggregates(employee, day_start: date, day_end: date) -> dict:
    """
    回傳 {date_obj: {'punches': [activity, ...], 'work_hours': float}}
    """
    acts = AttendanceActivity.objects.filter(
        employee_id=employee,
        attendance_date__range=(day_start, day_end),
    ).order_by("attendance_date", "clock_in")
    out = defaultdict(lambda: {"punches": [], "work_hours": 0.0})
    for a in acts:
        out[a.attendance_date]["punches"].append(a)
        if a.clock_in and a.clock_out:
            ci = datetime.combine(a.clock_in_date, a.clock_in)
            co = datetime.combine(a.clock_out_date or a.attendance_date, a.clock_out)
            if co < ci:
                co += timedelta(days=1)
            out[a.attendance_date]["work_hours"] += (co - ci).total_seconds() / 3600.0
    return out


def _approved_overtime_hours(employee, day_start, day_end) -> dict:
    """回傳 {date: 加班時數} for HR-approved overtime"""
    ot = OvertimeAssignment.objects.filter(
        employee=employee,
        overtime_date__range=(day_start, day_end),
        status="hr_approved",
    )
    out = defaultdict(float)
    for o in ot:
        out[o.overtime_date] += o.duration_hours
    return out


@login_required
def export_form(request):
    """匯出表單頁"""
    today = date.today()
    employees = _accessible_employees(request.user).order_by(
        "employee_first_name"
    )
    return render(
        request,
        "think4u/attendance/export_form.html",
        {
            "employees": employees,
            "default_year": today.year,
            "default_month": today.month,
            "is_hr": _is_hr(request.user),
        },
    )


@login_required
def export_excel(request):
    """產生 Excel"""
    if Workbook is None:
        return HttpResponse("openpyxl 未安裝", status=500)

    try:
        year = int(request.GET.get("year", date.today().year))
        month = int(request.GET.get("month", date.today().month))
    except ValueError:
        return HttpResponse("年月參數無效", status=400)
    emp_id = request.GET.get("employee")  # 'all' 或 PK

    accessible = _accessible_employees(request.user)
    if emp_id and emp_id != "all":
        employees = accessible.filter(id=int(emp_id))
    else:
        employees = accessible

    if not employees.exists():
        return HttpResponse("無可匯出員工", status=403)

    start, end = _month_range(year, month)

    wb = Workbook()
    ws = wb.active
    ws.title = f"{year}-{month:02d} 出勤匯出"

    headers = [
        "員工編號",
        "員工姓名",
        "部門",
        "日期",
        "打卡類型",
        "上班打卡",
        "下班打卡",
        "實際工時",
        "加班時數",
        "計薪時數",
        "備註",
    ]
    ws.append(headers)
    bold = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="667eea")
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = bold
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")

    row_no = 2
    for emp in employees:
        wi = getattr(emp, "employee_work_info", None)
        dept = wi.department_id.department if wi and wi.department_id else "—"
        daily = _daily_aggregates(emp, start, end)
        ot_hours = _approved_overtime_hours(emp, start, end)

        # 每日一列
        cur = start
        while cur <= end:
            info = daily.get(cur, {"punches": [], "work_hours": 0.0})
            ot_h = ot_hours.get(cur, 0.0)
            work_h = round(info["work_hours"], 2)
            payable_h = round(min(work_h, 8) + ot_h, 2)

            if info["punches"]:
                for p in info["punches"]:
                    ws.append(
                        [
                            emp.badge_id or emp.id,
                            emp.get_full_name(),
                            dept,
                            cur.strftime("%Y-%m-%d"),
                            "辦公室" if p.attendance_type == "office" else "外勤",
                            p.clock_in.strftime("%H:%M") if p.clock_in else "",
                            p.clock_out.strftime("%H:%M") if p.clock_out else "",
                            work_h,
                            ot_h,
                            payable_h,
                            p.field_reason or "",
                        ]
                    )
                    row_no += 1
            else:
                # 無打卡仍可能有加班
                if ot_h > 0:
                    ws.append(
                        [
                            emp.badge_id or emp.id,
                            emp.get_full_name(),
                            dept,
                            cur.strftime("%Y-%m-%d"),
                            "—",
                            "",
                            "",
                            0,
                            ot_h,
                            ot_h,
                            "僅加班",
                        ]
                    )
                    row_no += 1
            cur += timedelta(days=1)

    # 欄寬
    widths = [12, 14, 14, 12, 10, 10, 10, 10, 10, 10, 24]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    # 輸出
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"attendance_{year}-{month:02d}.xlsx"
    resp = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp
