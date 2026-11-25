import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


def identity_key(value):
    return value.strip().casefold()


class AccountManager(UserManager):
    def get_by_natural_key(self, username):
        return self.get(username_key=identity_key(username))

    async def aget_by_natural_key(self, username):
        return await self.aget(username_key=identity_key(username))


class Account(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=256, unique=True, verbose_name="Email address")
    username = models.CharField(max_length=45, unique=True, verbose_name="Username")
    username_key = models.TextField(unique=True, editable=False)
    avatar = models.ImageField(
        upload_to="bakot/static/bakot/imagination", blank=True, null=True, verbose_name="Profile picture",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Registration time")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated at")

    objects = AccountManager()

    def save(self, *args, **kwargs):
        self.username = self.username.strip()
        self.username_key = identity_key(self.username)
        self.email = identity_key(self.email)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "username" in update_fields:
            kwargs["update_fields"] = {*update_fields, "username_key"}
        return super().save(*args, **kwargs)


class Session(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True)


class PasswordResetToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True)


class AuthRateLimit(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    window_start = models.DateTimeField(db_index=True)
    count = models.PositiveIntegerField(default=0)
