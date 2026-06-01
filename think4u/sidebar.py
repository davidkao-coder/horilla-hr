"""think4u/sidebar.py — 後台「審核」入口（員工自助操作頁全部移到 /portal/）"""
from django.urls import reverse
from django.utils.translation import gettext_lazy as trans

MENU = trans("審核專區")
IMG_SRC = "images/ui/leave.svg"

SUBMENUS = [
    # 主管端
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
        "menu": trans("主管 — 補打卡審核"),
        "redirect": reverse("think4u-punch-correction-pending"),
        "vis_key": "think4u.punch_correction_pending",
        "accessibility": "think4u.sidebar.manager_accessibility",
    },
    # HR 端
    {
        "menu": trans("HR — 加班核准"),
        "redirect": reverse("think4u-overtime-hr"),
        "vis_key": "think4u.overtime_hr",
        "accessibility": "think4u.sidebar.hr_accessibility",
    },
    {
        "menu": trans("HR — 給假審核"),
        "redirect": reverse("think4u-leave-grant-pending"),
        "vis_key": "think4u.leave_grant",
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
    # Think4U：直屬主管 或 部門主管（Department.manager）皆可進審核專區
    from think4u.manager_utils import is_manager

    return is_manager(request.user) or request.user.is_superuser or _is_hr(request.user)


def hr_accessibility(request, submenu, user_perms, *args, **kwargs):
    return _is_hr(request.user)


def _is_hr(user):
    return user.is_superuser or user.groups.filter(name__in=["人資 HR", "系統管理員"]).exists()
