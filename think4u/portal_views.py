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
    tab = request.GET.get("tab", "clock")
    emp = _emp_or_redirect(request)
    if not emp:
        return redirect("/")

    today = timezone.localdate()
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

    # 請假
    leave_types = LeaveType.objects.filter(is_active=True).order_by("name")
    my_leaves = LeaveRequest.objects.filter(employee_id=emp).order_by("-created_at")[:5]
    leave_balances = AvailableLeave.objects.filter(employee_id=emp).select_related(
        "leave_type_id"
    )

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
            "my_overtime_apps": my_overtime_apps,
            "my_overtime_assignments": my_overtime_assignments,
            "bank": bank,
            "todays_code": get_today_code() if show_code else None,
            "show_code": show_code,
            "client_ip": get_client_ip(request),
            "can_access_admin": user_can_access_admin(request.user),
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
