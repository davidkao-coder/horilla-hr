"""
think4u/audit_views.py — 稽核紀錄查詢頁（superuser only）
"""
from datetime import datetime, timedelta

from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from think4u.models import AuditLog


def _superuser(user):
    return user.is_active and user.is_superuser


@user_passes_test(_superuser, login_url="/portal/")
def audit_log_list(request):
    """稽核紀錄清單 + 過濾"""
    qs = AuditLog.objects.select_related("user").all()

    # 過濾
    fl_user = request.GET.get("user") or ""
    fl_action = request.GET.get("action") or ""
    fl_model = request.GET.get("model") or ""
    fl_object_id = request.GET.get("object_id") or ""
    fl_date_from = request.GET.get("date_from") or ""
    fl_date_to = request.GET.get("date_to") or ""
    fl_q = request.GET.get("q") or ""

    if fl_user:
        qs = qs.filter(user_id=fl_user)
    if fl_action in ("CREATE", "UPDATE", "DELETE"):
        qs = qs.filter(action=fl_action)
    if fl_model:
        qs = qs.filter(model_label__icontains=fl_model)
    if fl_object_id:
        qs = qs.filter(object_id=fl_object_id)
    if fl_date_from:
        try:
            d = datetime.strptime(fl_date_from, "%Y-%m-%d").date()
            qs = qs.filter(timestamp__date__gte=d)
        except ValueError:
            pass
    if fl_date_to:
        try:
            d = datetime.strptime(fl_date_to, "%Y-%m-%d").date()
            qs = qs.filter(timestamp__date__lte=d)
        except ValueError:
            pass
    if fl_q:
        qs = qs.filter(object_repr__icontains=fl_q)

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page", 1))

    # 統計
    distinct_models = (
        AuditLog.objects.order_by("model_label").values_list(
            "model_label", flat=True
        ).distinct()
    )
    users = User.objects.filter(t4u_audit_logs__isnull=False).distinct().order_by("username")

    return render(
        request,
        "think4u/audit/log_list.html",
        {
            "page": page,
            "total_count": paginator.count,
            "distinct_models": distinct_models,
            "users": users,
            "filters": {
                "user": fl_user,
                "action": fl_action,
                "model": fl_model,
                "object_id": fl_object_id,
                "date_from": fl_date_from,
                "date_to": fl_date_to,
                "q": fl_q,
            },
        },
    )


@user_passes_test(_superuser, login_url="/portal/")
def audit_log_detail(request, pk):
    """單筆稽核紀錄詳細"""
    log = get_object_or_404(AuditLog.objects.select_related("user"), pk=pk)
    # 解出 deleted snapshot（template 不能直接讀 __deleted__）
    deleted_snapshot = (log.changes or {}).get("__deleted__", {}) if log.action == "DELETE" else {}
    # 同 object 的歷史紀錄
    related = AuditLog.objects.filter(
        model_label=log.model_label, object_id=log.object_id
    ).exclude(pk=log.pk).order_by("-timestamp")[:30]
    return render(
        request,
        "think4u/audit/log_detail.html",
        {"log": log, "deleted_snapshot": deleted_snapshot, "related": related},
    )
