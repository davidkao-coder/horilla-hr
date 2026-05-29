"""
think4u/attendance_compute.py — 共用出勤計算

把 AttendanceActivity（打卡明細）+ LeaveRequest（請假）+ Holidays（國定假）合併，
依 think4u.attendance_rules.evaluate 算出每位員工每個工作日的評估結果。

late_come_early_out_view 與其他報表共用，確保資料一致（打卡明細 / 工作紀錄 / 遲到早退
全部來自同一份 AttendanceActivity，不再依賴 Horilla 的 Attendance / AttendanceLateComeEarlyOut
（Think4U 匯入與 GPS 打卡只寫 AttendanceActivity，那兩張表是空的，會對不上）。
"""
from collections import defaultdict
from datetime import date

from attendance.models import AttendanceActivity
from base.models import Holidays
from leave.models import LeaveRequest

from think4u.attendance_rules import evaluate, is_workday


def _holiday_dates(start: date, end: date) -> dict:
    """回傳 {date: holiday_name}，涵蓋 start~end（含 recurring 年度展開）"""
    result = {}
    for h in Holidays.objects.entire().filter(start_date__lte=end):
        h_start = h.start_date
        h_end = h.end_date or h.start_date
        years = range(start.year, end.year + 1)
        spans = []
        if h.recurring:
            for y in years:
                try:
                    spans.append((h_start.replace(year=y), h_end.replace(year=y)))
                except ValueError:
                    pass
        else:
            spans.append((h_start, h_end))
        for s, e in spans:
            cur = s
            while cur <= e:
                if start <= cur <= end:
                    result[cur] = h.name
                cur = cur.fromordinal(cur.toordinal() + 1)
    return result


def leave_hours_by_type(emp_id, start: date, end: date, statuses=("approved",)) -> dict:
    """回傳某員工在 start~end 區間內各假別的總時數（多日攤分、單日上限 8h）。
    {假別名稱: 時數}
    """
    result = defaultdict(float)
    for r in LeaveRequest.objects.filter(
        employee_id=emp_id,
        start_date__lte=end,
        end_date__gte=start,
        status__in=list(statuses),
    ).select_related("leave_type_id"):
        span = (r.end_date - r.start_date).days + 1
        if span <= 0:
            span = 1
        daily_days = min(float(r.requested_days or 0) / span, 1.0)
        # 落在區間內的天數
        cur = max(r.start_date, start)
        last = min(r.end_date, end)
        n = (last - cur).days + 1
        if n <= 0:
            continue
        name = r.leave_type_id.name if r.leave_type_id else "其他"
        result[name] += daily_days * 8.0 * n
    return dict(result)


def daily_evaluations(employees, start: date, end: date, statuses=("approved",)):
    """
    回傳 list[dict]：每位員工每個「工作日且有出勤活動或請假」的評估。
      {employee, date, evaluation, check_in, check_out}
    employees: Employee queryset / list
    """
    emp_list = list(employees)
    emp_ids = [e.id for e in emp_list]
    if not emp_ids:
        return []

    # 1) 打卡活動 → (emp, date) 最早上班 / 最晚下班
    by_emp_date = defaultdict(lambda: {"in": None, "out": None})
    for a in AttendanceActivity.objects.filter(
        employee_id__in=emp_ids,
        attendance_date__gte=start,
        attendance_date__lte=end,
    ):
        key = (a.employee_id_id, a.attendance_date)
        if a.clock_in and (by_emp_date[key]["in"] is None or a.clock_in < by_emp_date[key]["in"]):
            by_emp_date[key]["in"] = a.clock_in
        if a.clock_out and (by_emp_date[key]["out"] is None or a.clock_out > by_emp_date[key]["out"]):
            by_emp_date[key]["out"] = a.clock_out

    # 2) 請假 → 每日分鐘（多日攤分）
    leave_minutes = defaultdict(int)
    for r in LeaveRequest.objects.filter(
        employee_id__in=emp_ids,
        start_date__lte=end,
        end_date__gte=start,
        status__in=list(statuses),
    ):
        span = (r.end_date - r.start_date).days + 1
        if span <= 0:
            span = 1
        daily_days = float(r.requested_days or 0) / span
        daily_min = int(min(daily_days, 1.0) * 480)
        cur = max(r.start_date, start)
        last = min(r.end_date, end)
        while cur <= last:
            leave_minutes[(r.employee_id_id, cur)] = min(
                leave_minutes[(r.employee_id_id, cur)] + daily_min, 480
            )
            cur = cur.fromordinal(cur.toordinal() + 1)

    holidays = _holiday_dates(start, end)

    out = []
    cur = start
    days = []
    while cur <= end:
        days.append(cur)
        cur = cur.fromordinal(cur.toordinal() + 1)

    for emp in emp_list:
        for d in days:
            if not is_workday(d) or d in holidays:
                continue
            data = by_emp_date.get((emp.id, d))
            lv = leave_minutes.get((emp.id, d), 0)
            # 該日完全沒打卡也沒請假 → 略過（缺勤交由月度頁處理，遲到早退頁不列）
            if not data and not lv:
                continue
            ci = data["in"] if data else None
            co = data["out"] if data else None
            ev = evaluate(ci, co, leave_minutes=lv)
            out.append(
                {
                    "employee": emp,
                    "date": d,
                    "evaluation": ev,
                    "check_in": ci,
                    "check_out": co,
                }
            )
    return out
