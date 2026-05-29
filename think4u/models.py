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
# 角色設定（AdminAccessGroup 擴充 → 通用 RoleSettings）
# ----------------------------------------------------------------------------
# 每個 Auth Group 一筆 row（OneToOne），存控制行為的 flags：
#   - can_access_admin: 該角色可進後台管理（/）
#   - force_admin_only: 該角色強制只能用後台，登入直接跳 / 而不是 /portal/
#                       （適合高管 — 不需要打卡/請假/出勤的角色）
#   - show_in_personal_reports: 該角色員工會出現在個人請假 / 加班報表
#                                （高管設 False → 報表中過濾掉）
# superuser 永遠可進後台、不受 force_admin_only 影響。
# ============================================================================


class AdminAccessGroup(models.Model):
    """歷史名稱 AdminAccessGroup；現在實質上是 per-group RoleSettings。"""
    group = models.OneToOneField(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="admin_access",
        verbose_name=_("角色"),
    )
    can_access_admin = models.BooleanField(default=False, verbose_name=_("可進後台"))
    force_admin_only = models.BooleanField(default=False, verbose_name=_("強制只能用後台"))
    show_in_personal_reports = models.BooleanField(
        default=True, verbose_name=_("顯示在個人加班/請假報表")
    )
    acts_as_superuser = models.BooleanField(
        default=False,
        verbose_name=_("視同 superuser"),
        help_text=_("勾選後，此角色成員自動取得 is_superuser/is_staff 權限"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("角色設定")
        verbose_name_plural = _("角色設定")

    def __str__(self):
        flags = []
        if self.can_access_admin:
            flags.append("後台")
        if self.force_admin_only:
            flags.append("僅後台")
        if not self.show_in_personal_reports:
            flags.append("不入報表")
        return f"{self.group.name}（{', '.join(flags) or '一般'}）"


def user_can_access_admin(user) -> bool:
    """判定使用者是否能進入後台管理"""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return AdminAccessGroup.objects.filter(
        group__in=user.groups.all(), can_access_admin=True
    ).exists()


def user_is_admin_only(user) -> bool:
    """判定使用者是否被強制只能用後台（不顯示前台 portal）
    admin 帳號永遠不受限（避免自己 lock 自己）；其他 user（含 superuser）
    都尊重 force_admin_only flag — 因為 force_admin_only 通常設給高管/系統管理員，
    他們即使是 superuser 也不該被導去前台 portal。
    """
    if not user or not user.is_authenticated:
        return False
    if user.username == "admin":
        return False
    return AdminAccessGroup.objects.filter(
        group__in=user.groups.all(), force_admin_only=True
    ).exists()


def get_hidden_in_reports_employees():
    """回傳「不應出現在個人請假/加班報表」的 Employee queryset"""
    from employee.models import Employee
    from django.contrib.auth.models import Group
    hidden_groups = AdminAccessGroup.objects.filter(
        show_in_personal_reports=False
    ).values_list("group_id", flat=True)
    return Employee.objects.filter(
        employee_user_id__groups__in=hidden_groups
    ).distinct()


# ============================================================================
# 申請給假（員工請求 HR 開啟非預設假別）
# ----------------------------------------------------------------------------
# 預設只給 4 種假：特休、事假、病假、生理假（女性）
# 其他假別（婚假、喪假、產假、公假等）員工要：
#   1. 在前台填「申請給假」表單 + 上傳證明
#   2. HR 在後台審核 + 核發天數
#   3. 核准後系統自動建 AvailableLeave 給該員工
# ============================================================================


class LeaveGrantRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", _("待審核")),
        ("approved", _("已核發")),
        ("rejected", _("已駁回")),
        ("cancelled", _("已取消")),
    ]
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_grant_requests",
        verbose_name=_("員工"),
    )
    leave_type = models.ForeignKey(
        "leave.LeaveType",
        on_delete=models.PROTECT,
        related_name="grant_requests",
        verbose_name=_("假別"),
    )
    requested_days = models.DecimalField(
        max_digits=5, decimal_places=1, verbose_name=_("申請天數")
    )
    reason = models.TextField(verbose_name=_("事由"))
    proof_document = models.FileField(
        upload_to="leave_grants/", null=True, blank=True, verbose_name=_("證明文件")
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending", verbose_name=_("狀態")
    )
    granted_days = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True, verbose_name=_("核發天數")
    )
    hr_note = models.TextField(blank=True, default="", verbose_name=_("HR 批註"))
    decided_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="leave_grants_decided",
        verbose_name=_("審核人"),
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("給假申請")
        verbose_name_plural = _("給假申請")

    def __str__(self):
        return f"{self.employee} | {self.leave_type.name} | {self.requested_hours}h | {self.get_status_display()}"

    @property
    def requested_hours(self) -> float:
        return float(self.requested_days or 0) * 8.0

    @property
    def granted_hours(self):
        if self.granted_days is None:
            return None
        return float(self.granted_days) * 8.0


# 預設 4 種假別名稱（精確 match LeaveType.name）
DEFAULT_LEAVE_TYPE_NAMES = ("特休假", "事假", "病假", "生理假")
FEMALE_ONLY_LEAVE_TYPES = ("生理假",)


def get_default_leave_types_for(employee):
    """回傳該員工應有的預設假別 queryset"""
    from leave.models import LeaveType

    names = list(DEFAULT_LEAVE_TYPE_NAMES)
    if getattr(employee, "gender", None) != "female":
        names = [n for n in names if n not in FEMALE_ONLY_LEAVE_TYPES]
    return LeaveType.objects.filter(name__in=names, is_active=True)


# ============================================================================
# 中央稽核紀錄（AuditLog）
# ----------------------------------------------------------------------------
# 自動透過 signals 攔截所有 model 的 Create / Update / Delete，寫入此表。
# 記錄：時間 / 操作人 / 動作 / model / object / 欄位 舊→新 / IP / URL
# 保留 3 年（用 management command + cron 定期清理）
# ============================================================================


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("CREATE", _("建立")),
        ("UPDATE", _("更新")),
        ("DELETE", _("刪除")),
    ]
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="t4u_audit_logs",
    )
    user_repr = models.CharField(
        max_length=150, blank=True, default="",
        help_text="使用者顯示名稱（即使 User 被刪除也保留）",
    )
    action = models.CharField(max_length=10, choices=ACTION_CHOICES, db_index=True)
    model_label = models.CharField(
        max_length=120, db_index=True,
        help_text="app_label.ModelName",
    )
    object_id = models.CharField(max_length=64, db_index=True, blank=True, default="")
    object_repr = models.CharField(max_length=200, blank=True, default="")
    changes = models.JSONField(
        default=dict, blank=True,
        help_text="UPDATE: {field: [old, new], ...}; CREATE: {field: [null, new]}; DELETE: {__deleted__: {...}}",
    )
    request_path = models.CharField(max_length=300, blank=True, default="")
    request_method = models.CharField(max_length=10, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = _("稽核紀錄")
        verbose_name_plural = _("稽核紀錄")
        indexes = [
            models.Index(fields=["model_label", "object_id"]),
            models.Index(fields=["timestamp"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.user_repr} {self.action} {self.model_label}#{self.object_id}"


# ============================================================================
# 特休 Anniversary 配給細項（Model B：週年獲假 + 歷年使用）
# ----------------------------------------------------------------------------
# 每次 anniversary 拆 2 筆：
#   - small：anniv ~ 該年 12/31 可用
#   - big  ：anniv+1 年 1/1 ~ 12/31 可用
# 一次性 precompute 20 年存進來，不再用 cron。
# ============================================================================


class LeaveAllocation(models.Model):
    GRANT_TYPE_CHOICES = [
        ("six_month", _("滿半年（一次性 3 天）")),
        ("anniv_small", _("週年小段（當年剩餘）")),
        ("anniv_big", _("週年大段（隔年整年）")),
        ("carryforward", _("遞延")),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_allocations",
        verbose_name=_("員工"),
    )
    leave_type = models.ForeignKey(
        "leave.LeaveType",
        on_delete=models.PROTECT,
        related_name="t4u_allocations",
        verbose_name=_("假別"),
    )
    service_years = models.PositiveSmallIntegerField(
        verbose_name=_("累積年資（滿 N 年）")
    )
    anniversary_date = models.DateField(verbose_name=_("獲假日"))
    tier_days = models.DecimalField(
        max_digits=4, decimal_places=1, verbose_name=_("該年 tier 總天數")
    )
    grant_type = models.CharField(
        max_length=20, choices=GRANT_TYPE_CHOICES, verbose_name=_("段類型")
    )
    days_granted = models.DecimalField(
        max_digits=4, decimal_places=1, verbose_name=_("此段天數")
    )
    days_used = models.DecimalField(
        max_digits=4, decimal_places=1, default=0, verbose_name=_("已使用")
    )
    start_date = models.DateField(verbose_name=_("可用起"))
    end_date = models.DateField(verbose_name=_("可用迄"))
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee_id", "start_date"]
        unique_together = ("employee", "leave_type", "anniversary_date", "grant_type")
        indexes = [
            models.Index(fields=["employee", "leave_type", "start_date"]),
        ]
        verbose_name = _("特休配給")
        verbose_name_plural = _("特休配給")

    def __str__(self):
        return f"{self.employee} | 滿{self.service_years}年 {self.get_grant_type_display()} {self.days_granted}天"

    @property
    def days_remaining(self):
        return float(self.days_granted) - float(self.days_used)

    def is_active(self, on: "date | None" = None) -> bool:
        from datetime import date as _d
        on = on or _d.today()
        return self.start_date <= on <= self.end_date


# ============================================================================
# 員工月薪（用於月度出勤統計即時試算薪資 — 扣勞健保）
# ----------------------------------------------------------------------------
# 預設每位員工 50,000；HR 可在月度統計頁即時編輯。
# 勞健保計算邏輯見 think4u/payroll_rules.py（2025 級距表）。
# ============================================================================
class EmployeeSalary(models.Model):
    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name="t4u_salary",
        verbose_name=_("員工"),
    )
    monthly_salary = models.PositiveIntegerField(
        default=50000, verbose_name=_("月薪（NT$）")
    )
    dependents = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("健保眷屬人數")
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("員工月薪")
        verbose_name_plural = _("員工月薪")

    def __str__(self):
        return f"{self.employee} | {self.monthly_salary}"


def get_monthly_salary(employee) -> int:
    """取員工月薪（無紀錄則預設 50000）"""
    row = EmployeeSalary.objects.filter(employee=employee).first()
    return row.monthly_salary if row else 50000
