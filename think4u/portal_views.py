"""
think4u/portal_views.py — 員工自助前台 (App 風格)

四個下方 nav 分頁：
  1. 打卡（含補打卡）
  2. 請假申請
  3. 加班申請
  4. 我的紀錄
"""
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models as dj_models
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from attendance.models import AttendanceActivity
from base.think4u_clock import get_client_ip, get_today_code, verify_code
from employee.models import EmployeeBankDetails
from leave.models import AvailableLeave, LeaveRequest, LeaveType
from think4u.models import (
    ApprovalWorkflow,
    LeaveGrantRequest,
    OvertimeApplication,
    OvertimeAssignment,
    PunchCorrectionRequest,
    user_can_access_admin,
)


def _emp_or_redirect(request):
    emp = getattr(request.user, "employee_get", None)
    if not emp:
        messages.error(request, "尚未綁定員工資料")
        return None
    return emp


def _resolve_workflow(employee, request_type: str):
    info = getattr(employee, "employee_work_info", None)
    if not info or not info.job_position_id:
        return None
    return ApprovalWorkflow.objects.filter(
        job_position_id=info.job_position_id,
        request_type=request_type,
        is_active=True,
    ).first()


@login_required
def portal_home(request):
    """前台主頁 — 預設顯示打卡 tab"""
    import calendar
    from collections import defaultdict
    from datetime import date as _date

    from think4u.attendance_rules import evaluate, format_minutes, is_workday

    tab = request.GET.get("tab", "clock")
    emp = _emp_or_redirect(request)
    if not emp:
        return redirect("/")

    today = timezone.localdate()

    # 預填日期：請假 / 加班 / 補打卡 從出勤頁跳過來時用
    prefill_date = request.GET.get("prefill_date") or ""

    # 出勤 tab 的月份切換（預設為今天當月）
    try:
        att_year = int(request.GET.get("att_year", today.year))
        att_month = int(request.GET.get("att_month", today.month))
    except (TypeError, ValueError):
        att_year, att_month = today.year, today.month

    _, last_day = calendar.monthrange(att_year, att_month)
    month_first = _date(att_year, att_month, 1)
    month_last = _date(att_year, att_month, last_day)

    # 該員工該月的 AttendanceActivity，整合成 (date -> {in, out})
    month_acts = AttendanceActivity.objects.filter(
        employee_id=emp,
        attendance_date__gte=month_first,
        attendance_date__lte=month_last,
    )
    by_date = defaultdict(lambda: {"in": None, "out": None})
    for a in month_acts:
        d = a.attendance_date
        if a.clock_in and (by_date[d]["in"] is None or a.clock_in < by_date[d]["in"]):
            by_date[d]["in"] = a.clock_in
        if a.clock_out and (by_date[d]["out"] is None or a.clock_out > by_date[d]["out"]):
            by_date[d]["out"] = a.clock_out

    attendance_rows = []
    s_normal = s_late = s_early = s_absent = s_incomplete = 0
    sum_work = sum_late = sum_early = 0
    for day in range(1, last_day + 1):
        d = _date(att_year, att_month, day)
        if not is_workday(d):
            attendance_rows.append({
                "date": d, "is_workday": False, "status": "weekend",
                "status_label": "週末", "work_label": "—",
            })
            continue
        data = by_date.get(d, {"in": None, "out": None})
        # 未來的日期不評估
        if d > today:
            attendance_rows.append({
                "date": d, "is_workday": True, "status": "future",
                "status_label": "—", "check_in": None, "check_out": None,
                "work_label": "—",
            })
            continue
        ev = evaluate(data["in"], data["out"])
        attendance_rows.append({
            "date": d, "is_workday": True,
            "status": ev.status, "status_label": ev.status_label,
            "check_in": data["in"], "check_out": data["out"],
            "work_label": format_minutes(ev.work_minutes),
            "late_minutes": ev.late_minutes,
            "early_minutes": ev.early_minutes,
            "is_abnormal": ev.status not in ("on_time",),
        })
        sum_work += ev.work_minutes
        sum_late += ev.late_minutes
        sum_early += ev.early_minutes
        if ev.status == "absent":
            s_absent += 1
        elif ev.status == "incomplete":
            s_incomplete += 1
        elif ev.status == "on_time":
            s_normal += 1
        else:
            if ev.late_minutes > 0:
                s_late += 1
            if ev.early_minutes > 0:
                s_early += 1

    att_summary = {
        "normal": s_normal,
        "late": s_late,
        "early": s_early,
        "absent": s_absent,
        "incomplete": s_incomplete,
        "total_work": format_minutes(sum_work),
        "total_late": format_minutes(sum_late),
        "total_early": format_minutes(sum_early),
    }
    # 12 個月導航
    att_months = list(range(1, 13))
    today_punches = list(
        AttendanceActivity.objects.filter(
            employee_id=emp, attendance_date=today
        ).order_by("clock_in")
    )

    # 員工是否已上 / 下班打卡
    first_in = next((p for p in today_punches if p.clock_in), None)
    last_out = None
    for p in reversed(today_punches):
        if p.clock_out:
            last_out = p
            break
    open_punch = next(
        (p for p in today_punches if p.clock_in and not p.clock_out), None
    )

    # 補打卡待審
    my_corrections = PunchCorrectionRequest.objects.filter(employee=emp).order_by(
        "-created_at"
    )[:5]

    # 請假 — 只列員工已有 AvailableLeave 配額 且 > 0 的假別
    leave_balances = list(
        AvailableLeave.objects.filter(employee_id=emp)
        .select_related("leave_type_id")
        .order_by("leave_type_id__name")
    )
    available_type_ids = [
        b.leave_type_id_id for b in leave_balances if (b.available_days or 0) + (b.carryforward_days or 0) > 0
    ]
    leave_types = LeaveType.objects.filter(id__in=available_type_ids).order_by("name")
    my_leaves = LeaveRequest.objects.filter(employee_id=emp).order_by("-created_at")[:5]

    # 申請給假（非預設假別才能申請）
    from think4u.models import DEFAULT_LEAVE_TYPE_NAMES

    grantable_types = LeaveType.objects.filter(is_active=True).exclude(
        name__in=DEFAULT_LEAVE_TYPE_NAMES
    ).order_by("name")
    my_grant_requests = LeaveGrantRequest.objects.filter(employee=emp).order_by(
        "-created_at"
    )[:5]

    # 加班
    my_overtime_apps = OvertimeApplication.objects.filter(employee=emp).order_by(
        "-created_at"
    )[:5]
    my_overtime_assignments = OvertimeAssignment.objects.filter(employee=emp).order_by(
        "-created_at"
    )[:5]

    # 銀行資訊
    bank = EmployeeBankDetails.objects.filter(employee_id=emp).first()

    # superuser / HR 可看當日驗證碼
    user = request.user
    show_code = user.is_superuser or user.groups.filter(
        name__in=["人資 HR", "系統管理員"]
    ).exists()

    return render(
        request,
        "think4u/portal/main.html",
        {
            "tab": tab,
            "employee": emp,
            "today": today,
            "today_punches": today_punches,
            "first_in": first_in,
            "last_out": last_out,
            "open_punch": open_punch,
            "my_corrections": my_corrections,
            "leave_types": leave_types,
            "my_leaves": my_leaves,
            "leave_balances": leave_balances,
            "grantable_types": grantable_types,
            "my_grant_requests": my_grant_requests,
            "my_overtime_apps": my_overtime_apps,
            "my_overtime_assignments": my_overtime_assignments,
            "bank": bank,
            "todays_code": get_today_code() if show_code else None,
            "show_code": show_code,
            "client_ip": get_client_ip(request),
            "can_access_admin": user_can_access_admin(request.user),
            # 出勤表
            "att_year": att_year,
            "att_month": att_month,
            "att_months": att_months,
            "attendance_rows": attendance_rows,
            "att_summary": att_summary,
            # 預填日期
            "prefill_date": prefill_date,
        },
    )


# ============================================================================
# Clock 打卡（共用 think4u_clock 邏輯，但重導至 portal）
# ============================================================================
@login_required
def portal_clock_submit(request):
    if request.method != "POST":
        return redirect("think4u-portal")
    emp = _emp_or_redirect(request)
    if not emp:
        return redirect("/")

    action = request.POST.get("action")
    a_type = request.POST.get("attendance_type", "office")
    code = (request.POST.get("verification_code") or "").strip()
    reason = (request.POST.get("field_reason") or "").strip()
    client_ip = get_client_ip(request)

    if a_type not in ("office", "field"):
        messages.error(request, "無效的打卡類型")
        return redirect(f"{reverse('think4u-portal')}?tab=clock")

    if a_type == "office":
        if not verify_code(code):
            messages.error(request, "驗證碼錯誤或已過期")
            return redirect(f"{reverse('think4u-portal')}?tab=clock")
    elif not reason:
        messages.error(request, "外勤打卡必須填寫原因")
        return redirect(f"{reverse('think4u-portal')}?tab=clock")

    now = timezone.localtime()
    today = now.date()
    AttendanceActivity.save = dj_models.Model.save

    if action == "in":
        AttendanceActivity.objects.create(
            employee_id=emp,
            attendance_date=today,
            clock_in_date=today,
            clock_in=now.time(),
            in_datetime=now,
            attendance_type=a_type,
            field_reason=reason or None,
            client_ip=client_ip,
            verification_code_used=(code[:2] + "****") if code else None,
        )
        messages.success(request, f"上班打卡成功：{now.strftime('%H:%M:%S')}")
    elif action == "out":
        last = (
            AttendanceActivity.objects.filter(
                employee_id=emp, attendance_date=today, clock_out__isnull=True
            )
            .order_by("-clock_in")
            .first()
        )
        if not last:
            messages.error(request, "尚未上班打卡，無法下班打卡")
        else:
            last.clock_out_date = today
            last.clock_out = now.time()
            last.out_datetime = now
            last.save()
            messages.success(request, f"下班打卡成功：{now.strftime('%H:%M:%S')}")
    return redirect(f"{reverse('think4u-portal')}?tab=clock")


# ============================================================================
# 補打卡（簡化版，直接從 portal 提交）
# ============================================================================
@login_required
def portal_punch_correction_submit(request):
    if request.method != "POST":
        return redirect("think4u-portal")
    emp = _emp_or_redirect(request)
    if not emp:
        return redirect("/")

    target_date = request.POST.get("target_date")
    check_in = request.POST.get("requested_check_in") or None
    check_out = request.POST.get("requested_check_out") or None
    reason = (request.POST.get("reason") or "").strip()

    if not target_date or not reason or not (check_in or check_out):
        messages.error(request, "日期、事由必填，上班/下班至少一項")
    else:
        wf = _resolve_workflow(emp, "punch_correction")
        req = PunchCorrectionRequest.objects.create(
            employee=emp,
            target_date=target_date,
            requested_check_in=check_in,
            requested_check_out=check_out,
            reason=reason,
            workflow=wf,
            current_step_order=1,
        )
        messages.success(request, f"已建立補打卡申請 #{req.id}")
    return redirect(f"{reverse('think4u-portal')}?tab=clock")


# ============================================================================
# 請假申請
# ============================================================================
@login_required
def portal_leave_submit(request):
    if request.method != "POST":
        return redirect("think4u-portal")
    emp = _emp_or_redirect(request)
    if not emp:
        return redirect("/")

    leave_type_id = request.POST.get("leave_type_id")
    start_date = request.POST.get("start_date")
    end_date = request.POST.get("end_date") or start_date
    description = (request.POST.get("description") or "").strip()
    attachment = request.FILES.get("attachment")

    if not (leave_type_id and start_date and description):
        messages.error(request, "假別、起始日、事由皆為必填")
        return redirect(f"{reverse('think4u-portal')}?tab=leave")

    lt = LeaveType.objects.filter(pk=leave_type_id).first()
    if not lt:
        messages.error(request, "無效的假別")
        return redirect(f"{reverse('think4u-portal')}?tab=leave")

    # 必須有 AvailableLeave 才能請（前台已過濾，但後端再驗一次）
    has_quota = AvailableLeave.objects.filter(
        employee_id=emp, leave_type_id=lt
    ).exists()
    if not has_quota:
        messages.error(request, f"你尚未取得「{lt.name}」配額，請先送出申請給假")
        return redirect(f"{reverse('think4u-portal')}?tab=leave")

    # 計算請假天數
    try:
        d_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        d_end = datetime.strptime(end_date, "%Y-%m-%d").date()
        days = (d_end - d_start).days + 1
        if days < 1:
            raise ValueError
    except ValueError:
        messages.error(request, "日期格式錯誤或結束日早於起始日")
        return redirect(f"{reverse('think4u-portal')}?tab=leave")

    # 生理假規則：每月最多 1 天
    if lt.name == "生理假":
        if days > 1:
            messages.error(request, "生理假每次只能請 1 天")
            return redirect(f"{reverse('think4u-portal')}?tab=leave")
        month_start = d_start.replace(day=1)
        # 下個月第一天
        if d_start.month == 12:
            next_month = d_start.replace(year=d_start.year + 1, month=1, day=1)
        else:
            next_month = d_start.replace(month=d_start.month + 1, day=1)
        same_month_used = LeaveRequest.objects.filter(
            employee_id=emp,
            leave_type_id=lt,
            start_date__gte=month_start,
            start_date__lt=next_month,
        ).exclude(status__in=("cancelled", "rejected")).exists()
        if same_month_used:
            messages.error(request, "本月已申請過生理假（每月限 1 天）")
            return redirect(f"{reverse('think4u-portal')}?tab=leave")

    LeaveRequest.save = dj_models.Model.save  # Horilla bug 繞過
    LeaveRequest.objects.create(
        employee_id=emp,
        leave_type_id=lt,
        start_date=d_start,
        end_date=d_end,
        requested_days=days,
        description=description,
        attachment=attachment,
        status="requested",
    )
    messages.success(request, f"已送出請假申請（{lt.name}，共 {days} 天）")
    return redirect(f"{reverse('think4u-portal')}?tab=leave")


# ============================================================================
# 加班申請（員工主動）
# ============================================================================
@login_required
def portal_overtime_submit(request):
    if request.method != "POST":
        return redirect("think4u-portal")
    emp = _emp_or_redirect(request)
    if not emp:
        return redirect("/")

    overtime_date = request.POST.get("overtime_date")
    start_time = request.POST.get("start_time")
    end_time = request.POST.get("end_time")
    reason = (request.POST.get("reason") or "").strip()

    if not (overtime_date and start_time and end_time and reason):
        messages.error(request, "日期、開始/結束時間、事由皆為必填")
        return redirect(f"{reverse('think4u-portal')}?tab=overtime")

    wf = _resolve_workflow(emp, "overtime")
    app = OvertimeApplication.objects.create(
        employee=emp,
        overtime_date=overtime_date,
        start_time=start_time,
        end_time=end_time,
        reason=reason,
        workflow=wf,
        current_step_order=1,
    )
    messages.success(
        request,
        f"已送出加班申請 #{app.id}（{app.duration_hours:.1f}h）",
    )
    return redirect(f"{reverse('think4u-portal')}?tab=overtime")


# ============================================================================
# 取消我的申請
# ============================================================================
@login_required
def portal_cancel(request, kind, pk):
    emp = _emp_or_redirect(request)
    if not emp:
        return redirect("/")

    if kind == "punch":
        obj = get_object_or_404(PunchCorrectionRequest, pk=pk, employee=emp)
    elif kind == "leave":
        obj = get_object_or_404(LeaveRequest, pk=pk, employee_id=emp)
    elif kind == "overtime":
        obj = get_object_or_404(OvertimeApplication, pk=pk, employee=emp)
    else:
        messages.error(request, "未知的類型")
        return redirect("think4u-portal")

    # 統一判斷可否取消
    if kind == "leave":
        if obj.status not in ("requested",):
            messages.error(request, "此申請已不能取消")
        else:
            LeaveRequest.save = dj_models.Model.save
            obj.status = "cancelled"
            obj.save()
            messages.success(request, "已取消請假申請")
    else:
        if obj.status != "pending":
            messages.error(request, "此申請已不能取消")
        else:
            obj.status = "cancelled"
            obj.save()
            messages.success(request, "已取消")

    tab_map = {"punch": "clock", "leave": "leave", "overtime": "overtime"}
    return redirect(f"{reverse('think4u-portal')}?tab={tab_map[kind]}")


# ============================================================================
# 個人資料修改
# ============================================================================
@login_required
def portal_personal_submit(request):
    if request.method != "POST":
        return redirect("think4u-portal")
    emp = _emp_or_redirect(request)
    if not emp:
        return redirect("/")

    # 可編輯欄位（與 Think4U 精簡後的個人資料表單一致）
    EDITABLE = [
        "employee_first_name",
        "email",
        "phone",
        "address",
        "dob",
        "gender",
        "emergency_contact",
        "emergency_contact_name",
        "emergency_contact_relation",
    ]
    from django.db import models as dj_models
    from employee.models import Employee

    Employee.save = dj_models.Model.save  # 繞 Horilla bug

    changed = False
    for f in EDITABLE:
        if f not in request.POST:
            continue
        val = (request.POST.get(f) or "").strip() or None
        if f == "employee_first_name" and not val:
            messages.error(request, "姓名必填")
            return redirect(f"{reverse('think4u-portal')}?tab=settings")
        if f == "email" and not val:
            messages.error(request, "Email 必填")
            return redirect(f"{reverse('think4u-portal')}?tab=settings")
        # dob 可以是空白
        if getattr(emp, f) != val:
            setattr(emp, f, val)
            changed = True

    # 大頭照
    img = request.FILES.get("employee_profile")
    if img:
        emp.employee_profile = img
        changed = True

    if changed:
        emp.save()
        messages.success(request, "個人資料已更新")
    else:
        messages.info(request, "沒有變更")
    return redirect(f"{reverse('think4u-portal')}?tab=settings")


# ============================================================================
# 銀行資訊修改（只留：銀行名稱、帳號）
# ============================================================================
@login_required
def portal_bank_submit(request):
    if request.method != "POST":
        return redirect("think4u-portal")
    emp = _emp_or_redirect(request)
    if not emp:
        return redirect("/")

    bank_name = (request.POST.get("bank_name") or "").strip()
    account_number = (request.POST.get("account_number") or "").strip()

    if not bank_name or not account_number:
        messages.error(request, "銀行名稱與帳號皆必填")
        return redirect(f"{reverse('think4u-portal')}?tab=settings")

    from django.db import models as dj_models

    EmployeeBankDetails.save = dj_models.Model.save  # 繞 Horilla bug

    bank, _created = EmployeeBankDetails.objects.update_or_create(
        employee_id=emp,
        defaults={"bank_name": bank_name, "account_number": account_number},
    )
    messages.success(request, "銀行資訊已更新")
    return redirect(f"{reverse('think4u-portal')}?tab=settings")


# ============================================================================
# 申請給假（非預設假別 — 需 HR 審核 + 上傳證明）
# ============================================================================
@login_required
def portal_leave_grant_submit(request):
    if request.method != "POST":
        return redirect("think4u-portal")
    emp = _emp_or_redirect(request)
    if not emp:
        return redirect("/")

    leave_type_id = request.POST.get("leave_type_id")
    # Think4U: 接收小時數，內部換算成天數儲存
    requested_hours = request.POST.get("requested_hours") or request.POST.get("requested_days")
    reason = (request.POST.get("reason") or "").strip()
    proof = request.FILES.get("proof_document")

    if not (leave_type_id and requested_hours and reason):
        messages.error(request, "假別、時數、事由皆為必填")
        return redirect(f"{reverse('think4u-portal')}?tab=leave")

    lt = LeaveType.objects.filter(pk=leave_type_id).first()
    if not lt:
        messages.error(request, "無效的假別")
        return redirect(f"{reverse('think4u-portal')}?tab=leave")

    from think4u.models import DEFAULT_LEAVE_TYPE_NAMES

    if lt.name in DEFAULT_LEAVE_TYPE_NAMES:
        messages.error(request, f"「{lt.name}」屬於預設假別，不需要申請給假")
        return redirect(f"{reverse('think4u-portal')}?tab=leave")

    try:
        hours = float(requested_hours)
        if hours <= 0:
            raise ValueError
    except ValueError:
        messages.error(request, "時數需大於 0")
        return redirect(f"{reverse('think4u-portal')}?tab=leave")
    days = hours / 8.0

    LeaveGrantRequest.objects.create(
        employee=emp,
        leave_type=lt,
        requested_days=days,
        reason=reason,
        proof_document=proof,
    )
    messages.success(request, f"已送出給假申請（{lt.name}，{hours} 小時），等待 HR 審核")
    return redirect(f"{reverse('think4u-portal')}?tab=leave")
