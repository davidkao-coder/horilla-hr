"""
horilla/config.py

Horilla app configurations
"""

import importlib
import logging

from django.apps import apps
from django.conf import settings
from django.contrib.auth.context_processors import PermWrapper

from horilla.horilla_apps import SIDEBARS

logger = logging.getLogger(__name__)


def get_apps_in_base_dir():
    return SIDEBARS


def import_method(accessibility):
    module_path, method_name = accessibility.rsplit(".", 1)
    module = __import__(module_path, fromlist=[method_name])
    accessibility_method = getattr(module, method_name)
    return accessibility_method


ALL_MENUS = {}


def _build_visibility_checker(request):
    """
    Think4U: 每 request 建一個 visibility lookup，把多次 DB query 合併成 1 次。
    """
    cached = getattr(request, "_t4u_vis", None)
    if cached is not None:
        return cached

    user = request.user

    def _always_true(_=None):
        return True

    if not user.is_authenticated or user.is_superuser:
        request._t4u_vis = _always_true
        return _always_true
    try:
        from base.models import GroupActiveStatus, RolePageVisibility
    except Exception:
        request._t4u_vis = _always_true
        return _always_true

    inactive_ids = set(
        GroupActiveStatus.objects.filter(is_active=False).values_list("group_id", flat=True)
    )
    user_group_ids = [
        gid for gid in user.groups.values_list("pk", flat=True) if gid not in inactive_ids
    ]
    if not user_group_ids:
        request._t4u_vis = _always_true
        return _always_true

    keys_visible, keys_hidden = set(), set()
    for r in RolePageVisibility.objects.filter(group_id__in=user_group_ids).only("sidebar_key", "visible"):
        (keys_visible if r.visible else keys_hidden).add(r.sidebar_key)

    def check(key):
        if not key:
            return True
        if key in keys_visible:
            return True
        if key in keys_hidden:
            return False
        return True

    request._t4u_vis = check
    return check


def _filter_sidebar_by_role(request, apps_list):
    check = _build_visibility_checker(request)
    return [a for a in apps_list if check(a)]


def _submenu_visible(request, vis_key):
    check = _build_visibility_checker(request)
    return check(vis_key)


def sidebar(request):

    base_dir_apps = get_apps_in_base_dir()
    # Think4U WP-X.6: 依角色過濾頂層 sidebar
    base_dir_apps = _filter_sidebar_by_role(request, base_dir_apps)

    if not request.user.is_anonymous:
        request.MENUS = []
        MENUS = request.MENUS

        for app in base_dir_apps:
            if apps.is_installed(app):
                try:
                    sidebar = importlib.import_module(app + ".sidebar")

                except Exception as e:
                    logger.error(e)
                    continue

                if sidebar:
                    accessibility = None
                    if getattr(sidebar, "ACCESSIBILITY", None):
                        accessibility = import_method(sidebar.ACCESSIBILITY)

                    if not accessibility or accessibility(
                        request,
                        sidebar.MENU,
                        PermWrapper(request.user),
                    ):
                        MENU = {}
                        MENU["menu"] = sidebar.MENU
                        MENU["app"] = app
                        MENU["img_src"] = sidebar.IMG_SRC
                        MENU["submenu"] = []
                        MENUS.append(MENU)
                        for submenu in sidebar.SUBMENUS:

                            accessibility = None

                            if submenu.get("accessibility"):
                                accessibility = import_method(submenu["accessibility"])
                            redirect: str = submenu["redirect"]
                            redirect = redirect.split("?")
                            submenu["redirect"] = redirect[0]

                            # Think4U: 子層 visibility 檢查
                            if not _submenu_visible(request, submenu.get("vis_key")):
                                continue

                            if not accessibility or accessibility(
                                request,
                                submenu,
                                PermWrapper(request.user),
                            ):
                                MENU["submenu"].append(submenu)
        ALL_MENUS[request.session.session_key] = MENUS


def get_MENUS(request):
    ALL_MENUS[request.session.session_key] = []
    sidebar(request)
    return {"sidebar": ALL_MENUS.get(request.session.session_key)}
