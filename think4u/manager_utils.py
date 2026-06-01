"""
think4u/manager_utils.py — 主管判定 / 部屬範圍（同時支援 Horilla 直屬主管 + Think4U 部門主管）

Horilla 原生 is_reportingmanager 只認 EmployeeWorkInformation.reporting_manager_id；
Think4U 另有 Department.manager（部門主管）。本工具把兩者合併，讓部門主管也算主管、
也能看到所管部門（含子部門）的部屬。
"""
from employee.models import Employee, EmployeeWorkInformation


def _managed_department_ids(employee):
    """該員工擔任 Department.manager 的部門 id（含子部門遞迴）"""
    from base.models import Department

    direct = set(
        Department.objects.filter(manager=employee).values_list("id", flat=True)
    )
    if not direct:
        return set()
    all_ids = set(direct)
    queue = list(direct)
    while queue:
        pid = queue.pop()
        for cid in Department.objects.filter(
            parent_department_id=pid
        ).values_list("id", flat=True):
            if cid not in all_ids:
                all_ids.add(cid)
                queue.append(cid)
    return all_ids


def is_manager(user) -> bool:
    """是否為主管：Horilla 直屬主管 或 Think4U 部門主管。"""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    emp = getattr(user, "employee_get", None)
    if not emp:
        return False
    # Horilla 直屬主管
    if EmployeeWorkInformation.objects.filter(reporting_manager_id=emp).exists():
        return True
    # Think4U 部門主管
    return bool(_managed_department_ids(emp))


def managed_employees(user):
    """回傳該主管可管的員工 queryset（直屬下屬 ∪ 所管部門含子部門成員 ∪ 自己）。"""
    emp = getattr(user, "employee_get", None)
    if not emp:
        return Employee.objects.none()
    dept_ids = _managed_department_ids(emp)
    from django.db.models import Q

    q = Q(employee_work_info__reporting_manager_id=emp) | Q(pk=emp.pk)
    if dept_ids:
        q |= Q(employee_work_info__department_id__in=dept_ids)
    return Employee.objects.filter(q, is_active=True).distinct()
