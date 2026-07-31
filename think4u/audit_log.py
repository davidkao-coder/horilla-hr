"""
think4u/audit_log.py — 中央稽核紀錄 signal handlers

每個 model 的 post_save / post_delete 都會自動寫入一筆 AuditLog 記錄。
透過 horilla_middlewares._thread_locals 抓 request 的 user / IP / path。

排除掉系統雜訊 model（自己、Session、HistoricalXXX、Permission、Notification 等）。
"""
import logging
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from horilla.horilla_middlewares import _thread_locals

logger = logging.getLogger(__name__)

# ============ 排除清單（避免噪音 + 避免無窮迴圈）============
EXCLUDED_LABELS = {
    "think4u.AuditLog",                      # 自己
    "sessions.Session",
    "contenttypes.ContentType",
    "admin.LogEntry",
    "auth.Permission",
    "notifications.Notification",           # 通知量太大
    "auditlog.LogEntry",                    # 套件自帶
    "simple_history.HistoricalRecords",
    # ★ MigrationRecorder 用 ORM 寫 django_migrations，每套用一個 migration 就觸發一次
    #   post_save。全新 DB 執行 migrate 時 think4u_auditlog 還不存在（該表由第 83 個
    #   migration think4u.0007 才建立），handler 去 INSERT 會失敗；即使被 except 接住，
    #   PostgreSQL 的 transaction 已被污染 → 接在後面的 DDL 一併 rollback，
    #   症狀是 auth.0001_initial 報「django_content_type does not exist」。
    #   必須排除，否則全新環境無法初始化。
    "migrations.Migration",
    # Horilla 自家 history rows（會 auto-create 一堆）
    # — 動態判斷 model.__name__ startswith 'Historical'
}


def _is_excluded(sender) -> bool:
    label = f"{sender._meta.app_label}.{sender.__name__}"
    if label in EXCLUDED_LABELS:
        return True
    # simple_history 產生的 HistoricalXXX
    if sender.__name__.startswith("Historical"):
        return True
    # session-like
    if "session" in label.lower():
        return True
    return False


# ============ 序列化任意 Python 值為 JSON-friendly ============
def _serialize(value):
    if value is None:
        return None
    if isinstance(value, (str, int, bool, float)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    # FieldFile
    if hasattr(value, "name") and hasattr(value, "url"):
        try:
            return value.name
        except Exception:
            return repr(value)
    # FK / model instance
    if hasattr(value, "_meta") and hasattr(value, "pk"):
        try:
            return f"{value._meta.label}#{value.pk} ({str(value)[:50]})"
        except Exception:
            return f"{value._meta.label}#{value.pk}"
    # Fallback
    try:
        return str(value)
    except Exception:
        return repr(value)


# ============ 從 thread-local 抓 request context ============
def _get_request_context():
    request = getattr(_thread_locals, "request", None)
    if not request:
        return None, "", "", "", None
    user = getattr(request, "user", None)
    user = user if (user and user.is_authenticated) else None
    user_repr = (
        user.get_username() if user else "anonymous/system"
    )
    path = getattr(request, "path", "")[:300]
    method = getattr(request, "method", "")[:10]
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = (xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")) or None
    return user, user_repr, path, method, ip


# ============ Signals ============
@receiver(pre_save)
def _capture_original(sender, instance, **kwargs):
    """更新時抓 DB 原值，附在 instance 上供 post_save 比對"""
    if _is_excluded(sender):
        return
    if not instance.pk:
        return  # 新建，無原值
    try:
        instance._t4u_audit_original = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        pass
    except Exception as e:
        logger.debug(f"audit pre_save 抓原值失敗 {sender}: {e}")


@receiver(post_save)
def _log_save(sender, instance, created, **kwargs):
    if _is_excluded(sender):
        return
    from think4u.models import AuditLog  # avoid circular at app load

    user, user_repr, path, method, ip = _get_request_context()
    label = f"{sender._meta.app_label}.{sender.__name__}"

    try:
        if created:
            changes = {}
            for f in instance._meta.concrete_fields:
                try:
                    val = getattr(instance, f.attname, None)
                    changes[f.name] = [None, _serialize(val)]
                except Exception:
                    pass
        else:
            original = getattr(instance, "_t4u_audit_original", None)
            if original is None:
                return  # 沒抓到原值，跳過
            changes = {}
            for f in instance._meta.concrete_fields:
                try:
                    old = getattr(original, f.attname, None)
                    new = getattr(instance, f.attname, None)
                    if old != new:
                        changes[f.name] = [_serialize(old), _serialize(new)]
                except Exception:
                    pass
            if not changes:
                return  # 沒實際變動

        # ★ 必須包 atomic：稽核寫入失敗時只回滾到 savepoint，不污染外層 transaction。
        #   否則（PostgreSQL）失敗的 INSERT 會讓整個 transaction 進入 aborted 狀態，
        #   即使這裡 except 接住，呼叫端「原本要做的那件事」也會一起失敗。
        #   稽核是附帶功能，絕不該讓它拖垮業務操作。
        with transaction.atomic():
            AuditLog.objects.create(
                user=user,
                user_repr=user_repr,
                action="CREATE" if created else "UPDATE",
                model_label=label,
                object_id=str(instance.pk) if instance.pk else "",
                object_repr=str(instance)[:200],
                changes=changes,
                request_path=path,
                request_method=method,
                ip_address=ip,
            )
    except Exception as e:
        logger.warning(f"audit log 寫入失敗 {label}: {e}")


@receiver(post_delete)
def _log_delete(sender, instance, **kwargs):
    if _is_excluded(sender):
        return
    from think4u.models import AuditLog

    user, user_repr, path, method, ip = _get_request_context()
    label = f"{sender._meta.app_label}.{sender.__name__}"

    try:
        snapshot = {}
        for f in instance._meta.concrete_fields:
            try:
                snapshot[f.name] = _serialize(getattr(instance, f.attname, None))
            except Exception:
                pass

        # ★ 同 _log_save：包 atomic 以 savepoint 隔離，稽核失敗不得拖垮外層 transaction
        with transaction.atomic():
            AuditLog.objects.create(
                user=user,
                user_repr=user_repr,
                action="DELETE",
                model_label=label,
                object_id=str(instance.pk) if instance.pk else "",
                object_repr=str(instance)[:200],
                changes={"__deleted__": snapshot},
                request_path=path,
                request_method=method,
                ip_address=ip,
            )
    except Exception as e:
        logger.warning(f"audit log 刪除紀錄寫入失敗 {label}: {e}")
