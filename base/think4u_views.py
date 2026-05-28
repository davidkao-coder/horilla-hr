"""
base/think4u_views.py

Think4U客製 view 集合：
- 角色頁面可見性設定（樹狀，含子選單）
- 角色管理：新增 / 改名 / 停用 / 啟用
"""

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import Group
from django.shortcuts import redirect, render

from base.models import (
    GroupActiveStatus,
    RolePageVisibility,
    THINK4U_SIDEBAR_TREE,
    think4u_all_keys,
)
from think4u.models import AdminAccessGroup


def _superuser_required(view_func):
    return user_passes_test(
        lambda u: u.is_active and u.is_superuser,
        login_url="/login/",
    )(view_func)


def _is_group_active(group) -> bool:
    s = getattr(group, "think4u_status", None)
    return s.is_active if s else True


ALL_KEYS = [k for k, _label in think4u_all_keys()]


@_superuser_required
def role_visibility_view(request):
    """
    角色頁面可見性（樹狀） + 角色管理。
    POST action：
      visibility — 儲存可見性矩陣（含所有頂層 + 子層 key）
      create     — 新增角色
      rename     — 改角色名稱
      toggle     — 啟用 / 停用
    """
    if request.method == "POST":
        action = request.POST.get("action", "visibility")

        if action == "create":
            name = (request.POST.get("name") or "").strip()
            if not name:
                messages.error(request, "角色名稱不可為空")
            elif Group.objects.filter(name=name).exists():
                messages.error(request, f"角色「{name}」已存在")
            else:
                g = Group.objects.create(name=name)
                GroupActiveStatus.objects.create(group=g, is_active=True)
                # 預設 visibility：全部可見
                for key in ALL_KEYS:
                    RolePageVisibility.objects.create(
                        group=g, sidebar_key=key, visible=True
                    )
                messages.success(request, f"已新增角色：{name}")
            return redirect(request.path)

        if action == "rename":
            pk = request.POST.get("pk")
            name = (request.POST.get("name") or "").strip()
            g = Group.objects.filter(pk=pk).first()
            if not g or not name:
                messages.error(request, "找不到角色或名稱為空")
            elif Group.objects.filter(name=name).exclude(pk=pk).exists():
                messages.error(request, f"角色名稱「{name}」與其他角色重複")
            else:
                old = g.name
                g.name = name
                g.save()
                messages.success(request, f"已改名：{old} → {name}")
            return redirect(request.path)

        if action == "toggle":
            pk = request.POST.get("pk")
            g = Group.objects.filter(pk=pk).first()
            if not g:
                messages.error(request, "找不到角色")
                return redirect(request.path)
            status, _ = GroupActiveStatus.objects.get_or_create(
                group=g, defaults={"is_active": True}
            )
            if status.is_active:
                user_count = g.user_set.count()
                if user_count > 0:
                    messages.error(
                        request,
                        f"角色「{g.name}」仍有 {user_count} 位成員，請先移除後再停用",
                    )
                else:
                    status.is_active = False
                    status.save()
                    messages.success(request, f"已停用：{g.name}")
            else:
                status.is_active = True
                status.save()
                messages.success(request, f"已啟用：{g.name}")
            return redirect(request.path)

        if action == "settings":
            # Think4U: 儲存「角色設定」（後台可進入 / 強制後台 / 顯示在報表）
            pk = request.POST.get("pk")
            g = Group.objects.filter(pk=pk).first()
            if not g:
                messages.error(request, "找不到角色")
                return redirect(request.path)
            obj, _ = AdminAccessGroup.objects.get_or_create(group=g)
            obj.can_access_admin = "can_access_admin" in request.POST
            obj.force_admin_only = "force_admin_only" in request.POST
            obj.show_in_personal_reports = "show_in_personal_reports" in request.POST
            obj.acts_as_superuser = "acts_as_superuser" in request.POST
            obj.save()  # AdminAccessGroup post_save signal 會自動 sync 該 group 成員的 is_superuser
            messages.success(request, f"已儲存「{g.name}」的角色設定")
            return redirect(request.path)

        # action == "visibility" — 單一角色的可見性
        pk = request.POST.get("pk")
        g = Group.objects.filter(pk=pk).first()
        if not g:
            messages.error(request, "找不到角色")
            return redirect(request.path)
        n = 0
        for key in ALL_KEYS:
            field = f"vis__{key}"
            visible = field in request.POST
            RolePageVisibility.objects.update_or_create(
                group=g, sidebar_key=key, defaults={"visible": visible}
            )
            n += 1
        messages.success(request, f"已儲存「{g.name}」的 {n} 筆頁面可見性")
        return redirect(request.path)

    # ---- GET ----
    groups = Group.objects.all().order_by("name")
    existing = {
        (r.group_id, r.sidebar_key): r.visible for r in RolePageVisibility.objects.all()
    }

    # 為每個 group 建立樹狀資料
    role_rows = []
    for g in groups:
        tree = []
        for parent_key, parent_label, children in THINK4U_SIDEBAR_TREE:
            child_nodes = [
                {
                    "key": ck,
                    "label": cl,
                    "visible": existing.get((g.pk, ck), True),
                }
                for ck, cl in children
            ]
            tree.append(
                {
                    "key": parent_key,
                    "label": parent_label,
                    "visible": existing.get((g.pk, parent_key), True),
                    "children": child_nodes,
                }
            )
        # Think4U: 取得該 group 的 RoleSettings（AdminAccessGroup）
        rs = AdminAccessGroup.objects.filter(group=g).first()
        role_rows.append(
            {
                "group": g,
                "is_active": _is_group_active(g),
                "user_count": g.user_set.count(),
                "tree": tree,
                "can_access_admin": rs.can_access_admin if rs else False,
                "force_admin_only": rs.force_admin_only if rs else False,
                "show_in_personal_reports": rs.show_in_personal_reports if rs else True,
                "acts_as_superuser": rs.acts_as_superuser if rs else False,
            }
        )

    return render(
        request,
        "base/think4u/role_visibility.html",
        {"role_rows": role_rows},
    )
