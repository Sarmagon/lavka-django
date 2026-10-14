import re

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from core.models import SoftDeleteQuerySet
from core.validators import validate_image


class AccountQuerySet(SoftDeleteQuerySet):
    def delete(self):
        count = self.filter(deleted_at__isnull=True).update(
            deleted_at=timezone.now(), is_active=False
        )
        return count, {self.model._meta.label: count}


class AccountManager(UserManager.from_queryset(AccountQuerySet)):
    pass


class User(AbstractUser):
    full_name = models.CharField("Ф. И. О.", max_length=255)
    email = models.EmailField("Email", unique=True)
    phone = models.CharField("Телефон", max_length=16, unique=True, null=True, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, validators=[validate_image])
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)
    objects = AccountManager()
    REQUIRED_FIELDS = ["email", "full_name"]

    class Meta:
        constraints = [models.UniqueConstraint(Lower("email"), name="user_email_ci_unique")]

    def clean(self):
        super().clean()
        self.email = self.email.strip().lower()
        self.full_name = self.full_name.strip()
        if not self.full_name:
            raise ValidationError({"full_name": "Укажите Ф. И. О."})
        if self.phone:
            self.phone = re.sub(r"[\s()\-]", "", self.phone)
            if not re.fullmatch(r"\+[1-9][0-9]{6,14}", self.phone):
                raise ValidationError({"phone": "Используйте международный формат: +79991234567."})
        else:
            self.phone = None

    def save(self, *args, **kwargs):
        self.clean()
        if self.deleted_at:
            self.is_active = False
        return super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        return type(self).objects.using(using or self._state.db).filter(pk=self.pk).delete()
