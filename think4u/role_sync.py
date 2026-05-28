"""
think4u/role_sync.py — 把「系統管理員」group 成員自動視為 superuser

User Steven 等帳號雖然加入了「系統管理員」group，但 Django 預設不會自動
設 `is_superuser=True` / `is_staff=True`，導致很多地方 `if user.is_superuser`
直接擋掉他，顯示頁面跟 admin 不一致。

本 module 用 m2m_changed signal 監聽 user.groups 變動，當有人被加入或移除
SUPER_GROUPS 時即時同步 is_superuser / is_staff。
"""
from django.contrib.auth.models import Group, User
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

# 視同 superuser 的 group 名稱（之後可以改成從 model 讀）
SUPER_GROUPS = {"系統管理員"}


def _sync_user_super(user: User) -> None:
    """重算 user.is_superuser 和 is_staff，根據其 group 成員資格"""
    in_super = user.groups.filter(name__in=SUPER_GROUPS).exists()
    changed = False
    if in_super and not user.is_superuser:
        user.is_superuser = True
        user.is_staff = True
        changed = True
    elif (not in_super) and user.is_superuser and user.username != "admin":
        # 注意：移除 group 時自動撤銷 superuser（保留 admin 帳號永遠 super）
        user.is_superuser = False
        user.is_staff = False
        changed = True
    if changed:
        user.save(update_fields=["is_superuser", "is_staff"])


@receiver(m2m_changed, sender=User.groups.through)
def sync_super_on_group_change(sender, instance, action, reverse, pk_set, **kwargs):
    """
    User.groups 變動時觸發。
    - action='post_add' / 'post_remove' / 'post_clear' 才同步
    - reverse=False：instance=User，pk_set=Group ids
    - reverse=True ：instance=Group，pk_set=User ids
    """
    if action not in ("post_add", "post_remove", "post_clear"):
        return

    if not reverse:
        # User-side: instance 是 User
        _sync_user_super(instance)
    else:
        # Group-side: instance 是 Group，pk_set 是被加/移的 user ids
        if instance.name not in SUPER_GROUPS:
            return
        if pk_set:
            for user in User.objects.filter(pk__in=pk_set):
                _sync_user_super(user)
        elif action == "post_clear":
            # post_clear 沒給 pk_set，全表掃一次（罕見路徑）
            for user in User.objects.all():
                _sync_user_super(user)


def sync_all() -> tuple[int, int]:
    """一次同步所有現存使用者；回傳 (升級數, 降級數)"""
    upgraded = downgraded = 0
    for u in User.objects.all():
        in_super = u.groups.filter(name__in=SUPER_GROUPS).exists()
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
