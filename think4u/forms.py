"""WP-04 加班指派表單"""
from django import forms
from django.utils.translation import gettext_lazy as _

from think4u.models import OvertimeAssignment


class OvertimeAssignmentForm(forms.ModelForm):
    class Meta:
        model = OvertimeAssignment
        fields = ["employee", "overtime_date", "start_time", "end_time", "reason"]
        widgets = {
            "overtime_date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "reason": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 套用 Horilla 樣式：select → oh-select，其餘 input/textarea → oh-input
        for name, field in self.fields.items():
            w = field.widget
            base = "oh-select w-100" if isinstance(w, forms.Select) else "oh-input w-100"
            existing = w.attrs.get("class", "")
            w.attrs["class"] = (existing + " " + base).strip()

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_time")
        end = cleaned.get("end_time")
        if start and end and end == start:
            raise forms.ValidationError(_("起訖時間不可相同"))
        return cleaned
