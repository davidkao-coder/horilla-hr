"""
leave/sidebar.py
"""

from django.apps import apps
from django.urls import reverse
from django.utils.translation import gettext_lazy as trans

from base.templatetags.basefilters import is_leave_approval_manager, is_reportingmanager
from leave.templatetags.leavefilters import is_compensatory

MENU = trans("Leave")
IMG_SRC = "images/ui/leave.svg"

SUBMENUS = [
    {
        "menu": trans("Dashboard"),
        "redirect": reverse("leave-dashboard"),
        "vis_key": "leave.dashboard",
        "accessibility": "leave.sidebar.dashboard_accessibility",
    },
    {
        "menu": trans("My Leave Requests"),
        "redirect": reverse("user-request-view"),
        "vis_key": "leave.my",
    },
    {
        "menu": trans("Leave Requests"),
        "redirect": reverse("request-view"),
        "vis_key": "leave.requests",
        "accessibility": "leave.sidebar.leave_request_accessibility",
    },
    {
        "menu": trans("Leave Types"),
        "redirect": reverse("type-view"),
        "vis_key": "leave.types",
        "accessibility": "leave.sidebar.type_accessibility",
    },
    {
        "menu": trans("Assigned Leave"),
        "redirect": reverse("assign-view"),
        "vis_key": "leave.assigned",
        "accessibility": "leave.sidebar.assign_accessibility",
    },
    {
        "menu": trans("Holidays"),
        "redirect": reverse("holiday-view"),
        "vis_key": "leave.holidays",
        "accessibility": "leave.sidebar.holiday_accessibility",
    },
    {
        "menu": trans("Company Leaves"),
        "redirect": reverse("company-leave-view"),
        "vis_key": "leave.company_leaves",
        "accessibility": "leave.sidebar.company_leave_accessibility",
    },
    {
        "menu": trans("Employee Leave Overview"),
        "redirect": reverse("employee-leave-overview"),
        "vis_key": "leave.overview",
        "accessibility": "leave.sidebar.employee_leave_overview_accessibility",
    },
]


def dashboard_accessibility(request, submenu, user_perms, *args, **kwargs):
    have_perm = request.user.has_perm("leave.view_leaverequest")
    if not have_perm:
        submenu["redirect"] = reverse("leave-employee-dashboard") + "?dashboard=true"
    return True


def leave_request_accessibility(request, submenu, user_perms, *args, **kwargs):
    return (
        request.user.has_perm("leave.view_leaverequest")
        or is_leave_approval_manager(request.user)
        or is_reportingmanager(request.user)
    )


def type_accessibility(request, submenu, user_perms, *args, **kwargs):
    return request.user.has_perm("leave.view_leavetype")


def assign_accessibility(request, submenu, user_perm, *args, **kwargs):
    submenu["redirect"] = submenu["redirect"] + "?field=leave_type_id"
    return request.user.has_perm("leave.view_availableleave") or is_reportingmanager(
        request.user
    )


def holiday_accessibility(request, submenu, user_perms, *args, **kwargs):
    return not request.user.is_superuser and not request.user.has_perm(
        "base.view_holidays"
    )


def company_leave_accessibility(request, submenu, user_perms, *args, **kwargs):
    return not request.user.is_superuser and not request.user.has_perm(
        "base.view_companyleaves"
    )


def restrict_leave_accessibility(request, submenu, user_perms, *args, **kwargs):
    return not request.user.is_superuser and not request.user.has_perm(
        "leave.view_restrictleave"
    )


def employee_leave_overview_accessibility(request, submenu, user_perms, *args, **kwargs):
    """Think4U WP-X.7: HR / 主管 / 系統管理員可看請假總覽"""
    return (
        request.user.is_superuser
        or request.user.has_perm("leave.view_availableleave")
        or is_reportingmanager(request.user)
    )


if apps.is_installed("attendance"):
    SUBMENUS.append(
        {
            "menu": trans("Compensatory Leave Requests"),
            "redirect": reverse("view-compensatory-leave"),
            "accessibility": "leave.sidebar.componstory_accessibility",
        }
    )

    def componstory_accessibility(request, submenu, user_perms, *args, **kwargs):
        return is_compensatory(request.user)
