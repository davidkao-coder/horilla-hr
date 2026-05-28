"""
base/think4u_clock.py

Think4U客製 WP-X.2 + WP-02：
- Landing page（雙入口）
- 打卡頁（公司網路 TOTP / 外勤 IP）
- 每日 TOTP 驗證碼（24h 週期）
"""

from datetime import date, datetime, time

import pyotp
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from attendance.models import AttendanceActivity
from base.context_processors import biometric_app_exists  # noqa: F401


def _get_totp() -> pyotp.TOTP:
    """每日驗證碼：interval=86400(24h)；secret 從 env 取，須為合法 Base32"""
    secret = getattr(settings, "DAILY_VERIFICATION_CODE_SECRET", None) or "THINKFOURHRMSCLOCKDAILYTOTPSECRE"
    return pyotp.TOTP(secret, interval=86400, digits=6)


def get_today_code() -> str:
    return _get_totp().now()


def verify_code(code: str) -> bool:
    if not code:
        return False
    return _get_totp().verify(code, valid_window=1)


def get_client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


@login_required
def landing_page(request):
    """登入後的入口選擇頁。
    有後台權限 → 顯示「後台管理 + 前台 portal」兩個入口
    無後台權限 → 直接導向前台 portal
    """
    from think4u.models import user_can_access_admin

    if not user_can_access_admin(request.user):
        return redirect("/portal/")

    return render(
        request,
        "base/think4u/landing.html",
        {
            "user": request.user,
            "employee": getattr(request.user, "employee_get", None),
        },
    )


@login_required
def clock_page(request):
    """打卡主頁"""
    user = request.user
    emp = getattr(user, "employee_get", None)
    if not emp:
        return HttpResponseBadRequest("尚未綁定員工資料")

    today = timezone.localdate()
    today_punches = (
        AttendanceActivity.objects.filter(employee_id=emp, attendance_date=today)
        .order_by("clock_in")
    )

    # superuser / HR 可看當日驗證碼
    show_code = user.is_superuser or user.groups.filter(name__in=["人資 HR", "系統管理員"]).exists()

    return render(
        request,
        "base/think4u/clock.html",
        {
            "employee": emp,
            "today": today,
            "today_punches": today_punches,
            "todays_code": get_today_code() if show_code else None,
            "client_ip": get_client_ip(request),
            "show_code": show_code,
        },
    )


@login_required
@require_http_methods(["POST"])
def clock_submit(request):
    """處理打卡 POST"""
    user = request.user
    emp = getattr(user, "employee_get", None)
    if not emp:
        return HttpResponseBadRequest("尚未綁定員工資料")

    action = request.POST.get("action")  # 'in' or 'out'
    a_type = request.POST.get("attendance_type", "office")
    code = (request.POST.get("verification_code") or "").strip()
    reason = (request.POST.get("field_reason") or "").strip()
    client_ip = get_client_ip(request)

    if a_type not in ("office", "field"):
        messages.error(request, _("無效的打卡類型"))
        return redirect("think4u-clock")

    # 公司打卡：須驗證碼
    if a_type == "office":
        if not verify_code(code):
            messages.error(request, _("驗證碼錯誤或已過期"))
            return redirect("think4u-clock")
    # 外勤打卡：須填原因
    else:
        if not reason:
            messages.error(request, _("外勤打卡必須填寫原因"))
            return redirect("think4u-clock")

    now = timezone.localtime()
    today = now.date()

    if action == "in":
        # 上班打卡：建立新 AttendanceActivity
        AttendanceActivity.objects.create(
            employee_id=emp,
            attendance_date=today,
            clock_in_date=today,
            clock_in=now.time(),
            in_datetime=now,
            attendance_type=a_type,
            field_reason=reason or None,
            client_ip=client_ip,
            verification_code_used=code[:2] + "****" if code else None,
        )
        messages.success(request, _("上班打卡成功：{}").format(now.strftime("%H:%M:%S")))
    elif action == "out":
        # 下班打卡：找今天最後一筆未打下班的紀錄補上
        last = (
            AttendanceActivity.objects.filter(
                employee_id=emp, attendance_date=today, clock_out__isnull=True
            )
            .order_by("-clock_in")
            .first()
        )
        if not last:
            messages.error(request, _("尚未上班打卡，無法下班打卡"))
            return redirect("think4u-clock")
        last.clock_out_date = today
        last.clock_out = now.time()
        last.out_datetime = now
        last.save()
        messages.success(request, _("下班打卡成功：{}").format(now.strftime("%H:%M:%S")))
    else:
        messages.error(request, _("未知的打卡動作"))
    return redirect("think4u-clock")
