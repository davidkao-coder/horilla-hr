"""
組織結構圖 admin 編輯（WP- 補丁）
superuser 可批次更新員工的部門 / 職位 / 職務 / 主管。
"""
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import Group
from django.db import models as dj_models
from django.shortcuts import redirect, render

from base.models import Company, Department, JobPosition
from employee.models import Employee, EmployeeWorkInformation


def _patch_save(*models):
    """Horilla 多個 base model 的 save() 不接 kwargs；shell / view 環境繞過"""
    for M in models:
        M.save = dj_models.Model.save  # type: ignore[assignment]


def _superuser(user):
    return user.is_active and user.is_superuser


def _build_dept_tree():
    """根據 parent_department 組出部門樹"""
    all_depts = list(Department.objects.all().order_by("department"))
    by_parent = {}
    for d in all_depts:
        by_parent.setdefault(d.parent_department_id, []).append(d)

    def build(parent_id=None, depth=0):
        out = []
        for d in by_parent.get(parent_id, []):
            out.append({"dept": d, "depth": depth})
            out.extend(build(d.id, depth + 1))
        return out

    return build(None, 0)


def _descendant_ids(dept_id):
    """回傳某部門及其所有後代的 id 集合（防止循環掛載）"""
    result = {dept_id}
    queue = [dept_id]
    while queue:
        pid = queue.pop()
        for child_id in Department.objects.filter(parent_department_id=pid).values_list("id", flat=True):
            if child_id not in result:
                result.add(child_id)
                queue.append(child_id)
    return result


@user_passes_test(_superuser, login_url="/login/")
def org_edit(request):
    """組織編輯：設定每個部門的上級部門 + 部門主管"""
    _patch_save(Department)

    if request.method == "POST":
        n_changed = 0
        skipped = []
        for d in Department.objects.all():
            # 上級部門
            new_parent = request.POST.get(f"parent_{d.id}") or None
            new_parent_id = int(new_parent) if new_parent else None
            # 部門主管
            new_mgr = request.POST.get(f"manager_{d.id}") or None
            new_mgr_id = int(new_mgr) if new_mgr else None

            changed = False
            # 處理 parent
            if new_parent_id != d.parent_department_id:
                if new_parent_id is not None and new_parent_id in _descendant_ids(d.id):
                    skipped.append(d.department)
                else:
                    d.parent_department_id = new_parent_id
                    changed = True
            # 處理 manager
            if new_mgr_id != d.manager_id:
                d.manager_id = new_mgr_id
                changed = True

            if changed:
                d.save()
                n_changed += 1

        if skipped:
            messages.error(
                request,
                f"以下部門因會造成循環從屬關係而未更新：{', '.join(skipped)}",
            )
        messages.success(request, f"已更新 {n_changed} 筆部門資訊")
        return redirect("think4u-org-edit")

    tree = _build_dept_tree()
    # 預先計算每個部門的有效主管（含回溯）
    for row in tree:
        d = row["dept"]
        row["effective_manager"] = d.get_effective_manager()
    return render(
        request,
        "think4u/org/edit.html",
        {
            "tree": tree,
            "all_departments": Department.objects.all().order_by("department"),
            "all_employees": Employee.objects.filter(is_active=True).order_by(
                "employee_first_name"
            ),
        },
    )


# ============================================================================
# 部門管理
# ============================================================================
@user_passes_test(_superuser, login_url="/login/")
def dept_manage(request):
    _patch_save(Department, JobPosition)
    company = Company.objects.first()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            name = (request.POST.get("name") or "").strip()
            if name and not Department.objects.filter(department=name).exists():
                d = Department.objects.create(department=name)
                if company:
                    d.company_id.add(company)
                messages.success(request, f"已新增部門：{name}")
            else:
                messages.error(request, "部門名稱重複或為空")
        elif action == "rename":
            pk = request.POST.get("pk")
            name = (request.POST.get("name") or "").strip()
            d = Department.objects.filter(pk=pk).first()
            if d and name:
                d.department = name
                d.save()
                messages.success(request, f"已重新命名為 {name}")
        elif action == "delete":
            pk = request.POST.get("pk")
            d = Department.objects.filter(pk=pk).first()
            if not d:
                messages.error(request, "找不到部門")
            else:
                pos_cnt = JobPosition.objects.filter(department_id=d).count()
                emp_cnt = EmployeeWorkInformation.objects.filter(department_id=d).count()
                if pos_cnt or emp_cnt:
                    messages.error(
                        request,
                        f"無法刪除 {d.department}：仍有 {pos_cnt} 個職位、{emp_cnt} 名員工。",
                    )
                else:
                    d.delete()
                    messages.success(request, "已刪除")
        return redirect("think4u-dept-manage")

    # Think4U 效能：用 annotate 一次撈完，避免 N+1
    from django.db.models import Count

    rows = []
    depts = (
        Department.objects.all()
        .annotate(
            _pos_count=Count("job_position", distinct=True),
            _emp_count=Count("employeeworkinformation", distinct=True),
        )
        .order_by("department")
    )
    for d in depts:
        rows.append(
            {
                "obj": d,
                "pos_count": d._pos_count,
                "emp_count": d._emp_count,
            }
        )
    return render(request, "think4u/org/dept_manage.html", {"rows": rows})


# ============================================================================
# 職位管理
# ============================================================================
@user_passes_test(_superuser, login_url="/login/")
def position_manage(request):
    _patch_save(Department, JobPosition)
    company = Company.objects.first()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            name = (request.POST.get("name") or "").strip()
            dept_id = request.POST.get("dept")
            role_id = request.POST.get("role") or None
            dept = Department.objects.filter(pk=dept_id).first()
            if name and dept and not JobPosition.objects.filter(
                job_position=name, department_id=dept
            ).exists():
                p = JobPosition.objects.create(
                    job_position=name,
                    department_id=dept,
                    default_role_id=int(role_id) if role_id else None,
                )
                if company:
                    p.company_id.add(company)
                messages.success(request, f"已新增職位：{name} ({dept})")
            else:
                messages.error(request, "職位名稱重複、部門無效或為空")
        elif action == "rename":
            pk = request.POST.get("pk")
            name = (request.POST.get("name") or "").strip()
            role_id = request.POST.get("role") or None
            p = JobPosition.objects.filter(pk=pk).first()
            if p and name:
                p.job_position = name
                p.default_role_id = int(role_id) if role_id else None
                p.save()
                messages.success(request, f"已重新命名為 {name}")
        elif action == "delete":
            pk = request.POST.get("pk")
            p = JobPosition.objects.filter(pk=pk).first()
            if not p:
                messages.error(request, "找不到職位")
            else:
                emp_cnt = EmployeeWorkInformation.objects.filter(job_position_id=p).count()
                if emp_cnt:
                    messages.error(
                        request,
                        f"無法刪除 {p.job_position}：仍有 {emp_cnt} 名員工屬於此職位。",
                    )
                else:
                    p.delete()
                    messages.success(request, "已刪除")
        return redirect("think4u-position-manage")

    # Think4U 效能：annotate 一次撈完，避免 N+1
    from django.db.models import Count

    positions = (
        JobPosition.objects.select_related("department_id")
        .annotate(_emp_count=Count("employeeworkinformation", distinct=True))
        .order_by("department_id__department", "job_position")
    )
    rows = [{"obj": p, "emp_count": p._emp_count} for p in positions]
    return render(
        request,
        "think4u/org/position_manage.html",
        {
            "rows": rows,
            "departments": Department.objects.all().order_by("department"),
            "roles": Group.objects.all().order_by("name"),
        },
    )


# API：取得 JobPosition default_role（員工編輯頁 JS 用）
from django.http import JsonResponse


def position_default_role(request):
    pid = request.GET.get("pk")
    if not pid:
        return JsonResponse({"role_id": None})
    p = JobPosition.objects.filter(pk=pid).first()
    if not p or not p.default_role_id:
        return JsonResponse({"role_id": None})
    return JsonResponse(
        {"role_id": p.default_role_id, "role_name": p.default_role.name}
    )
