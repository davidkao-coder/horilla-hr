"""
think4u/models.py

Think4U 客製化 model 集合。
- AnnualLeaveRecord：勞基法歷年制特休紀錄（WP-05）
- OvertimeAssignment：主管由上而下指派加班 + 雙層審核（WP-04）
"""

from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _

from base.models import JobPosition
from employee.models import Employee


class AnnualLeaveRecord(models.Model):
    """
    WP-05 歷年制特休年度紀錄。
    一名員工一個年度可以有多筆（source 不同）：
    - annual_reset：每年 1/1 重置給假
    - six_month_grant：到職滿 6 個月當天補給 3 天
    - carry_over：從前一年遞延進來
    """

    SOURCE_CHOICES = [
        ("annual_reset", _("每年 1/1 重置")),
        ("six_month_grant", _("滿 6 個月補給")),
        ("carry_over", _("遞延進來")),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="think4u_annual_leave",
        verbose_name=_("Employee"),
    )
    year = models.IntegerField(verbose_name=_("Year"))
    allocated_days = models.DecimalField(
        max_digits=4, decimal_places=1, verbose_name=_("Allocated Days")
    )
    used_days = models.DecimalField(
        max_digits=4, decimal_places=1, default=0, verbose_name=_("Used Days")
    )
    carried_over = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=0,
        verbose_name=_("Carried Over from Prev Year"),
    )
    carry_over_expire = models.DateField(
        null=True, blank=True, verbose_name=_("Carry-over Expire Date")
    )
    source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, verbose_name=_("Source")
    )
    note = models.CharField(
        max_length=200, blank=True, default="", verbose_name=_("Note")
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("employee", "year", "source")
        ordering = ["-year", "employee_id"]
        verbose_name = _("Annual Leave Record")
        verbose_name_plural = _("Annual Leave Records")

    def __str__(self):
        return f"{self.employee} | {self.year} | {self.source} | {self.allocated_days}"

    @property
    def remaining(self):
        return float(self.allocated_days) - float(self.used_days)


class OvertimeAssignment(models.Model):
    """
    WP-04 主管 → 員工 top-down 加班指派 + 雙層審核。
    狀態機：
        pending_employee → employee_confirmed → pending_hr → hr_approved
                       ↘ employee_rejected
                                              ↘ hr_rejected
        pending_employee → cancelled (主管在員工確認前取消)
    """

    STATUS_CHOICES = [
        ("pending_employee", _("待員工確認")),
        ("employee_confirmed", _("員工已確認")),
        ("employee_rejected", _("員工拒絕")),
        ("pending_hr", _("待 HR 核准")),
        ("hr_approved", _("HR 已核准")),
        ("hr_rejected", _("HR 駁回")),
        ("cancelled", _("已取消")),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="overtime_assignments",
        verbose_name=_("Employee"),
    )
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="overtime_assigned_by_me",
        verbose_name=_("Assigned By"),
    )
    overtime_date = models.DateField(verbose_name=_("Overtime Date"))
    start_time = models.TimeField(verbose_name=_("Start Time"))
    end_time = models.TimeField(verbose_name=_("End Time"))
    reason = models.TextField(verbose_name=_("Reason"))
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="pending_employee",
        verbose_name=_("Status"),
    )
    employee_note = models.TextField(
        null=True, blank=True, verbose_name=_("Employee Note")
    )
    hr_note = models.TextField(null=True, blank=True, verbose_name=_("HR Note"))
    employee_confirmed_at = models.DateTimeField(null=True, blank=True)
    hr_approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-overtime_date", "-created_at"]
        verbose_name = _("Overtime Assignment")
        verbose_name_plural = _("Overtime Assignments")

    def __str__(self):
        return f"{self.employee} | {self.overtime_date} | {self.get_status_display()}"

    @property
    def duration_hours(self) -> float:
        """加班時長（小時）— 跨日不適用"""
        from datetime import datetime, timedelta

        d = datetime.combine(self.overtime_date, self.start_time)
        e = datetime.combine(self.overtime_date, self.end_time)
        if e < d:
            e += timedelta(days=1)
        return (e - d).total_seconds() / 3600.0


# ============================================================================
# 審核關卡（Approval Workflow）
# ----------------------------------------------------------------------------
# 目的：針對「特定職位 × 申請類型」（請假 / 加班），定義審核關卡序列。
# 例：產品經理請假 → [直屬主管, 部門主管, HR]
#     工程師加班 → [直屬主管, HR]
#
# 關卡 approver_type：
#   - direct_manager : 直屬主管（由部門 manager + get_effective_manager 推導）
#   - department_head: 部門主管（從員工所屬部門往上找第一個有 manager 的部門）
#   - role           : 指定角色（Auth Group）— 此角色內任一人皆可審
#   - employee       : 指定特定員工
#   - hr             : HR（由 role=HR 群組成員處理；保留以便日後切換實作）
# ============================================================================


class ApprovalWorkflow(models.Model):
    """一個 (職位 × 申請類型) 對應一條審核流程"""

    REQUEST_TYPE_CHOICES = [
        ("leave", _("請假")),
        ("overtime", _("加班")),
        ("punch_correction", _("補打卡")),
    ]

    job_position = models.ForeignKey(
        JobPosition,
        on_delete=models.CASCADE,
        related_name="approval_workflows",
        verbose_name=_("適用職位"),
    )
    request_type = models.CharField(
        max_length=20,
        choices=REQUEST_TYPE_CHOICES,
        verbose_name=_("申請類型"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("啟用"))
    note = models.CharField(
        max_length=200, blank=True, default="", verbose_name=_("備註")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("job_position", "request_type")
        ordering = ["job_position__department_id", "job_position__job_position", "request_type"]
        verbose_name = _("審核流程")
        verbose_name_plural = _("審核流程")

    def __str__(self):
        return f"{self.job_position} / {self.get_request_type_display()}"


class ApprovalStep(models.Model):
    """單一審核關卡（隸屬一條 ApprovalWorkflow）"""

    APPROVER_TYPE_CHOICES = [
        ("direct_manager", _("直屬主管")),
        ("department_head", _("部門主管")),
        ("role", _("指定角色")),
        ("employee", _("指定員工")),
        ("hr", _("HR")),
    ]

    workflow = models.ForeignKey(
        ApprovalWorkflow,
        on_delete=models.CASCADE,
        related_name="steps",
        verbose_name=_("所屬流程"),
    )
    order = models.PositiveSmallIntegerField(
        default=1, verbose_name=_("順序")
    )
    approver_type = models.CharField(
        max_length=30,
        choices=APPROVER_TYPE_CHOICES,
        verbose_name=_("審核人類型"),
    )
    # 當 approver_type == role
    approver_role = models.ForeignKey(
        "auth.Group",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_steps",
        verbose_name=_("指定角色"),
    )
    # 當 approver_type == employee
    approver_employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_steps_as_approver",
        verbose_name=_("指定員工"),
    )

    class Meta:
        ordering = ["workflow_id", "order"]
        unique_together = ("workflow", "order")
        verbose_name = _("審核關卡")
        verbose_name_plural = _("審核關卡")

    def __str__(self):
        return f"#{self.order} {self.get_approver_type_display()}"

    def label(self) -> str:
        """供 UI 顯示的人類可讀標籤"""
        if self.approver_type == "role" and self.approver_role:
            return f"角色：{self.approver_role.name}"
        if self.approver_type == "employee" and self.approver_employee:
            return f"員工：{self.approver_employee}"
        return self.get_approver_type_display()


# ============================================================================
# 補打卡申請 (Punch Correction Request)
# ----------------------------------------------------------------------------
# 員工漏打卡時，可提出補打卡申請；走 ApprovalWorkflow 審核流程
# (request_type = 'punch_correction')，核准後自動寫入 AttendanceActivity。
# ============================================================================


class PunchCorrectionRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", _("待審核")),
        ("approved", _("已核准")),
        ("rejected", _("已駁回")),
        ("applied", _("已套用")),  # 核准且已寫回 AttendanceActivity
        ("cancelled", _("已取消")),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="punch_corrections",
        verbose_name=_("員工"),
    )
    target_date = models.DateField(verbose_name=_("補打卡日期"))
    requested_check_in = models.TimeField(
        null=True, blank=True, verbose_name=_("補的上班時間")
    )
    requested_check_out = models.TimeField(
        null=True, blank=True, verbose_name=_("補的下班時間")
    )
    reason = models.TextField(verbose_name=_("申請事由"))
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending", verbose_name=_("狀態")
    )
    workflow = models.ForeignKey(
        ApprovalWorkflow,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="punch_correction_requests",
        verbose_name=_("套用流程"),
    )
    current_step_order = models.PositiveSmallIntegerField(
        default=1, verbose_name=_("目前審核關卡")
    )
    decisions = models.JSONField(
        default=list, blank=True, verbose_name=_("審核記錄")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-target_date", "-created_at"]
        verbose_name = _("補打卡申請")
        verbose_name_plural = _("補打卡申請")

    def __str__(self):
        return f"{self.employee} | {self.target_date} | {self.get_status_display()}"


# ============================================================================
# 員工主動加班申請（OvertimeApplication）
# ----------------------------------------------------------------------------
# 與 OvertimeAssignment 並存：
#   - OvertimeAssignment：主管由上而下指派加班（top-down）
#   - OvertimeApplication：員工自己主動申請加班（bottom-up）走 ApprovalWorkflow
# ============================================================================


class OvertimeApplication(models.Model):
    STATUS_CHOICES = [
        ("pending", _("待審核")),
        ("approved", _("已核准")),
        ("rejected", _("已駁回")),
        ("cancelled", _("已取消")),
    ]
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="overtime_applications",
        verbose_name=_("員工"),
    )
    overtime_date = models.DateField(verbose_name=_("加班日期"))
    start_time = models.TimeField(verbose_name=_("開始時間"))
    end_time = models.TimeField(verbose_name=_("結束時間"))
    reason = models.TextField(verbose_name=_("加班事由"))
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending", verbose_name=_("狀態")
    )
    workflow = models.ForeignKey(
        ApprovalWorkflow,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="overtime_applications",
        verbose_name=_("套用流程"),
    )
    current_step_order = models.PositiveSmallIntegerField(
        default=1, verbose_name=_("目前審核關卡")
    )
    decisions = models.JSONField(
        default=list, blank=True, verbose_name=_("審核記錄")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-overtime_date", "-created_at"]
        verbose_name = _("加班申請")
        verbose_name_plural = _("加班申請")

    def __str__(self):
        return f"{self.employee} | {self.overtime_date} | {self.get_status_display()}"

    @property
    def duration_hours(self) -> float:
        from datetime import datetime, timedelta

        d = datetime.combine(self.overtime_date, self.start_time)
        e = datetime.combine(self.overtime_date, self.end_time)
        if e < d:
            e += timedelta(days=1)
        return (e - d).total_seconds() / 3600.0


# ============================================================================
# 後台存取群組（AdminAccessGroup）
# ----------------------------------------------------------------------------
# 此表內的 Auth Group 成員，才能進入後台管理（/）。
# 不在表內的人，登入後一律導到前台 portal（/portal/）。
# superuser 永遠可進後台。
# ============================================================================


class AdminAccessGroup(models.Model):
    group = models.OneToOneField(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="admin_access",
        verbose_name=_("角色"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("後台存取角色")
        verbose_name_plural = _("後台存取角色")

    def __str__(self):
        return f"{self.group.name}（可進後台）"


def user_can_access_admin(user) -> bool:
    """判定使用者是否能進入後台管理"""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return AdminAccessGroup.objects.filter(group__in=user.groups.all()).exists()
