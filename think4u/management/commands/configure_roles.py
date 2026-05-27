"""
WP-08 配置 4 個預設 Auth Group 的 Django permissions + RolePageVisibility。

用法：
    python manage.py configure_roles
    python manage.py configure_roles --dump   # 同時匯出 fixture
"""

from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from base.models import RolePageVisibility


# 4 個 Group 對應的 Django permission codenames
# 注意：codename 為 <action>_<modelname>，例如 view_employee, add_leaverequest
GROUP_PERMS = {
    "系統管理員": "__all__",  # 系統管理員直接拿所有 perm
    "人資 HR": [
        # 員工
        "view_employee", "change_employee", "add_employee",
        "view_employeeworkinformation", "change_employeeworkinformation",
        # 出勤
        "view_attendance", "change_attendance", "view_attendanceactivity",
        # 請假
        "view_leaverequest", "change_leaverequest", "delete_leaverequest",
        "view_leavetype", "view_availableleave", "change_availableleave",
        # 假期 / 公司假
        "view_holidays", "add_holidays", "view_companyleaves", "add_companyleaves",
        # 多重核准
        "view_multipleapprovalcondition", "add_multipleapprovalcondition",
        # think4u
        "view_annualleaverecord", "view_overtimeassignment", "change_overtimeassignment",
    ],
    "部門主管": [
        # 員工（自部門）
        "view_employee", "view_employeeworkinformation",
        # 出勤（自部門）
        "view_attendance", "change_attendance", "view_attendanceactivity",
        # 請假（自部門）
        "view_leaverequest", "change_leaverequest",
        "view_leavetype", "view_availableleave",
        # think4u 加班指派建立
        "add_overtimeassignment", "view_overtimeassignment",
        "change_overtimeassignment",  # 取消自己建的指派
    ],
    "一般員工": [
        # 自己看自己
        "view_employee", "view_employeeworkinformation",
        # 出勤
        "view_attendance", "view_attendanceactivity",
        # 請假
        "add_leaverequest", "view_leaverequest", "view_leavetype",
        "view_availableleave",
        # 加班（自己看自己的）
        "view_overtimeassignment",
    ],
}


# 每個 Group 可見的頂層 sidebar
GROUP_SIDEBARS = {
    "系統管理員": ["employee", "attendance", "leave", "think4u", "base"],
    "人資 HR": ["employee", "attendance", "leave", "think4u", "base"],
    "部門主管": ["employee", "attendance", "leave", "think4u", "base"],
    "一般員工": ["attendance", "leave", "think4u", "base"],
}


class Command(BaseCommand):
    help = "WP-08 設定 4 個 Auth Group 的 permission + RolePageVisibility"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dump", action="store_true", help="同時匯出 fixtures/initial_groups.json"
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        self.stdout.write("=== configure_roles ===")
        for name, perm_codes in GROUP_PERMS.items():
            g, created = Group.objects.get_or_create(name=name)
            if perm_codes == "__all__":
                perms = Permission.objects.all()
            else:
                perms = Permission.objects.filter(codename__in=perm_codes)
            g.permissions.set(perms)
            self.stdout.write(
                f"  Group {name}: {perms.count()} permissions {'(new)' if created else ''}"
            )

            visible_keys = GROUP_SIDEBARS.get(name, [])
            for key, _label in RolePageVisibility.THINK4U_SIDEBAR_CHOICES:
                RolePageVisibility.objects.update_or_create(
                    group=g,
                    sidebar_key=key,
                    defaults={"visible": key in visible_keys},
                )
            self.stdout.write(f"    Visible sidebars: {visible_keys}")

        if opts["dump"]:
            import os
            os.makedirs("fixtures", exist_ok=True)
            with open("fixtures/initial_groups.json", "w", encoding="utf-8") as f:
                call_command(
                    "dumpdata",
                    "auth.group",
                    "base.rolepagevisibility",
                    "--indent",
                    "2",
                    stdout=f,
                )
            self.stdout.write(
                self.style.SUCCESS("已輸出 fixtures/initial_groups.json")
            )

        self.stdout.write(self.style.SUCCESS("完成"))
