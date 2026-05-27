"""think4u/sidebar.py — 加班指派 + 雙層審核入口"""
from django.urls import reverse
from django.utils.translation import gettext_lazy as trans

MENU = trans("加班 / 審核")
IMG_SRC = "images/ui/leave.svg"

SUBMENUS = [
    {
        "menu": trans("我的申請與狀態"),
        "redirect": reverse("think4u-approval-employee"),
        "vis_key": "think4u.my_status",
    },
    {
        "menu": trans("我的加班"),
        "redirect": reverse("think4u-overtime-employee"),
        "vis_key": "think4u.my_overtime",
    },
    {
        "menu": trans("主管 — 指派加班"),
        "redirect": reverse("think4u-overtime-manager"),
        "vis_key": "think4u.overtime_manager",
        "accessibility": "think4u.sidebar.manager_accessibility",
    },
    {
        "menu": trans("主管 — 審核專區"),
        "redirect": reverse("think4u-approval-manager"),
        "vis_key": "think4u.approval_manager",
        "accessibility": "think4u.sidebar.manager_accessibility",
    },
    {
        "menu": trans("HR — 加班核准"),
        "redirect": reverse("think4u-overtime-hr"),
        "vis_key": "think4u.overtime_hr",
        "accessibility": "think4u.sidebar.hr_accessibility",
    },
    {
        "menu": trans("HR — 雙層審核專區"),
        "redirect": reverse("think4u-approval-hr"),
        "vis_key": "think4u.approval_hr",
        "accessibility": "think4u.sidebar.hr_accessibility",
    },
]


def manager_accessibility(request, submenu, user_perms, *args, **kwargs):
    from base.templatetags.basefilters import is_reportingmanager

    return is_reportingmanager(request.user) or request.user.is_superuser or _is_hr(request.user)


def hr_accessibility(request, submenu, user_perms, *args, **kwargs):
    return _is_hr(request.user)


def _is_hr(user):
    return user.is_superuser or user.groups.filter(name__in=["人資 HR", "系統管理員"]).exists()
