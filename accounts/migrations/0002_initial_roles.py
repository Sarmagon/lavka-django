import os

from django.contrib.auth.hashers import make_password
from django.db import migrations


def forward(apps, schema_editor):
    alias = schema_editor.connection.alias
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("accounts", "User")
    for name in ("Покупатели", "Продавцы", "Менеджеры"):
        Group.objects.using(alias).create(name=name)
    # An unusable password keeps unattended installation safe. Set a password
    # with changepassword after migration, or supply it through the environment.
    User.objects.using(alias).create(
        username="admin", email="admin@example.invalid", full_name="Администратор",
        is_staff=True, is_superuser=True,
        password=make_password(os.environ.get("DJANGO_INITIAL_ADMIN_PASSWORD") or None),
    )


def backward(apps, schema_editor):
    alias = schema_editor.connection.alias
    apps.get_model("accounts", "User").objects.using(alias).filter(username="admin", email="admin@example.invalid").delete()
    apps.get_model("auth", "Group").objects.using(alias).filter(name__in=["Покупатели", "Продавцы", "Менеджеры"]).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial"), ("auth", "0012_alter_user_first_name_max_length")]
    operations = [migrations.RunPython(forward, backward)]
