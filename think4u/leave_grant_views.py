"""
think4u/leave_grant_views.py — HR 給假審核（後台）

員工在前台「申請給假」提交 LeaveGrantRequest 後，HR 在此頁審核 + 核發天數。
核准時自動建立 / 增加 AvailableLeave。
"""
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db import models as dj_models
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from leave.models import AvailableLeave
from think4u.models import LeaveGrantRequest


def _is_hr(user) -> bool:
    return user.is_authenticated and (
        user.is_superuser
        or user.groups.filter(name__in=["人資 HR", "系統管理員"]).exists()
    )


@user_passes_test(_is_hr, login_url="/portal/")
def leave_grant_pending(request):
    """待審 + 全部歷史"""
    show_all = request.GET.get("all") == "1"
    qs = LeaveGrantRequest.objects.select_related("employee", "leave_type").order_by(
        "-created_at"
    )
    if not show_all:
        qs = qs.filter(status="pending")
    return render(
        request,
        "think4u/leave_grant/pending.html",
        {
            "requests": qs,
            "show_all": show_all,
        },
    )


@user_passes_test(_is_hr, login_url="/portal/")
def leave_grant_decide(request, pk):
    if request.method != "POST":
        return redirect("think4u-leave-grant-pending")

    req = get_object_or_404(LeaveGrantRequest, pk=pk)
    if req.status != "pending":
        messages.error(request, "此申請已不在待審核狀態")
        return redirect("think4u-leave-grant-pending")

    decision = request.POST.get("decision")
    granted_days = request.POST.get("granted_days")
    note = (request.POST.get("hr_note") or "").strip()

    with transaction.atomic():
        AvailableLeave.save = dj_models.Model.save
        if decision == "approve":
            try:
                days = float(granted_days) if granted_days else float(req.requested_days)
                if days <= 0:
                    raise ValueError
            except ValueError:
                messages.error(request, "核發天數不合法")
                return redirect("think4u-leave-grant-pending")

            # 建立 / 增加 AvailableLeave
            avail, created = AvailableLeave.objects.get_or_create(
                employee_id=req.employee,
                leave_type_id=req.leave_type,
                defaults={"available_days": days, "carryforward_days": 0},
            )
            if not created:
                avail.available_days = (avail.available_days or 0) + days
                avail.save()

            req.status = "approved"
            req.granted_days = days
            req.decided_by = request.user
            req.decided_at = timezone.now()
            req.hr_note = note
            req.save()
            messages.success(
                request,
                f"已核發 {req.employee} 「{req.leave_type.name}」{days} 天",
            )
        elif decision == "reject":
            req.status = "rejected"
            req.decided_by = request.user
            req.decided_at = timezone.now()
            req.hr_note = note
            req.save()
            messages.success(request, "已駁回")
        else:
            messages.error(request, "未知的決定")

    return redirect("think4u-leave-grant-pending")
