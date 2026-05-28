"""
Think4U: 刪除超過保留期限的稽核紀錄（預設 3 年）。

建議 cron：每月 1 日凌晨 3 點：
    0 3 1 * * docker compose exec server python manage.py purge_audit_log
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from think4u.models import AuditLog


class Command(BaseCommand):
    help = "刪除超過保留期限的稽核紀錄"

    def add_arguments(self, parser):
        parser.add_argument("--years", type=int, default=3, help="保留年數（預設 3）")
        parser.add_argument("--dry-run", action="store_true", help="只計數不刪除")

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts["years"] * 365)
        qs = AuditLog.objects.filter(timestamp__lt=cutoff)
        n = qs.count()
        if opts["dry_run"]:
            self.stdout.write(f"DRY RUN: 會刪除 {n} 筆（< {cutoff}）")
        else:
            qs.delete()
            self.stdout.write(self.style.SUCCESS(f"已刪除 {n} 筆 audit log（< {cutoff}）"))
