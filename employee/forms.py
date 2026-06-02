"""
forms.py

This module contains the form classes used in the application.

Each form represents a specific functionality or data input in the
application. They are responsible for validating
and processing user input data.

Classes:
- YourForm: Represents a form for handling specific data input.

Usage:
from django import forms

class YourForm(forms.Form):
    field_name = forms.CharField()

    def clean_field_name(self):
        # Custom validation logic goes here
        pass
"""

import logging
import re
from datetime import date, datetime
from typing import Any

from django import forms
from django.contrib.auth.models import Group, User
from django.db.models import Q
from django.forms import DateInput, TextInput
from django.template.loader import render_to_string
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as trans

from base.methods import eval_validate, reload_queryset
from employee.models import (
    Actiontype,
    BonusPoint,
    DisciplinaryAction,
    Employee,
    EmployeeBankDetails,
    EmployeeGeneralSetting,
    EmployeeNote,
    EmployeeTag,
    EmployeeWorkInformation,
    NoteFiles,
    Policy,
    PolicyMultipleFile,
)
from horilla import horilla_middlewares
from horilla_audit.models import AccountBlockUnblock

logger = logging.getLogger(__name__)


class ModelForm(forms.ModelForm):
    """
    Override of Django ModelForm to add initial styling and defaults.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        reload_queryset(self.fields)

        request = getattr(horilla_middlewares._thread_locals, "request", None)

        today = date.today()
        now = datetime.now()

        default_input_class = "oh-input w-100"
        select_class = "oh-select oh-select-2"
        checkbox_class = "oh-switch__checkbox"

        for field_name, field in self.fields.items():
            widget = field.widget
            label = _(field.label) if field.label else ""

            # Date field
            if isinstance(widget, forms.DateInput):
                field.initial = today
                widget.input_type = "date"
                widget.format = "%Y-%m-%d"
                field.input_formats = ["%Y-%m-%d"]

                existing_class = widget.attrs.get("class", default_input_class)
                widget.attrs.update(
                    {
                        "class": f"{existing_class} form-control",
                        "placeholder": label,
                    }
                )

            # Time field
            elif isinstance(widget, forms.TimeInput):
                field.initial = now.strftime("%H:%M")
                widget.input_type = "time"
                widget.format = "%H:%M"
                field.input_formats = ["%H:%M"]

                existing_class = widget.attrs.get("class", default_input_class)
                widget.attrs.update(
                    {
                        "class": f"{existing_class} form-control",
                        "placeholder": label,
                    }
                )

            # Number, Email, Text, File, URL fields
            elif isinstance(
                widget,
                (
                    forms.NumberInput,
                    forms.EmailInput,
                    forms.TextInput,
                    forms.FileInput,
                    forms.URLInput,
                ),
            ):
                existing_class = widget.attrs.get("class", default_input_class)
                widget.attrs.update(
                    {
                        "class": f"{existing_class} form-control",
                        "placeholder": _(field.label.title()) if field.label else "",
                    }
                )

            # Select fields
            elif isinstance(widget, forms.Select):
                if not isinstance(field, forms.ModelMultipleChoiceField):
                    field.empty_label = _("---Choose {label}---").format(label=label)
                existing_class = widget.attrs.get("class", select_class)
                widget.attrs.update({"class": existing_class})

            # Textarea
            elif isinstance(widget, forms.Textarea):
                existing_class = widget.attrs.get("class", default_input_class)
                widget.attrs.update(
                    {
                        "class": f"{existing_class} form-control",
                        "placeholder": label,
                        "rows": 2,
                        "cols": 40,
                    }
                )

            # Checkbox types
            elif isinstance(
                widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)
            ):
                existing_class = widget.attrs.get("class", checkbox_class)
                widget.attrs.update({"class": existing_class})

        # Set employee_id and company_id once
        if request:
            employee = getattr(request.user, "employee_get", None)
            if employee:
                if "employee_id" in self.fields and self._meta.model.__name__ not in [
                    "DisciplinaryAction"
                ]:
                    self.fields["employee_id"].initial = employee

                if "company_id" in self.fields:
                    company_field = self.fields["company_id"]
                    company = getattr(employee, "get_company", None)
                    if company:
                        queryset = company_field.queryset
                        company_field.initial = (
                            company if company in queryset else queryset.first()
                        )


class UserForm(ModelForm):
    """
    Form for User model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        fields = ("groups",)
        model = User


class UserPermissionForm(ModelForm):
    """
    Form for User model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        fields = ("groups", "user_permissions")
        model = User


class EmployeeForm(ModelForm):
    """
    Form for Employee model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        model = Employee
        fields = "__all__"
        exclude = (
            "employee_user_id",
            "additional_info",
            "is_from_onboarding",
            "is_directly_converted",
            "is_active",
            # Think4U: 隱藏不需要的個人資料欄位
            "employee_last_name",  # 姓名併入 first_name 單一欄位
            "badge_id",  # 識別證號碼
            "country",
            "state",
            "city",
            "zip",
            "qualification",
            "experience",
            "marital_status",
            "children",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["phone"].widget.attrs["autocomplete"] = "phone"
        self.fields["address"].widget.attrs["autocomplete"] = "address"
        # Think4U: 姓名欄位改 label
        if "employee_first_name" in self.fields:
            self.fields["employee_first_name"].label = _("姓名")
        # Think4U: 電話改為非必填
        if "phone" in self.fields:
            self.fields["phone"].required = False
        if instance := kwargs.get("instance"):
            # ----
            # django forms not showing value inside the date, time html element.
            # so here overriding default forms instance method to set initial value
            # ----
            initial = {}
            if instance.dob is not None:
                initial["dob"] = instance.dob.strftime("%H:%M")
            kwargs["initial"] = initial
        else:
            # Think4U: badge_id 已被排除，但 model 必填 — 自動填入避免 NOT NULL 錯
            pass

    def as_p(self, *args, **kwargs):
        context = {"form": self}
        return render_to_string("employee/create_form/personal_info_as_p.html", context)

    def clean(self):
        super().clean()
        email = self.cleaned_data["email"]
        query = Employee.objects.entire().filter(email=email)
        if self.instance and self.instance.id:
            query = query.exclude(id=self.instance.id)

        existing_employee = query.first()

        if existing_employee:
            company_id = None
            if (
                hasattr(existing_employee, "employee_work_info")
                and existing_employee.employee_work_info
            ):
                company_id = existing_employee.employee_work_info.company_id

            if company_id:
                error_message = _(
                    "An Employee with this Email already exists in company {}".format(
                        company_id
                    )
                )
            else:
                error_message = _("An Employee with this Email already exists")

            raise forms.ValidationError({"email": error_message})

    def get_next_badge_id(self):
        """
        This method is used to generate badge id
        """
        from base.context_processors import get_initial_prefix
        from employee.methods.methods import get_ordered_badge_ids

        prefix = get_initial_prefix(None)["get_initial_prefix"]
        data = get_ordered_badge_ids()
        result = []
        try:
            for sublist in data:
                for item in sublist:
                    if isinstance(item, str) and item.lower().startswith(
                        prefix.lower()
                    ):
                        # Find the index of the item in the sublist
                        index = sublist.index(item)
                        # Check if there is a next item in the sublist
                        if index + 1 < len(sublist):
                            result = sublist[index + 1]
                            result = re.findall(r"[a-zA-Z]+|\d+|[^a-zA-Z\d\s]", result)

            if result:
                prefix = []
                incremented = False
                for item in reversed(result):
                    total_letters = len(item)
                    total_zero_leads = 0
                    for letter in item:
                        if letter == "0":
                            total_zero_leads = total_zero_leads + 1
                            continue
                        break

                    if total_zero_leads:
                        item = item[total_zero_leads:]
                    if isinstance(item, list):
                        item = item[-1]
                    if not incremented and isinstance(eval_validate(str(item)), int):
                        item = int(item) + 1
                        incremented = True
                    if isinstance(item, int):
                        item = "{:0{}d}".format(item, total_letters)
                    prefix.insert(0, str(item))
                prefix = "".join(prefix)
        except Exception as e:
            logger.exception(e)
            prefix = get_initial_prefix(None)["get_initial_prefix"]
        return prefix

    def clean_badge_id(self):
        """
        This method is used to clean the badge id
        """
        badge_id = self.cleaned_data["badge_id"]
        if badge_id:
            all_employees = Employee.objects.entire()
            queryset = all_employees.filter(badge_id=badge_id).exclude(
                pk=self.instance.pk if self.instance else None
            )
            if queryset.exists():
                raise forms.ValidationError(trans("Badge ID must be unique."))
            if not re.search(r"\d", badge_id):
                raise forms.ValidationError(
                    trans("Badge ID must contain at least one digit.")
                )
        return badge_id


def _salary_field(label):
    return forms.IntegerField(
        required=False,
        min_value=0,
        label=label,
        widget=forms.NumberInput(
            attrs={"class": "oh-input w-100", "step": "500", "min": "0"}
        ),
    )


class _SalaryComponentsMixin:
    """Think4U: 薪資組成（本薪 + 津貼 + 加給）+ 健保眷屬，存到 think4u.EmployeeSalary。
    供 EmployeeWorkInformationForm / EmployeeWorkInformationUpdateForm 共用。

    注意：純 mixin 的 class-level Field 不會被 ModelForm metaclass 收集，
    因此改在 __init__ 時以 _setup_salary_fields() 動態注入欄位。
    （非 model 欄位；在 view 中 work_info 存檔後呼叫 save_salary(employee)）"""

    _T4U_SALARY_DEFS = [
        ("base_salary", _("本薪")),
        ("meal_allowance", _("伙食津貼")),
        ("transport_allowance", _("交通津貼")),
        ("management_allowance", _("管理加給")),
        ("tech_management_allowance", _("技術管理加給")),
        ("salary_addition", _("薪資加給")),
    ]
    _T4U_SALARY_FIELDS = [k for k, _l in _T4U_SALARY_DEFS]

    def _setup_salary_fields(self):
        """動態加入薪資組成欄位 + 帶入該員工 EmployeeSalary 初始值
        （健保眷屬改用 HealthInsuranceDependent 明細維護，不在此表單）"""
        for key, label in self._T4U_SALARY_DEFS:
            self.fields[key] = _salary_field(label)
        emp = getattr(self.instance, "employee_id", None) if self.instance else None
        if not emp:
            self.fields["base_salary"].initial = 50000
            return
        from think4u.models import EmployeeSalary

        sal = EmployeeSalary.objects.filter(employee=emp).first()
        if sal:
            for f in self._T4U_SALARY_FIELDS:
                self.fields[f].initial = getattr(sal, f, 0)
        else:
            self.fields["base_salary"].initial = 50000

    # 舊名相容
    def _load_salary_initials(self):
        self._setup_salary_fields()

    def save_salary(self, employee):
        """把薪資組成欄位存到 think4u.EmployeeSalary（眷屬數不在此處理）"""
        if not employee:
            return
        from think4u.models import EmployeeSalary

        sal, _ = EmployeeSalary.objects.get_or_create(employee=employee)
        for f in self._T4U_SALARY_FIELDS:
            val = self.cleaned_data.get(f)
            if val is not None:
                setattr(sal, f, max(0, int(val)))
        sal.save()


class EmployeeWorkInformationForm(_SalaryComponentsMixin, ModelForm):
    """
    Form for EmployeeWorkInformation model
    """

    # Think4U: 單選角色（取代多選 groups）
    role = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        required=False,
        label=_("角色"),
        empty_label=_("— 請選擇 —"),
        widget=forms.Select(attrs={"class": "oh-select oh-select-2"}),
    )

    class Meta:
        model = EmployeeWorkInformation
        fields = "__all__"
        # Think4U: 拿掉不需要的欄位
        exclude = (
            "employee_id",
            "additional_info",
            "experience",
            "shift_id",
            "work_type_id",
            "job_role_id",          # 職級
            "reporting_manager_id", # 直屬主管（由部門推導）
            "tags",                 # 員工標籤
            "location",             # 工作地點
            "company_id",           # 公司（鎖定一家）
            "salary_hour",          # 時薪
            "mobile",
            "email",                # 工作信箱（已有個人 Email 欄位，毋須重複）
        )

    def __init__(self, *args, disable=False, **kwargs):
        super().__init__(*args, **kwargs)
        # 帶入既有角色（只取第一個 group）
        if self.instance and self.instance.pk:
            emp = self.instance.employee_id
            if emp and emp.employee_user_id_id:
                first = emp.employee_user_id.groups.first()
                if first:
                    self.fields["role"].initial = first.pk

        # 標準欄位 placeholder
        for field in self.fields:
            try:
                self.fields[field].widget.attrs["placeholder"] = self.fields[field].label
            except Exception:
                pass
            if disable:
                self.fields[field].disabled = True

        # Think4U: 動態 ChoiceField 改造（用 i18n label，原本 Horilla 用英文 label 對應）
        # 不再做 ChoiceField 轉換，保留 ModelChoiceField 以確保 queryset 正確
        for f in ("department_id", "job_position_id", "employee_type_id"):
            if f in self.fields:
                self.fields[f].widget.attrs["class"] = "oh-select oh-select-2"
                self.fields[f].empty_label = _("— 請選擇 —")

        # Think4U: 帶入薪資組成初始值
        self._load_salary_initials()

    def sync_groups(self, employee):
        """Think4U: 把單選 role 寫回對應 User.groups（取代多選 sync）
        若未指定 role 但職位有 default_role，自動帶入"""
        if not employee or not employee.employee_user_id_id:
            return
        role = self.cleaned_data.get("role")
        # fallback：未選 role 但職位有預設角色
        if not role:
            job_pos = self.cleaned_data.get("job_position_id")
            if job_pos and getattr(job_pos, "default_role_id", None):
                role = job_pos.default_role
        user = employee.employee_user_id
        if role:
            user.groups.set([role])
        else:
            user.groups.clear()

    def clean(self):
        cleaned_data = super().clean()
        if "employee_id" in self.errors:
            del self.errors["employee_id"]
        return cleaned_data

    def as_p(self, *args, **kwargs):
        context = {"form": self}
        return render_to_string("employee/create_form/personal_info_as_p.html", context)


class EmployeeWorkInformationUpdateForm(_SalaryComponentsMixin, ModelForm):
    """
    Form for EmployeeWorkInformation model — Think4U 簡化版
    含薪資組成（本薪 / 津貼 / 加給）+ 健保眷屬，存到 think4u.EmployeeSalary
    """

    role = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        required=False,
        label=_("角色"),
        empty_label=_("— 請選擇 —"),
        widget=forms.Select(attrs={"class": "oh-select oh-select-2"}),
    )

    class Meta:
        model = EmployeeWorkInformation
        fields = "__all__"
        exclude = (
            "employee_id",
            "shift_id",
            "work_type_id",
            "job_role_id",
            "reporting_manager_id",
            "tags",
            "location",
            "company_id",
            "salary_hour",
            "mobile",
            "email",                # 工作信箱（已有個人 Email 欄位，毋須重複）
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            emp = self.instance.employee_id
            if emp and emp.employee_user_id_id:
                first = emp.employee_user_id.groups.first()
                if first:
                    self.fields["role"].initial = first.pk
        # Think4U: 帶入薪資組成初始值
        self._load_salary_initials()

    def sync_groups(self, employee):
        """Think4U: 同 EmployeeWorkInformationForm；未選 role 時 fallback 到職位的 default_role"""
        if not employee or not employee.employee_user_id_id:
            return
        role = self.cleaned_data.get("role")
        if not role:
            job_pos = self.cleaned_data.get("job_position_id")
            if job_pos and getattr(job_pos, "default_role_id", None):
                role = job_pos.default_role
        user = employee.employee_user_id
        if role:
            user.groups.set([role])
        else:
            user.groups.clear()

    def as_p(self, *args, **kwargs):
        context = {"form": self}
        return render_to_string("employee/create_form/personal_info_as_p.html", context)


class EmployeeBankDetailsForm(ModelForm):
    """
    Form for EmployeeBankDetails model
    Think4U: 只留 銀行帳號 + 銀行名稱
    """

    class Meta:
        model = EmployeeBankDetails
        fields = ("bank_name", "account_number")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for visible in self.visible_fields():
            visible.field.widget.attrs["class"] = "oh-input w-100"

    def as_p(self, *args, **kwargs):
        context = {"form": self}
        return render_to_string("employee/update_form/bank_info_as_p.html", context)


class EmployeeBankDetailsUpdateForm(ModelForm):
    """
    Form for EmployeeBankDetails model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        model = EmployeeBankDetails
        fields = ("bank_name", "account_number")  # Think4U: 只留 銀行帳號 + 銀行名稱

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for visible in self.visible_fields():
            visible.field.widget.attrs["class"] = "oh-input w-100"
        for field in self.fields:
            self.fields[field].widget.attrs["placeholder"] = self.fields[field].label

    def as_p(self, *args, **kwargs):
        context = {"form": self}
        return render_to_string("employee/update_form/bank_info_as_p.html", context)


excel_columns = [
    ("badge_id", trans("Badge ID")),
    ("employee_first_name", trans("First Name")),
    ("employee_last_name", trans("Last Name")),
    ("email", trans("Email")),
    ("phone", trans("Phone")),
    ("experience", trans("Experience")),
    ("gender", trans("Gender")),
    ("dob", trans("Date of Birth")),
    ("country", trans("Country")),
    ("state", trans("State")),
    ("city", trans("City")),
    ("address", trans("Address")),
    ("zip", trans("Zip Code")),
    ("marital_status", trans("Marital Status")),
    ("children", trans("Children")),
    ("is_active", trans("Is active")),
    ("emergency_contact", trans("Emergency Contact")),
    ("emergency_contact_name", trans("Emergency Contact Name")),
    ("emergency_contact_relation", trans("Emergency Contact Relation")),
    # Think4U: 移除「工作信箱」匯出/欄位選項（已有 Email）
    ("employee_work_info__mobile", trans("Work Phone")),
    ("employee_work_info__department_id", trans("Department")),
    ("employee_work_info__job_position_id", trans("Job Position")),
    ("employee_work_info__job_role_id", trans("Job Role")),
    ("employee_work_info__shift_id", trans("Shift")),
    ("employee_work_info__work_type_id", trans("Work Type")),
    ("employee_work_info__reporting_manager_id", trans("Reporting Manager")),
    ("employee_work_info__employee_type_id", trans("Employee Type")),
    ("employee_work_info__location", trans("Location")),
    ("employee_work_info__date_joining", trans("Date Joining")),
    ("employee_work_info__basic_salary", trans("Basic Salary")),
    ("employee_work_info__salary_hour", trans("Salary Hour")),
    ("employee_work_info__contract_end_date", trans("Contract End Date")),
    ("employee_work_info__company_id", trans("Company")),
    ("employee_bank_details__bank_name", trans("Bank Name")),
    ("employee_bank_details__branch", trans("Branch")),
    ("employee_bank_details__account_number", trans("Account Number")),
    ("employee_bank_details__any_other_code1", trans("Bank Code #1")),
    ("employee_bank_details__any_other_code2", trans("Bank Code #2")),
    ("employee_bank_details__country", trans("Bank Country")),
    ("employee_bank_details__state", trans("Bank State")),
    ("employee_bank_details__city", trans("Bank City")),
]
fields_to_remove = [
    "badge_id",
    "employee_first_name",
    "employee_last_name",
    "is_active",
    "email",
    "phone",
    "employee_bank_details__account_number",
]


class EmployeeExportExcelForm(forms.Form):
    selected_fields = forms.MultipleChoiceField(
        choices=excel_columns,
        widget=forms.CheckboxSelectMultiple,
        initial=[
            "badge_id",
            "employee_first_name",
            "employee_last_name",
            "email",
            "phone",
            "gender",
            "employee_work_info__department_id",
            "employee_work_info__job_position_id",
            "employee_work_info__job_role_id",
            "employee_work_info__shift_id",
            "employee_work_info__work_type_id",
            "employee_work_info__reporting_manager_id",
            "employee_work_info__employee_type_id",
            "employee_work_info__location",
            "employee_work_info__date_joining",
            "employee_work_info__basic_salary",
            "employee_work_info__salary_hour",
            "employee_work_info__contract_end_date",
            "employee_work_info__company_id",
        ],
    )


class BulkUpdateFieldForm(forms.Form):
    update_fields = forms.MultipleChoiceField(
        choices=excel_columns, label=_("Select Fields to Update")
    )
    bulk_employee_ids = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        updated_choices = [
            (value, label)
            for value, label in self.fields["update_fields"].choices
            if value not in fields_to_remove
        ]
        self.fields["update_fields"].choices = updated_choices
        for visible in self.visible_fields():
            visible.field.widget.attrs["class"] = "oh-select oh-select-2 oh-input w-100"


class EmployeeNoteForm(ModelForm):
    """
    Form for EmployeeNote model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        model = EmployeeNote
        fields = ("description",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["note_files"] = MultipleFileField(label="files")
        self.fields["note_files"].required = False

    def save(self, commit: bool = ...) -> Any:
        attachement = []
        multiple_attachment_ids = []
        attachements = None
        if self.files.getlist("note_files"):
            attachements = self.files.getlist("note_files")
            self.instance.attachement = attachements[0]
            multiple_attachment_ids = []

            for attachement in attachements:
                file_instance = NoteFiles()
                file_instance.files = attachement
                file_instance.save()
                multiple_attachment_ids.append(file_instance.pk)
        instance = super().save(commit)
        if commit:
            instance.note_files.add(*multiple_attachment_ids)
        return instance, multiple_attachment_ids


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = [single_file_clean(data, initial)]
        if len(result) == 0:
            result = [[]]
        return result[0]


class PolicyForm(ModelForm):
    """
    PolicyForm
    """

    class Meta:
        model = Policy
        fields = "__all__"
        exclude = ["attachments", "is_active"]
        widgets = {
            "body": forms.Textarea(
                attrs={"data-summernote": "", "style": "display:none;"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["attachment"] = MultipleFileField(
            label=trans("Attachments"), required=False
        )

    def save(self, *args, commit=True, **kwargs):
        attachemnt = []
        multiple_attachment_ids = []
        attachemnts = None
        if self.files.getlist("attachment"):
            attachemnts = self.files.getlist("attachment")
            multiple_attachment_ids = []
            for attachemnt in attachemnts:
                file_instance = PolicyMultipleFile()
                file_instance.attachment = attachemnt
                file_instance.save()
                multiple_attachment_ids.append(file_instance.pk)
        instance = super().save(commit)
        if commit:
            instance.attachments.add(*multiple_attachment_ids)
        return instance, attachemnts


class BonusPointAddForm(ModelForm):
    class Meta:
        model = BonusPoint
        fields = ["points", "reason"]
        widgets = {
            "reason": forms.TextInput(attrs={"required": "required"}),
        }


class BonusPointRedeemForm(ModelForm):
    class Meta:
        model = BonusPoint
        fields = ["points"]

    def clean(self):
        cleaned_data = super().clean()
        available_points = BonusPoint.objects.filter(
            employee_id=self.instance.employee_id
        ).first()
        if not available_points or available_points.points < cleaned_data["points"]:
            raise forms.ValidationError({"points": "Not enough bonus points to redeem"})
        if cleaned_data["points"] <= 0:
            raise forms.ValidationError(
                {"points": "Points must be greater than zero to redeem."}
            )


class DisciplinaryActionForm(ModelForm):
    class Meta:
        model = DisciplinaryAction
        fields = "__all__"
        exclude = ["objects", "is_active"]

    action = forms.ModelChoiceField(
        queryset=Actiontype.objects.all(),
        label=_("Action"),
        widget=forms.Select(
            attrs={
                "class": "oh-select oh-select-2",
                "onchange": "actionTypeChange($(this))",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        action_choices = [("", _("---Choose Action---"))] + list(
            self.fields["action"].queryset.values_list("id", "title")
        )
        self.fields["action"].choices = action_choices
        if self.instance.pk is None:
            self.fields["action"].choices += [("create", _("Create new action type "))]

    def as_p(self):
        """
        Render the form fields as HTML table rows with Bootstrap styling.
        """
        context = {"form": self}
        table_html = render_to_string("common_form.html", context)
        return table_html


class ActiontypeForm(ModelForm):
    class Meta:
        model = Actiontype
        fields = "__all__"
        exclude = ["is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["action_type"].widget.attrs.update(
            {
                "onchange": "actionChange($(this))",
            }
        )


class EmployeeTagForm(ModelForm):
    """
    Employee Tags form
    """

    class Meta:
        """
        Meta class for additional options
        """

        model = EmployeeTag
        fields = "__all__"
        exclude = ["is_active"]
        widgets = {"color": TextInput(attrs={"type": "color", "style": "height:50px"})}


class EmployeeGeneralSettingPrefixForm(forms.ModelForm):

    class Meta:

        model = EmployeeGeneralSetting
        exclude = ["objects"]
        widgets = {
            "badge_id_prefix": forms.TextInput(attrs={"class": "oh-input w-100"}),
            "company_id": forms.Select(attrs={"class": "oh-select oh-select-2 w-100"}),
        }
