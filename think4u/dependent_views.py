"""
think4u/dependent_views.py — 健保眷屬（加保）維護

在員工「工作資訊」編輯頁以 HTMX 管理：新增 / 刪除眷屬，
加保人數自動回寫 EmployeeSalary.dependents（影響健保自付額）。
"""
from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_POST

from employee.models import Employee
from think4u.models import HealthInsuranceDependent, sync_dependent_count


def _can_edit(user) -> bool:
    return user.is_superuser or user.has_perm("employee.change_employeeworkinformation")


def _render_section(request, employee):
    deps = HealthInsuranceDependent.objects.filter(employee=employee)
    enrolled = deps.filter(is_enrolled=True).count()
    return render(
        request,
        "think4u/salary/dependents_section.html",
        {
            "employee": employee,
            "dependents": deps,
            "enrolled_count": enrolled,
            "billed_count": min(enrolled, 3),
            "can_edit": _can_edit(request.user),
            "relation_choices": HealthInsuranceDependent.RELATION_CHOICES,
        },
    )


@login_required
def dependent_section(request, emp_id):
    """回傳某員工的眷屬區塊（HTMX 載入用）"""
    employee = Employee.objects.filter(id=emp_id).first()
    if not employee:
        return render(request, "think4u/salary/dependents_section.html", {"dependents": []})
    return _render_section(request, employee)


@login_required
@require_POST
def dependent_add(request, emp_id):
    employee = Employee.objects.filter(id=emp_id).first()
    if not employee or not _can_edit(request.user):
        return _render_section(request, employee) if employee else render(
            request, "think4u/salary/dependents_section.html", {"dependents": []}
        )
    name = (request.POST.get("name") or "").strip()
    if name:
        def _parse_date(v):
            try:
                return date.fromisoformat(v) if v else None
            except (TypeError, ValueError):
                return None

        HealthInsuranceDependent.objects.create(
            employee=employee,
            name=name,
            relationship=request.POST.get("relationship") or "spouse",
            national_id=(request.POST.get("national_id") or "").strip(),
            birth_date=_parse_date(request.POST.get("birth_date")),
            enroll_date=_parse_date(request.POST.get("enroll_date")),
            is_enrolled=request.POST.get("is_enrolled", "on") in ("on", "true", "1", "True"),
        )
        sync_dependent_count(employee)
    return _render_section(request, employee)


@login_required
@require_POST
def dependent_delete(request, dep_id):
    dep = HealthInsuranceDependent.objects.filter(id=dep_id).first()
    if not dep or not _can_edit(request.user):
        return render(request, "think4u/salary/dependents_section.html", {"dependents": []})
    employee = dep.employee
    dep.delete()
    sync_dependent_count(employee)
    return _render_section(request, employee)


@login_required
@require_POST
def dependent_toggle(request, dep_id):
    """切換加保 / 退保"""
    dep = HealthInsuranceDependent.objects.filter(id=dep_id).first()
    if not dep or not _can_edit(request.user):
        return render(request, "think4u/salary/dependents_section.html", {"dependents": []})
    dep.is_enrolled = not dep.is_enrolled
    dep.save(update_fields=["is_enrolled"])
    sync_dependent_count(dep.employee)
    return _render_section(request, dep.employee)
