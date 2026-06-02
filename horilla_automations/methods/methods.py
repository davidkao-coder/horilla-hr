"""
horilla_automations/methods/methods.py

"""

import operator

from django.core.exceptions import FieldDoesNotExist
from django.db import models as django_models
from django.http import QueryDict
from django.utils.translation import gettext as _

from base.templatetags.horillafilters import app_installed
from employee.models import Employee
from horilla.models import HorillaModel

recruitment_installed = False
if app_installed("recruitment"):
    from recruitment.models import Candidate

    recruitment_installed = True


def get_related_models(model: HorillaModel) -> list:
    related_models = []
    for field in model._meta.get_fields():
        if field.one_to_many or field.one_to_one or field.many_to_many:
            related_model = field.related_model
            related_models.append(related_model)
    return related_models


from horilla_automations.methods.recursive_relation import (
    get_forward_relation_paths_separated,
)


def generate_choices(model_path):
    """
    Generate mail to choice
    """
    module_name, class_name = model_path.rsplit(".", 1)

    module = __import__(module_name, fromlist=[class_name])
    model_class: Employee = getattr(module, class_name)

    # Get relations to Employee
    employee_fk_paths, employee_m2m_paths = get_forward_relation_paths_separated(
        model_class, Employee
    )

    # Get relations to Candidate（招募模組已停用時略過，避免 NameError）
    candidate_fk_paths, candidate_m2m_paths = [], []
    if recruitment_installed:
        candidate_fk_paths, candidate_m2m_paths = get_forward_relation_paths_separated(
            model_class, Candidate
        )

    all_fields = (
        employee_fk_paths
        + employee_m2m_paths
        + candidate_fk_paths
        + candidate_m2m_paths
    )

    all_mail_to_field = []
    mail_details_choice = []
    for field_tuple in all_fields:
        if not getattr(field_tuple[1], "exclude_from_automation", False):
            _name = field_tuple[1].verbose_name.capitalize().replace(" id", "")
            all_mail_to_field.append(
                (
                    f"{field_tuple[0]}__get_email",
                    _("(%(model)s) %(name)s's mail")
                    % {"model": field_tuple[1].model.__name__, "name": _name},
                )
            )
            if not field_tuple[1].many_to_many:
                mail_details_choice += [
                    (
                        f"{field_tuple[0]}__pk",
                        _("%(name)s (Template context)") % {"name": _name},
                    ),
                ]
                # Adding reporting manager if the related model is Employee
                if field_tuple[1].related_model == Employee:
                    # reporting manager mail to
                    all_mail_to_field.append(
                        (
                            f"{field_tuple[0]}__employee_work_info__reporting_manager_id__get_email",
                            _("%(name)s / Reporting Manager's mail")
                            % {"name": _name},
                        )
                    )
                    # reporting manager template context
                    mail_details_choice.append(
                        (
                            f"{field_tuple[0]}__employee_work_info__reporting_manager_id__pk",
                            _("%(name)s / Reporting Manager (Template context)")
                            % {"name": _name},
                        )
                    )

    if model_class == Employee:
        # reporting manager mail to
        all_mail_to_field.append(
            (
                f"employee_work_info__reporting_manager_id__get_email",
                _("Reporting Manager's mail"),
            )
        )
        mail_details_choice.append(("pk", _("Employee (Template context)")))
    if recruitment_installed and model_class == Candidate:
        mail_details_choice.append(("pk", _("Candidate (Template context)")))

    if model_path == "employee.models.Employee":
        all_mail_to_field.append(("get_email", _("Employee's own mail")))
    elif model_path == "recruitment.models.Candidate":
        all_mail_to_field.append(("get_email", _("Candidate's own mail")))

    to_fields = []
    # mail_details_choice = []

    # for field in list(model_class._meta.fields) + list(model_class._meta.many_to_many):
    #     if not getattr(field, "exclude_from_automation", False):
    #         related_model = field.related_model
    #         models = [Employee]
    #         if recruitment_installed:
    #             models.append(Candidate)
    #         if related_model in models:
    #             email_field = (
    #                 f"{field.name}__get_email",
    #                 f"{field.verbose_name.capitalize().replace(' id','')} mail field ",
    #             )
    #             mail_detail = None
    #             if not isinstance(field, django_models.ManyToManyField):
    #                 mail_detail = (
    #                     f"{field.name}__pk",
    #                     field.verbose_name.capitalize().replace(" id", "")
    #                     + "(Template context)",
    #                 )
    #             if field.related_model == Employee:
    #                 to_fields.append(
    #                     (
    #                         f"{field.name}__employee_work_info__reporting_manager_id__get_email",
    #                         f"{field.verbose_name.capitalize().replace(' id','')}'s reporting manager",
    #                     )
    #                 )
    #                 if not isinstance(field, django_models.ManyToManyField):
    #                     mail_details_choice.append(
    #                         (
    #                             f"{field.name}__employee_work_info__reporting_manager_id__pk",
    #                             f"{field.verbose_name.capitalize().replace(' id','')}'s reporting manager (Template context)",
    #                         )
    #                     )

    # to_fields.append(email_field)
    # if mail_detail:
    #     mail_details_choice.append(mail_detail)
    text_area_fields = get_textfield_paths(model_class)
    mail_details_choice = mail_details_choice + text_area_fields
    # models = [Employee]
    # if recruitment_installed:
    #     models.append(Candidate)
    # if model_class in models:
    #     to_fields.append(
    #         (
    #             "get_email",
    #             f"{model_class.__name__}'s mail ({model_class.__name__})",
    #         )
    #     )
    #     mail_to_related_fields = getattr(model_class, "mail_to_related_fields", [])
    #     to_fields = to_fields + mail_to_related_fields
    #     mail_details_choice.append(("pk", model_class.__name__))

    to_fields = list(set(to_fields))

    return all_mail_to_field, mail_details_choice, model_class


def get_model_class(model_path):
    """
    method to return the model class from string 'app.models.Model'
    """
    module_name, class_name = model_path.rsplit(".", 1)
    module = __import__(module_name, fromlist=[class_name])
    model_class: Employee = getattr(module, class_name)
    return model_class


operator_map = {
    "==": operator.eq,
    "!=": operator.ne,
    "and": lambda x, y: x and y,
    "or": lambda x, y: x or y,
}


def querydict(query_string):
    query_dict = QueryDict(query_string)
    return query_dict


def split_query_string(query_string):
    """
    Split the query string based on the "&logic=" substring
    """
    query_parts = query_string.split("&logic=")
    result = []

    for i, part in enumerate(query_parts):
        if i != 0:
            result.append(querydict("&logic=" + part))
        else:
            result.append(querydict(part))
    return result


def evaluate_condition(value1, operator_str, value2):
    op_func = operator_map.get(operator_str)
    if op_func is None:
        raise ValueError(f"Invalid operator: {operator_str}")
    return op_func(value1, value2)


def get_related_field_model(model: Employee, field_path):
    parts = field_path.split("__")
    for part in parts:
        # Handle the special case for 'pk'
        if part == "pk":
            field = model._meta.pk
        else:
            try:
                field = model._meta.get_field(part)
            except FieldDoesNotExist:
                # Handle the case where the field does not exist
                raise

        if field.is_relation:
            model = field.related_model
        else:
            # If the part is a non-relation field, break the loop
            break
    return model


def get_textfield_paths(model):
    """
    get all text field mapping / or relation
    """
    paths = []

    def traverse(model, prefix=""):
        for field in model._meta.get_fields():
            if isinstance(field, django_models.TextField):
                _label = (
                    (prefix.capitalize() + field.name.capitalize())
                    .replace("__", " > ")
                    .replace("_id", "")
                    .replace("_", " ")
                )
                paths.append(
                    (
                        prefix + field.name,
                        _("%(label)s (As a mail template)") % {"label": _label},
                    )
                )
            elif isinstance(field, django_models.ForeignKey):
                traverse(field.related_model, prefix + field.name + "__")

    traverse(model)
    return paths
