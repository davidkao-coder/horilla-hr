"""
WP-07 雙層審核專區 — 把請假 + 加班的待審核項目綜合在一個 dashboard 內。
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import render

from base.templatetags.basefilters import is_reportingmanager
from employee.models import Employee
from leave.models import LeaveRequest
from think4u.models import OvertimeAssignment, get_hidden_in_reports_employees


def _is_hr(user):
    return user.is_superuser or user.groups.filter(
        name__in=["人資 HR", "系統管理員"]
    ).exists()


@login_required
def manager_dashboard(request):
    """主管綜合審核：自己部門員工的請假 + 加班"""
    from think4u.manager_utils import is_manager, managed_employees

    user = request.user
    if not (is_manager(user) or _is_hr(user)):
        return HttpResponseForbidden("僅主管可查看")
    emp = getattr(user, "employee_get", None)
    # Think4U: 排除「不顯示在報表」的角色成員
    hidden_ids = list(get_hidden_in_reports_employees().values_list("id", flat=True))
    # 取下屬（直屬主管 ∪ 部門主管所管部門含子部門）
    if _is_hr(user):
        my_subs = Employee.objects.filter(is_active=True).exclude(id__in=hidden_ids)
        scope = "全公司"
    else:
        my_subs = managed_employees(user).exclude(id__in=hidden_ids)
        scope = "自部門"

    leave_pending = LeaveRequest.objects.filter(
        employee_id__in=my_subs, status="requested"
    ).select_related("employee_id", "leave_type_id")
    overtime_pending = OvertimeAssignment.objects.filter(
        assigned_by=user, status="pending_employee"
    ).select_related("employee")  # 主管自己建的待員工確認

    return render(
        request,
        "think4u/approval/manager.html",
        {
            "scope": scope,
            "leave_pending": leave_pending,
            "overtime_pending": overtime_pending,
            "subs_count": my_subs.count(),
        },
    )


@login_required
def hr_dashboard(request):
    """HR 第二層審核：全公司待 HR 核准的請假 + 加班"""
    user = request.user
    if not _is_hr(user):
        return HttpResponseForbidden("僅 HR 可查看")
    # Think4U: 排除「不顯示在報表」的角色成員
    hidden_ids = list(get_hidden_in_reports_employees().values_list("id", flat=True))
    # 請假狀態：Horilla 的 'approved_first_level' 或本系統使用之 status
    # Horilla 預設 status: requested / approved / cancelled / rejected — 二層審核需要由 multi-approval 條件決定
    leave_pending = (
        LeaveRequest.objects.filter(status="approved")
        .exclude(employee_id__in=hidden_ids)
        .select_related("employee_id", "leave_type_id")
    )  # 第二層審核時的狀態
    # 加班待 HR 核准
    overtime_pending = (
        OvertimeAssignment.objects.filter(status="pending_hr")
        .exclude(employee__in=hidden_ids)
        .select_related("employee")
    )

    return render(
        request,
        "think4u/approval/hr.html",
        {
            "leave_pending": leave_pending,
            "overtime_pending": overtime_pending,
        },
    )


@login_required
def employee_dashboard(request):
    """員工：自己的申請與狀態"""
    user = request.user
    emp = getattr(user, "employee_get", None)
    if not emp:
        return HttpResponseForbidden("尚未綁定員工")
    leaves = LeaveRequest.objects.filter(employee_id=emp).order_by("-start_date")[:30]
    overtimes = OvertimeAssignment.objects.filter(employee=emp).order_by(
        "-overtime_date"
    )[:30]
    return render(
        request,
        "think4u/approval/employee.html",
        {"leaves": leaves, "overtimes": overtimes},
    )
