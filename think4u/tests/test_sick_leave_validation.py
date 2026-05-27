"""WP-06: 驗證 _SickLeaveAttachmentMixin 的條件式必填邏輯"""
from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django import forms

from leave.forms import _SickLeaveAttachmentMixin


class _FakeLeaveType:
    def __init__(self, name):
        self.name = name


class _ProbeForm(_SickLeaveAttachmentMixin, forms.Form):
    """純驗證 mixin 邏輯，不沾 Horilla model"""

    leave_type_id = forms.Field(required=False)
    attachment = forms.FileField(required=False)


class TestSickLeaveAttachmentMixin(TestCase):
    def test_sick_without_attachment_fails(self):
        f = _ProbeForm(
            data={"leave_type_id": _FakeLeaveType("病假")},
            files={},
        )
        self.assertFalse(f.is_valid())
        self.assertIn("attachment", f.errors)

    def test_personal_without_attachment_ok(self):
        f = _ProbeForm(
            data={"leave_type_id": _FakeLeaveType("事假")},
            files={},
        )
        # 事假無附件不應出 attachment 錯誤
        self.assertTrue(f.is_valid() or "attachment" not in f.errors)

    def test_sick_with_valid_pdf_ok(self):
        att = SimpleUploadedFile("doc.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        f = _ProbeForm(
            data={"leave_type_id": _FakeLeaveType("病假")},
            files={"attachment": att},
        )
        self.assertTrue(f.is_valid(), f.errors)

    def test_sick_with_invalid_ext_fails(self):
        att = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
        f = _ProbeForm(
            data={"leave_type_id": _FakeLeaveType("病假")},
            files={"attachment": att},
        )
        self.assertFalse(f.is_valid())
        self.assertIn("attachment", f.errors)

    def test_oversized_attachment_fails(self):
        big = SimpleUploadedFile(
            "huge.pdf", b"x" * (11 * 1024 * 1024), content_type="application/pdf"
        )
        f = _ProbeForm(
            data={"leave_type_id": _FakeLeaveType("病假")},
            files={"attachment": big},
        )
        self.assertFalse(f.is_valid())
        self.assertIn("attachment", f.errors)
