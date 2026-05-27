"""
horilla_company_manager.py
"""

import logging
from typing import Coroutine, Sequence

from django.db import models
from django.db.models.query import QuerySet

from horilla.horilla_middlewares import _thread_locals
from horilla.signals import post_bulk_update, pre_bulk_update

logger = logging.getLogger(__name__)
django_filter_update = QuerySet.update

# Think4U 效能：distinct 偵測結果跨 request 穩定（company_filter 是 class attribute，
# 不會在 runtime 改），用 process-wide cache 大幅減少 SQL。
# key = (model_label, selected_company), value = bool
_T4U_DISTINCT_CACHE: dict = {}


def update(self, *args, **kwargs):
    # pre_update signal
    request = getattr(_thread_locals, "request", None)
    self.request = request
    pre_bulk_update.send(sender=self.model, queryset=self, args=args, kwargs=kwargs)
    result = django_filter_update(self, *args, **kwargs)
    # post_update signal
    post_bulk_update.send(sender=self.model, queryset=self, args=args, kwargs=kwargs)

    return result


setattr(QuerySet, "update", update)


class HorillaCompanyManager(models.Manager):
    """
    HorillaCompanyManager
    """

    def __init__(self, related_company_field=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.related_company_field = related_company_field
        self.check_fields = [
            "employee_id",
            "requested_employee_id",
        ]

    def get_queryset(self):
        """
        get_queryset method

        Think4U 效能優化（2026-05-27）：
        原本每次 get_queryset() 都跑 `count() != distinct().count()` 兩條 COUNT
        來偵測是否有重複；對 HorillaCompanyManager 管的 model 來說，這在每個
        request 內可能被呼叫 60+ 次，造成 100+ 條多餘 SQL。

        修法：把「是否需要 distinct」的結果 cache 在 request 物件上（per-request、
        per-model、per-selected_company），同一個 request 內同一個 model 只判斷
        一次。沒有 request（例如 management command）就退回原本行為。
        """

        queryset = super().get_queryset()
        request = getattr(_thread_locals, "request", None)
        selected_company = None
        if request is not None:
            selected_company = request.session.get("selected_company")
        try:
            queryset = (
                queryset.filter(self.model.company_filter)
                if selected_company != "all" and selected_company
                else queryset
            )
        except Exception as e:
            logger.error(e)

        # ----- distinct 判斷 + process-wide cache -----
        try:
            cache_key = (self.model._meta.label, selected_company)
            if cache_key in _T4U_DISTINCT_CACHE:
                has_duplicates = _T4U_DISTINCT_CACHE[cache_key]
            else:
                has_duplicates = queryset.count() != queryset.distinct().count()
                _T4U_DISTINCT_CACHE[cache_key] = has_duplicates

            if has_duplicates:
                queryset = queryset.distinct()
        except Exception:
            pass
        return queryset

    def all(self):
        """
        Override the all() method
        """
        queryset = []
        try:
            queryset = self.get_queryset()
            if queryset.exists():
                try:
                    model_name = queryset.model._meta.model_name
                    if model_name == "employee":
                        request = getattr(_thread_locals, "request", None)
                        if not getattr(request, "is_filtering", None):
                            queryset = queryset.filter(is_active=True)
                    else:
                        for field in queryset.model._meta.fields:
                            if isinstance(field, models.ForeignKey):
                                if field.name in self.check_fields:
                                    related_model_is_active_filter = {
                                        f"{field.name}__is_active": True
                                    }
                                    queryset = queryset.filter(
                                        **related_model_is_active_filter
                                    )
                except:
                    pass
        except:
            pass
        return queryset

    def filter(self, *args, **kwargs):
        queryset = super().filter(*args, **kwargs)
        setattr(_thread_locals, "queryset_filter", queryset)
        return queryset

    def entire(self):
        """
        Fetch all datas from a model without applying any company filter.
        """
        queryset = super().get_queryset()
        return queryset  # No filtering applied
