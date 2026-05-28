"""
Think4U: 每日打卡提醒 — 寄信 + 站內通知給今日尚未打卡的員工。

建議 cron 設定（10:30，週一~週五）:
    30 10 * * 1-5 docker compose exec server python manage.py notify_unpunched

可加 --dry-run 看會通知誰但不真的寄信。
"""
from datetime import date

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from attendance.models import AttendanceActivity
from employee.models import Employee


class Command(BaseCommand):
    help = "提醒當日尚未打卡的員工（Email + 站內通知）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只列印名單，不真的寄信 / 通知",
        )
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="覆寫檢查日期（YYYY-MM-DD），預設今天",
        )

    def handle(self, *args, **options):
        if options["date"]:
            from datetime import datetime

            target = datetime.strptime(options["date"], "%Y-%m-%d").date()
        else:
            target = timezone.localdate()

        # 週末跳過
        if target.weekday() >= 5:
            self.stdout.write(f"{target} 是週末，跳過")
            return

        # 找出今日有 in_punch 的員工
        punched_ids = set(
            AttendanceActivity.objects.filter(
                attendance_date=target,
                clock_in__isnull=False,
            ).values_list("employee_id_id", flat=True)
        )

        to_notify = (
            Employee.objects.filter(is_active=True)
            .exclude(id__in=punched_ids)
            .select_related("employee_user_id")
        )

        count = to_notify.count()
        self.stdout.write(f"今日（{target}）需提醒打卡：{count} 人")
        if options["dry_run"]:
            for emp in to_notify:
                self.stdout.write(f"  - {emp} <{emp.email}>")
            return

        sent_email = 0
        sent_notify = 0
        for emp in to_notify:
            # Email
            if emp.email:
                try:
                    send_mail(
                        subject=f"[Think4U-HRMS] {target} 打卡提醒",
                        message=(
                            f"嗨 {emp.get_full_name()}，\n\n"
                            f"今天 ({target}) 的打卡時間已到（規定 09:30~10:00 內打卡），"
                            f"系統目前還沒有你的打卡紀錄。\n\n"
                            f"請盡快至打卡頁完成打卡：\n"
                            f"  /clock/\n\n"
                            f"若已經打過卡而出現本通知，請聯絡 IT。\n\n"
                            f"-- Think4U HRMS"
                        ),
                        from_email=None,  # 用 settings.DEFAULT_FROM_EMAIL
                        recipient_list=[emp.email],
                        fail_silently=True,
                    )
                    sent_email += 1
                except Exception as e:
                    self.stdout.write(f"  寄信給 {emp} 失敗：{e}")

            # 站內通知（horilla 用 notifications app）
            try:
                from notifications.signals import notify

                if emp.employee_user_id_id:
                    notify.send(
                        emp.employee_user_id,
                        recipient=emp.employee_user_id,
                        verb=f"記得打卡：{target} 尚未打卡",
                        verb_ar=f"تذكير: لم تسجل دخولك بعد لـ {target}",
                        verb_de=f"Erinnerung: Sie haben sich heute ({target}) noch nicht eingestempelt",
                        verb_es=f"Recordatorio: aún no has fichado para {target}",
                        verb_fr=f"Rappel : vous n'avez pas encore pointé pour {target}",
                        icon="time-outline",
                        redirect="/clock/",
                    )
                    sent_notify += 1
            except Exception as e:
                self.stdout.write(f"  站內通知 {emp} 失敗：{e}")

        self.stdout.write(
            self.style.SUCCESS(
                f"完成：寄信 {sent_email} 封 / 站內通知 {sent_notify} 則"
            )
        )
