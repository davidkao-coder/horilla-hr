"""
think4u/role_sync.py — 把標記 acts_as_superuser=True 的角色成員自動視同 superuser

舊版寫死 SUPER_GROUPS = {"系統管理員"}；
新版改成由角色維護頁的「視同 superuser」flag (AdminAccessGroup.acts_as_superuser)
動態決定哪些 group 觸發升級。

設定方法：後台 → 配置 → 角色維護 → 點某角色的「⚙️ 角色設定」→ 勾選「視同 superuser」

m2m_changed signal 在 user.groups 變動時即時同步；
AdminAccessGroup.save / delete 的 signal 也會重算受影響的所有 user。
"""
from django.contrib.auth.models import Group, User
from django.db.models.signals import m2m_changed, post_save, post_delete
from django.dispatch import receiver


def _super_group_ids():
    """回傳所有 acts_as_superuser=True 的 group id 集合（避免循環 import）"""
    from think4u.models import AdminAccessGroup
    return set(
        AdminAccessGroup.objects.filter(acts_as_superuser=True).values_list(
            "group_id", flat=True
        )
    )


def _sync_user_super(user: User) -> None:
    """重算 user.is_superuser / is_staff，根據其 group 是否有 acts_as_superuser"""
    super_ids = _super_group_ids()
    in_super = user.groups.filter(pk__in=super_ids).exists()
    changed = False
    if in_super and not user.is_superuser:
        user.is_superuser = True
        user.is_staff = True
        changed = True
    elif (not in_super) and user.is_superuser and user.username != "admin":
        # 移除標記 / 移除 group 時自動撤銷 superuser（admin 永遠保留）
        user.is_superuser = False
        user.is_staff = False
        changed = True
    if changed:
        user.save(update_fields=["is_superuser", "is_staff"])


@receiver(m2m_changed, sender=User.groups.through)
def sync_on_group_change(sender, instance, action, reverse, pk_set, **kwargs):
    """User.groups 變動時觸發"""
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    if not reverse:
        _sync_user_super(instance)
    else:
        # instance 是 Group；pk_set 是 user ids
        if pk_set:
            for user in User.objects.filter(pk__in=pk_set):
                _sync_user_super(user)
        elif action == "post_clear":
            for user in User.objects.all():
                _sync_user_super(user)


@receiver(post_save)
def sync_on_rolesettings_save(sender, instance, **kwargs):
    """AdminAccessGroup.acts_as_superuser 變動時，重算該 group 所有成員"""
    if sender.__name__ != "AdminAccessGroup":
        return
    for user in User.objects.filter(groups=instance.group):
        _sync_user_super(user)


@receiver(post_delete)
def sync_on_rolesettings_delete(sender, instance, **kwargs):
    """AdminAccessGroup 被刪掉時，重算該 group 所有成員"""
    if sender.__name__ != "AdminAccessGroup":
        return
    for user in User.objects.filter(groups=instance.group):
        _sync_user_super(user)


def sync_all() -> tuple[int, int]:
    """一次同步所有現存使用者；回傳 (升級數, 降級數)"""
    upgraded = downgraded = 0
    super_ids = _super_group_ids()
    for u in User.objects.all():
        in_super = u.groups.filter(pk__in=super_ids).exists()
        if in_super and not u.is_superuser:
            u.is_superuser = True
            u.is_staff = True
            u.save(update_fields=["is_superuser", "is_staff"])
            upgraded += 1
        elif (not in_super) and u.is_superuser and u.username != "admin":
            u.is_superuser = False
            u.is_staff = False
            u.save(update_fields=["is_superuser", "is_staff"])
            downgraded += 1
    return upgraded, downgraded
