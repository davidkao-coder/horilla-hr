"""
think4u/punch_correction_views.py — 補打卡申請 + 多關卡審核

流程：
1. 員工提交申請（target_date / requested_check_in / requested_check_out / reason）
2. 套用該員工職位對應的 ApprovalWorkflow（request_type='punch_correction'）
3. 各關卡審核人依序審核；任一關卡駁回即終止
4. 全部通過後：寫入 AttendanceActivity，狀態變 'applied'
"""
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models as dj_models
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from attendance.models import AttendanceActivity
from employee.models import Employee
from think4u.models import (
    ApprovalStep,
    ApprovalWorkflow,
    PunchCorrectionRequest,
)


def _is_hr(user) -> bool:
    return user.is_superuser or user.groups.filter(
        name__in=["人資 HR", "系統管理員"]
    ).exists()


def _resolve_workflow(employee) -> "ApprovalWorkflow|None":
    """依員工職位找出補打卡審核流程"""
    info = getattr(employee, "employee_work_info", None)
    if not info or not info.job_position_id:
        return None
    return ApprovalWorkflow.objects.filter(
        job_position_id=info.job_position_id,
        request_type="punch_correction",
        is_active=True,
    ).first()


def _can_approve_step(user, step: ApprovalStep, request_owner: Employee) -> bool:
    """判斷使用者是否有資格審核某關卡"""
    if user.is_superuser:
        return True
    me = getattr(user, "employee_get", None)
    if not me:
        return False

    if step.approver_type == "hr":
        return _is_hr(user)
    if step.approver_type == "role" and step.approver_role:
        return user.groups.filter(pk=step.approver_role_id).exists()
    if step.approver_type == "employee" and step.approver_employee:
        return me.pk == step.approver_employee_id
    if step.approver_type in ("direct_manager", "department_head"):
        info = getattr(request_owner, "employee_work_info", None)
        dept = info.department_id if info else None
        if not dept:
            return False
        # direct_manager = 員工所屬部門的 manager（或向上回溯）
        if step.approver_type == "direct_manager":
            mgr = dept.manager
            if not mgr and hasattr(dept, "get_effective_manager"):
                mgr = dept.get_effective_manager()
            return mgr and me.pk == mgr.pk
        # department_head = 員工所屬部門及其祖先所有 manager
        if step.approver_type == "department_head":
            cur = dept
            while cur:
                if cur.manager_id and cur.manager_id == me.pk:
                    return True
                cur = cur.parent_department
            return False
    return False


def _advance_or_finalize(req: PunchCorrectionRequest):
    """進到下一關，若已是最後關卡就完成並寫回 AttendanceActivity"""
    if not req.workflow:
        # 沒有 workflow（沒設定流程）→ 直接核准（fallback）
        _apply_to_attendance(req)
        return
    steps = list(req.workflow.steps.order_by("order"))
    if req.current_step_order >= len(steps):
        # 已過最後一關 → 完成
        _apply_to_attendance(req)
    else:
        req.current_step_order += 1
        req.save()


def _apply_to_attendance(req: PunchCorrectionRequest):
    """核准完成：寫入 AttendanceActivity（建立或更新）"""
    AttendanceActivity.save = dj_models.Model.save  # 繞 Horilla bug
    today = req.target_date

    activity = AttendanceActivity.objects.filter(
        employee_id=req.employee, attendance_date=today
    ).order_by("clock_in").first()

    if activity:
        if req.requested_check_in:
            activity.clock_in = req.requested_check_in
            activity.clock_in_date = today
            activity.in_datetime = datetime.combine(today, req.requested_check_in)
        if req.requested_check_out:
            activity.clock_out = req.requested_check_out
            activity.clock_out_date = today
            activity.out_datetime = datetime.combine(today, req.requested_check_out)
        activity.save()
    else:
        # 沒有任何打卡紀錄 → 建一筆
        AttendanceActivity.objects.create(
            employee_id=req.employee,
            attendance_date=today,
            clock_in_date=today,
            clock_in=req.requested_check_in,
            in_datetime=datetime.combine(today, req.requested_check_in) if req.requested_check_in else None,
            clock_out_date=today if req.requested_check_out else None,
            clock_out=req.requested_check_out,
            out_datetime=datetime.combine(today, req.requested_check_out) if req.requested_check_out else None,
            attendance_type="office",
            field_reason=f"[補打卡] {req.reason}",
        )
    req.status = "applied"
    req.save()


# === 員工端 ==================================================
@login_required
def my_requests(request):
    """我的補打卡申請列表 + 新增表單"""
    me = getattr(request.user, "employee_get", None)
    if not me:
        messages.error(request, "尚未綁定員工資料")
        return redirect("/")

    if request.method == "POST":
        target_date = request.POST.get("target_date")
        check_in = request.POST.get("requested_check_in") or None
        check_out = request.POST.get("requested_check_out") or None
        reason = (request.POST.get("reason") or "").strip()

        if not target_date or not reason:
            messages.error(request, "日期與事由為必填")
        elif not (check_in or check_out):
            messages.error(request, "至少需要填寫上班或下班時間其中一項")
        else:
            wf = _resolve_workflow(me)
            req = PunchCorrectionRequest.objects.create(
                employee=me,
                target_date=target_date,
                requested_check_in=check_in,
                requested_check_out=check_out,
                reason=reason,
                workflow=wf,
                current_step_order=1,
            )
            if not wf:
                # 沒設流程 → 提示但仍建立（HR 可以直接處理）
                messages.warning(
                    request,
                    f"已建立補打卡申請（單號 #{req.id}），但你的職位尚未設定審核流程，將由 HR 處理。",
                )
            else:
                messages.success(
                    request, f"已建立補打卡申請（單號 #{req.id}），共 {wf.steps.count()} 關審核。"
                )
            return redirect("think4u-punch-correction-my")

    my_reqs = PunchCorrectionRequest.objects.filter(employee=me).order_by("-created_at")
    return render(
        request,
        "think4u/punch_correction/my_list.html",
        {"requests": my_reqs, "today": timezone.localdate()},
    )


@login_required
def cancel_request(request, pk):
    me = getattr(request.user, "employee_get", None)
    req = get_object_or_404(PunchCorrectionRequest, pk=pk)
    if req.employee_id != me.pk:
        messages.error(request, "不能取消他人的申請")
    elif req.status != "pending":
        messages.error(request, "只有待審核中的申請可以取消")
    else:
        req.status = "cancelled"
        req.save()
        messages.success(request, "已取消")
    return redirect("think4u-punch-correction-my")


# === 審核人端 ==================================================
@login_required
def pending_for_me(request):
    """待我審核的補打卡申請列表"""
    me = getattr(request.user, "employee_get", None)
    if not me and not request.user.is_superuser:
        return redirect("/")

    pending = (
        PunchCorrectionRequest.objects.filter(status="pending")
        .select_related("employee", "workflow")
        .prefetch_related("workflow__steps")
    )
    visible = []
    for req in pending:
        if not req.workflow:
            # 無 workflow 的 → HR 處理
            if _is_hr(request.user):
                visible.append({"req": req, "step": None})
            continue
        steps = list(req.workflow.steps.order_by("order"))
        if req.current_step_order > len(steps):
            continue
        current_step = steps[req.current_step_order - 1]
        if _can_approve_step(request.user, current_step, req.employee):
            visible.append({"req": req, "step": current_step})

    return render(
        request,
        "think4u/punch_correction/pending.html",
        {"items": visible},
    )


@login_required
def decide(request, pk):
    """審核 (POST: decision='approve'|'reject', note=...)"""
    if request.method != "POST":
        return redirect("think4u-punch-correction-pending")

    req = get_object_or_404(PunchCorrectionRequest, pk=pk)
    decision = request.POST.get("decision")
    note = (request.POST.get("note") or "").strip()

    if req.status != "pending":
        messages.error(request, "此申請已不在待審核狀態")
        return redirect("think4u-punch-correction-pending")

    # 找出當前關卡 & 校驗權限
    step = None
    if req.workflow:
        steps = list(req.workflow.steps.order_by("order"))
        if 0 < req.current_step_order <= len(steps):
            step = steps[req.current_step_order - 1]
            if not _can_approve_step(request.user, step, req.employee):
                messages.error(request, "你沒有權限審核這個關卡")
                return redirect("think4u-punch-correction-pending")
    else:
        if not _is_hr(request.user):
            messages.error(request, "此申請無流程，僅 HR 可處理")
            return redirect("think4u-punch-correction-pending")

    me = getattr(request.user, "employee_get", None)
    record = {
        "step_order": req.current_step_order,
        "step_type": step.approver_type if step else "hr_fallback",
        "approver_id": me.pk if me else None,
        "approver_name": str(me) if me else request.user.username,
        "decision": decision,
        "note": note,
        "at": timezone.now().isoformat(timespec="seconds"),
    }
    decisions = list(req.decisions or [])
    decisions.append(record)
    req.decisions = decisions

    with transaction.atomic():
        if decision == "approve":
            req.save()
            _advance_or_finalize(req)
            messages.success(request, "已核准")
        elif decision == "reject":
            req.status = "rejected"
            req.save()
            messages.success(request, "已駁回")
        else:
            messages.error(request, "未知的決定")

    return redirect("think4u-punch-correction-pending")
