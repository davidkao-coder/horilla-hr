"""
think4u/templatetags/think4u_filters.py — Think4U 模板過濾器
"""
from django import template

register = template.Library()


@register.filter(name="t4u_can_use_portal")
def t4u_can_use_portal(user):
    """該使用者是否可使用前台 portal（非 force_admin_only 角色）。
    後台 topbar 用來決定是否顯示「前往前台」按鈕。"""
    from think4u.models import user_is_admin_only

    try:
        return bool(user and user.is_authenticated) and not user_is_admin_only(user)
    except Exception:
        return False
