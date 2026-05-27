"""
審核關卡管理頁（Phase 3）
列出所有 (JobPosition × request_type) 工作流程，提供新增 / 編輯 / 移除關卡。
"""
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import Group
from django.db import models as dj_models
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from base.models import Department, JobPosition
from employee.models import Employee
from think4u.models import ApprovalStep, ApprovalWorkflow


def _superuser(user):
    return user.is_active and user.is_superuser


def _patch_save(*models):
    for M in models:
        M.save = dj_models.Model.save  # type: ignore[assignment]


@user_passes_test(_superuser, login_url="/login/")
def workflow_list(request):
    """總覽：所有職位 × 請假/加班 兩列；每列顯示已配置的關卡，可進入編輯。"""
    _patch_save(JobPosition)
    request_types = [("leave", "請假"), ("overtime", "加班")]

    positions = list(
        JobPosition.objects.select_related("department_id").order_by(
            "department_id__department", "job_position"
        )
    )

    # 預先 fetch 所有 workflow + steps，避免 N+1
    workflows = {
        (w.job_position_id, w.request_type): w
        for w in ApprovalWorkflow.objects.prefetch_related(
            "steps", "steps__approver_role", "steps__approver_employee"
        )
    }

    rows = []
    for p in positions:
        for rtype, rlabel in request_types:
            wf = workflows.get((p.id, rtype))
            rows.append(
                {
                    "position": p,
                    "request_type": rtype,
                    "request_type_label": rlabel,
                    "workflow": wf,
                    "steps": list(wf.steps.all().order_by("order")) if wf else [],
                }
            )

    return render(
        request,
        "think4u/approval/workflow_list.html",
        {
            "rows": rows,
            "roles": Group.objects.all().order_by("name"),
            "employees": Employee.objects.filter(is_active=True).order_by(
                "employee_first_name"
            ),
        },
    )


@user_passes_test(_superuser, login_url="/login/")
def workflow_save(request):
    """
    POST: 整批儲存某一條 workflow 的所有 steps。
    欄位：
        position=<job_position_id>
        request_type=<leave|overtime>
        step_count=<N>
        step_<i>_type=<approver_type>
        step_<i>_role=<group_id>
        step_<i>_employee=<employee_id>
    或 delete=1 整條刪除
    """
    if request.method != "POST":
        return redirect("think4u-approval-workflow")

    pos_id = request.POST.get("position")
    rtype = request.POST.get("request_type")
    position = get_object_or_404(JobPosition, pk=pos_id)
    if rtype not in ("leave", "overtime"):
        messages.error(request, "請求類型不正確")
        return redirect("think4u-approval-workflow")

    # 刪除整條
    if request.POST.get("delete"):
        ApprovalWorkflow.objects.filter(
            job_position=position, request_type=rtype
        ).delete()
        messages.success(request, f"已刪除 {position} / {rtype} 的審核流程")
        return redirect("think4u-approval-workflow")

    step_count = int(request.POST.get("step_count") or 0)
    parsed_steps = []
    for i in range(1, step_count + 1):
        atype = (request.POST.get(f"step_{i}_type") or "").strip()
        if not atype:
            continue
        role_id = request.POST.get(f"step_{i}_role") or None
        emp_id = request.POST.get(f"step_{i}_employee") or None

        # 校驗：role 類型一定要選 role；employee 類型一定要選 employee
        if atype == "role" and not role_id:
            messages.error(request, f"第 {i} 關卡為「指定角色」但未選擇角色")
            return redirect("think4u-approval-workflow")
        if atype == "employee" and not emp_id:
            messages.error(request, f"第 {i} 關卡為「指定員工」但未選擇員工")
            return redirect("think4u-approval-workflow")

        parsed_steps.append(
            {
                "type": atype,
                "role_id": int(role_id) if role_id and atype == "role" else None,
                "employee_id": int(emp_id) if emp_id and atype == "employee" else None,
            }
        )

    with transaction.atomic():
        wf, _ = ApprovalWorkflow.objects.get_or_create(
            job_position=position, request_type=rtype
        )
        # 清掉舊 steps 重建（簡單可靠）
        wf.steps.all().delete()
        for idx, s in enumerate(parsed_steps, start=1):
            ApprovalStep.objects.create(
                workflow=wf,
                order=idx,
                approver_type=s["type"],
                approver_role_id=s["role_id"],
                approver_employee_id=s["employee_id"],
            )
        # 若使用者把所有關卡都刪光，順手把 workflow 也清掉
        if not parsed_steps:
            wf.delete()

    messages.success(request, f"已儲存 {position} / {rtype} 的審核流程（{len(parsed_steps)} 關）")
    return redirect("think4u-approval-workflow")
