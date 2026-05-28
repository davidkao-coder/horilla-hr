"""think4u/portal_urls.py — 前台 portal URL (mounted at /portal/)"""
from django.urls import path

from think4u import portal_views

urlpatterns = [
    path("", portal_views.portal_home, name="think4u-portal"),
    path(
        "clock/submit/",
        portal_views.portal_clock_submit,
        name="think4u-portal-clock-submit",
    ),
    path(
        "correction/submit/",
        portal_views.portal_punch_correction_submit,
        name="think4u-portal-correction-submit",
    ),
    path(
        "leave/submit/",
        portal_views.portal_leave_submit,
        name="think4u-portal-leave-submit",
    ),
    path(
        "overtime/submit/",
        portal_views.portal_overtime_submit,
        name="think4u-portal-overtime-submit",
    ),
    path(
        "cancel/<str:kind>/<int:pk>/",
        portal_views.portal_cancel,
        name="think4u-portal-cancel",
    ),
]
