from django.apps import AppConfig


class Think4uConfig(AppConfig):
    """Think4U 客製模組集"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "think4u"
    verbose_name = "Think4U Customizations"

    def ready(self):
        # 連上中央稽核紀錄的 signals
        from think4u import audit_log  # noqa: F401
        # 連上「系統管理員 group 成員 → 自動 superuser」signal
        from think4u import role_sync  # noqa: F401
