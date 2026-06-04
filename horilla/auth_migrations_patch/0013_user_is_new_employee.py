"""
Think4U restore: Horilla 在 base/models.py 用 `User.add_to_class("is_new_employee", ...)`
把 is_new_employee 欄位掛到 Django 內建 auth.User，因此該欄位的 migration 屬於 auth app
（檔名 auth/migrations/0013_user_is_new_employee.py，原本由 makemigrations auth 產生並存在
venv 的 site-packages 內）。重建 image 會清掉 site-packages 內這個檔，導致 migration graph
缺節點（base.0003 等都 depend on 它）→ makemigrations/migrate 全部失敗。

對策：把這個 auth migration 留在版控，entrypoint.sh 啟動時 copy 進 auth 的 migrations 目錄，
確保重建後 graph 仍可解析。DB 內此 migration 早已標記為 applied，restore 後 migrate 為 no-op。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_new_employee",
            field=models.BooleanField(default=False),
        ),
    ]
