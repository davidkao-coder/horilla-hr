"""
think4u/overtime_views.py

WP-04 加班指派 views：
- 主管：建立 / 取消 / 列表
- 員工：列表 / 確認 / 拒絕
- HR：列表 / 核准 / 駁回
"""

import logging
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from base.templatetags.basefilters import is_reportingmanager
from employee.models import Employee
from think4u.forms import OvertimeAssignmentForm
from think4u.models import OvertimeAssignment

logger = logging.getLogger(__name__)


# ---------- helpers ----------


def _is_hr(user) -> bool:
    return user.is_superuser or user.groups.filter(name__in=["人資 HR", "系統管理員"]).exists()


def _safe_send(subject: str, body: str, to: list[str]):
    """忽略寄信失敗（無 SMTP 也要能跑）"""
    to = [t for t in to if t]
    if not to:
        return
    try:
        send_mail(subject, body, None, to, fail_silently=True)
    except Exception as e:
        logger.warning("send_mail failed: %s", e)


# ---------- 主管 ----------


@login_required
def manager_overtime_list(request):
    user = request.user
    if not (is_reportingmanager(user) or _is_hr(user)):
        return HttpResponseForbidden("僅主管可查看")
    emp = getattr(user, "employee_get", None)
    if _is_hr(user):
        qs = OvertimeAssignment.objects.all()
    else:
        qs = OvertimeAssignment.objects.filter(assigned_by=user)
    return render(
        request,
        "think4u/overtime/manager_list.html",
        {"items": qs, "is_hr": _is_hr(user)},
    )


@login_required
def manager_overtime_create(request):
    user = request.user
    if not (is_reportingmanager(user) or _is_hr(user)):
        return HttpResponseForbidden("僅主管可建立加班指派")
    if request.method == "POST":
        form = OvertimeAssignmentForm(request.POST)
        if form.is_valid():
            ot = form.save(commit=False)
            ot.assigned_by = user
            ot.status = "pending_employee"
            ot.save()
            # 通知員工
            target_email = ot.employee.employee_user_id.email if ot.employee.employee_user_id else ot.employee.email
            _safe_send(
                f"[加班指派] {ot.overtime_date} {ot.start_time}-{ot.end_time}",
                f"您被指派加班\n日期：{ot.overtime_date}\n時段：{ot.start_time}-{ot.end_time}\n原因：{ot.reason}\n請至系統確認。",
                [target_email],
            )
            messages.success(request, _("加班指派已建立，已通知員工"))
            return redirect("think4u-overtime-manager")
    else:
        form = OvertimeAssignmentForm()
    return render(
        request, "think4u/overtime/manager_create.html", {"form": form}
    )


@login_required
@require_http_methods(["POST"])
def manager_overtime_cancel(request, pk):
    ot = get_object_or_404(OvertimeAssignment, pk=pk, assigned_by=request.user)
    if ot.status != "pending_employee":
        messages.error(request, _("僅待員工確認狀態可取消"))
        return redirect("think4u-overtime-manager")
    ot.status = "cancelled"
    ot.save()
    messages.success(request, _("已取消"))
    return redirect("think4u-overtime-manager")


# ---------- 員工 ----------


@login_required
def employee_overtime_list(request):
    emp = getattr(request.user, "employee_get", None)
    if not emp:
        return HttpResponseForbidden("尚未綁定員工")
    qs = OvertimeAssignment.objects.filter(employee=emp)
    return render(
        request, "think4u/overtime/employee_list.html", {"items": qs}
    )


@login_required
@require_http_methods(["POST"])
def employee_overtime_decision(request, pk):
    """員工接受或拒絕"""
    emp = getattr(request.user, "employee_get", None)
    ot = get_object_or_404(OvertimeAssignment, pk=pk, employee=emp)
    if ot.status != "pending_employee":
        messages.error(request, _("此筆已超過確認階段"))
        return redirect("think4u-overtime-employee")
    decision = request.POST.get("decision")
    note = (request.POST.get("note") or "").strip()
    now = timezone.now()
    if decision == "accept":
        ot.status = "pending_hr"
        ot.employee_confirmed_at = now
        ot.employee_note = note or None
        ot.save()
        # 通知 HR
        hr_emails = list(
            User_email_of_group("人資 HR")
        )
        _safe_send(
            f"[加班待核准] {ot.employee} {ot.overtime_date}",
            f"員工 {ot.employee} 已確認加班，待 HR 核准。",
            hr_emails,
        )
        messages.success(request, _("已確認，待 HR 核准"))
    elif decision == "reject":
        if not note:
            messages.error(request, _("拒絕需填寫理由"))
            return redirect("think4u-overtime-employee")
        ot.status = "employee_rejected"
        ot.employee_note = note
        ot.save()
        # 通知主管
        _safe_send(
            f"[加班被拒] {ot.employee} {ot.overtime_date}",
            f"員工 {ot.employee} 拒絕加班。理由：{note}",
            [ot.assigned_by.email],
        )
        messages.success(request, _("已拒絕，主管已收到通知"))
    else:
        messages.error(request, _("未知的動作"))
    return redirect("think4u-overtime-employee")


def User_email_of_group(group_name):
    from django.contrib.auth.models import Group

    g = Group.objects.filter(name=group_name).first()
    if not g:
        return []
    return [u.email for u in g.user_set.all() if u.email]


# ---------- HR ----------


@login_required
def hr_overtime_list(request):
    if not _is_hr(request.user):
        return HttpResponseForbidden("僅 HR 可查看")
    qs = OvertimeAssignment.objects.filter(status="pending_hr")
    qs_all = OvertimeAssignment.objects.exclude(status="pending_employee")
    return render(
        request,
        "think4u/overtime/hr_list.html",
        {"pending": qs, "all_items": qs_all},
    )


@login_required
@require_http_methods(["POST"])
def hr_overtime_decision(request, pk):
    if not _is_hr(request.user):
        return HttpResponseForbidden()
    ot = get_object_or_404(OvertimeAssignment, pk=pk)
    if ot.status != "pending_hr":
        messages.error(request, _("非待 HR 核准狀態"))
        return redirect("think4u-overtime-hr")
    decision = request.POST.get("decision")
    note = (request.POST.get("hr_note") or "").strip()
    if decision == "approve":
        ot.status = "hr_approved"
        ot.hr_approved_at = timezone.now()
        ot.hr_note = note or None
        ot.save()
        # 通知主管 + 員工
        target_email = ot.employee.employee_user_id.email if ot.employee.employee_user_id else ot.employee.email
        _safe_send(
            f"[加班已核准] {ot.employee} {ot.overtime_date}",
            f"加班已通過 HR 核准。",
            [ot.assigned_by.email, target_email],
        )
        messages.success(request, _("已核准"))
    elif decision == "reject":
        if not note:
            messages.error(request, _("駁回需填寫理由"))
            return redirect("think4u-overtime-hr")
        ot.status = "hr_rejected"
        ot.hr_note = note
        ot.save()
        target_email = ot.employee.employee_user_id.email if ot.employee.employee_user_id else ot.employee.email
        _safe_send(
            f"[加班已駁回] {ot.employee} {ot.overtime_date}",
            f"HR 駁回加班。理由：{note}",
            [ot.assigned_by.email, target_email],
        )
        messages.success(request, _("已駁回"))
    else:
        messages.error(request, _("未知的動作"))
    return redirect("think4u-overtime-hr")
