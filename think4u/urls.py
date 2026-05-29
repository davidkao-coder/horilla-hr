"""think4u URL patterns（在 horilla/urls.py include）"""
from django.urls import path

from think4u import (
    approval_views,
    approval_workflow_views,
    attendance_exports,
    audit_views,
    day_detail_views,
    leave_grant_views,
    monthly_attendance_views,
    org_views,
    overtime_views,
    punch_correction_views,
)

urlpatterns = [
    # 組織結構圖編輯（admin only）
    path("org/edit/", org_views.org_edit, name="think4u-org-edit"),
    path("org/dept/", org_views.dept_manage, name="think4u-dept-manage"),
    path("org/position/", org_views.position_manage, name="think4u-position-manage"),
    path(
        "api/position-default-role/",
        org_views.position_default_role,
        name="think4u-position-default-role",
    ),
    # 審核關卡管理（Phase 3）
    path(
        "approval-workflow/",
        approval_workflow_views.workflow_list,
        name="think4u-approval-workflow",
    ),
    path(
        "approval-workflow/save/",
        approval_workflow_views.workflow_save,
        name="think4u-approval-workflow-save",
    ),
    # WP-07 雙層審核專區
    path(
        "approval/manager/",
        approval_views.manager_dashboard,
        name="think4u-approval-manager",
    ),
    path(
        "approval/hr/",
        approval_views.hr_dashboard,
        name="think4u-approval-hr",
    ),
    path(
        "approval/employee/",
        approval_views.employee_dashboard,
        name="think4u-approval-employee",
    ),
    # WP-03 出勤匯出
    path(
        "attendance/export/",
        attendance_exports.export_form,
        name="think4u-attendance-export",
    ),
    path(
        "attendance/export/excel/",
        attendance_exports.export_excel,
        name="think4u-attendance-export-excel",
    ),
    # 月度出勤統計
    path(
        "attendance/monthly/",
        monthly_attendance_views.monthly_attendance,
        name="think4u-attendance-monthly",
    ),
    path(
        "attendance/salary/update/",
        monthly_attendance_views.update_salary,
        name="think4u-salary-update",
    ),
    # 某員工某天打卡明細
    path(
        "attendance/day/<int:emp_id>/<str:ymd>/",
        day_detail_views.day_detail,
        name="think4u-attendance-day-detail",
    ),
    # 稽核紀錄（superuser only）
    path("audit-log/", audit_views.audit_log_list, name="think4u-audit-log"),
    path(
        "audit-log/<int:pk>/",
        audit_views.audit_log_detail,
        name="think4u-audit-log-detail",
    ),

    # 給假申請審核（HR）
    path(
        "leave-grant/pending/",
        leave_grant_views.leave_grant_pending,
        name="think4u-leave-grant-pending",
    ),
    path(
        "leave-grant/<int:pk>/decide/",
        leave_grant_views.leave_grant_decide,
        name="think4u-leave-grant-decide",
    ),

    # 補打卡申請（員工端）
    path(
        "punch-correction/my/",
        punch_correction_views.my_requests,
        name="think4u-punch-correction-my",
    ),
    path(
        "punch-correction/<int:pk>/cancel/",
        punch_correction_views.cancel_request,
        name="think4u-punch-correction-cancel",
    ),
    # 補打卡審核（審核人端）
    path(
        "punch-correction/pending/",
        punch_correction_views.pending_for_me,
        name="think4u-punch-correction-pending",
    ),
    path(
        "punch-correction/<int:pk>/decide/",
        punch_correction_views.decide,
        name="think4u-punch-correction-decide",
    ),
    # 加班指派 WP-04
    path(
        "overtime/manager/",
        overtime_views.manager_overtime_list,
        name="think4u-overtime-manager",
    ),
    path(
        "overtime/manager/new/",
        overtime_views.manager_overtime_create,
        name="think4u-overtime-create",
    ),
    path(
        "overtime/manager/<int:pk>/cancel/",
        overtime_views.manager_overtime_cancel,
        name="think4u-overtime-cancel",
    ),
    path(
        "overtime/employee/",
        overtime_views.employee_overtime_list,
        name="think4u-overtime-employee",
    ),
    path(
        "overtime/employee/<int:pk>/decision/",
        overtime_views.employee_overtime_decision,
        name="think4u-overtime-emp-decision",
    ),
    path(
        "overtime/hr/",
        overtime_views.hr_overtime_list,
        name="think4u-overtime-hr",
    ),
    path(
        "overtime/hr/<int:pk>/decision/",
        overtime_views.hr_overtime_decision,
        name="think4u-overtime-hr-decision",
    ),
]
