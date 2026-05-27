"""
base/sidebar.py

Think4U 客製：將「組織圖」拉到頂層 sidebar（WP-X.4）。
原本組織圖在員工 sub-menu 內，現以獨立模組呈現。
"""

from django.urls import reverse
from django.utils.translation import gettext_lazy as trans

MENU = trans("Organization Chart")
IMG_SRC = "images/ui/employees.svg"

SUBMENUS = [
    {
        "menu": trans("Organization Chart"),
        "redirect": reverse("organisation-chart"),
        "vis_key": "base.org_chart",
    },
    {
        "menu": trans("組織編輯"),
        "redirect": reverse("think4u-org-edit"),
        "vis_key": "base.org_edit",
        "accessibility": "base.sidebar.org_edit_accessibility",
    },
    {
        "menu": trans("部門管理"),
        "redirect": reverse("think4u-dept-manage"),
        "vis_key": "base.dept_manage",
        "accessibility": "base.sidebar.org_edit_accessibility",
    },
    {
        "menu": trans("職位管理"),
        "redirect": reverse("think4u-position-manage"),
        "vis_key": "base.position_manage",
        "accessibility": "base.sidebar.org_edit_accessibility",
    },
]


def org_edit_accessibility(request, submenu, user_perms, *args, **kwargs):
    return request.user.is_superuser
