import logging
from datetime import timedelta
from math import ceil
from secrets import token_urlsafe
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from cleanser.http import APIError, EmailField, StrictSerializer, TextField, body, query

from .authentication import hash_token, revoke_current, set_session_cookie, start_session
from .models import Account, AuthRateLimit, PasswordResetToken, Session, identity_key

logger = logging.getLogger(__name__)


class PasswordInput(StrictSerializer):
    password = TextField(trim_whitespace=False, max_length=settings.PASSWORD_MAX_LENGTH,
                         write_only=True, style={"input_type": "password"})
    passwordConfirmation = TextField(trim_whitespace=False, max_length=settings.PASSWORD_MAX_LENGTH,
                                     write_only=True, style={"input_type": "password"})

    def validate(self, attrs):
        if attrs["password"] != attrs["passwordConfirmation"]:
            raise serializers.ValidationError({"passwordConfirmation": ["Пароли не совпадают."]})
        return attrs


class Registration(PasswordInput):
    username = TextField(min_length=3, max_length=40)
    email = EmailField(max_length=256)

    def validate_username(self, value):
        if len(identity_key(value)) > 120:
            raise serializers.ValidationError("Имя пользователя слишком длинное.")
        return value

    def validate_email(self, value):
        email = identity_key(value)
        if len(email) > 256:
            raise serializers.ValidationError("Адрес слишком длинный после нормализации.")
        return email


class Login(StrictSerializer):
    username = TextField(max_length=45)
    password = TextField(trim_whitespace=False, max_length=settings.PASSWORD_MAX_LENGTH, write_only=True)


class Forgot(StrictSerializer):
    email = EmailField(max_length=256)


class Reset(PasswordInput):
    token = TextField(trim_whitespace=False, max_length=256, write_only=True)


def user_dto(user):
    return {"id": user.id, "username": user.username, "email": user.email,
            "avatarUrl": user.avatar.url if user.avatar else None, "createdAt": user.created_at}


def check_password_policy(password, user):
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise APIError(422, fields={"password": exc.messages}) from None


def limit(request, action):
    maximum, duration = settings.API_AUTH_LIMITS[action]
    key = salted_hmac("dataset-cleanser-auth-throttle",
                      f"{action}:{request.META.get('REMOTE_ADDR', '')}", algorithm="sha256").hexdigest()
    now = timezone.now()
    with transaction.atomic():
        entry, _ = AuthRateLimit.objects.select_for_update().get_or_create(
            key=key, defaults={"window_start": now},
        )
        remaining = (entry.window_start + timedelta(seconds=duration) - now).total_seconds()
        if remaining <= 0:
            entry.window_start = now
            entry.count = 0
        if entry.count >= maximum:
            raise APIError(429, wait=max(1, ceil(remaining)))
        entry.count += 1
        entry.save(update_fields=["window_start", "count"])


class PublicAuthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


class CSRFView(PublicAuthView):
    def get(self, request):
        query(request)
        return Response({"csrfToken": get_token(request._request)})


class RegisterView(PublicAuthView):
    def post(self, request):
        query(request)
        limit(request, "register")
        data = body(request, Registration)
        user = Account(username=data["username"], email=data["email"])
        check_password_policy(data["password"], user)
        user.set_password(data["password"])
        try:
            with transaction.atomic():
                user.save(force_insert=True)
                token = start_session(request, user)
        except IntegrityError:
            if Account.objects.filter(username_key=identity_key(user.username)).exists():
                raise APIError(409, "USERNAME_TAKEN", "Имя пользователя уже занято.") from None
            if Account.objects.filter(email=user.email).exists():
                raise APIError(409, "EMAIL_TAKEN", "Эта почта уже используется.") from None
            raise
        response = Response(user_dto(user), status=201)
        set_session_cookie(response, token)
        return response


class LoginView(PublicAuthView):
    def post(self, request):
        query(request)
        limit(request, "login")
        data = body(request, Login)
        user = authenticate(request._request, **data)
        if user is None:
            raise APIError(401, "INVALID_CREDENTIALS", "Неверное имя пользователя или пароль.")
        with transaction.atomic():
            locked = Account.objects.select_for_update().get(pk=user.pk)
            if locked.password != user.password or not locked.is_active:
                raise APIError(401, "INVALID_CREDENTIALS", "Неверное имя пользователя или пароль.")
            token = start_session(request, locked)
        response = Response(user_dto(locked))
        set_session_cookie(response, token)
        return response


class LogoutView(PublicAuthView):
    def post(self, request):
        query(request)
        body(request)
        revoke_current(request, timezone.now())
        response = Response(status=204)
        set_session_cookie(response)
        return response


class MeView(APIView):
    def get(self, request):
        query(request)
        return Response(user_dto(request.user))


def deliver_reset(request_id, email, token):
    link = f"{settings.FRONTEND_URL}/reset-password?{urlencode({'token': token})}"
    try:
        send_mail("Восстановление пароля DatasetCleanser",
                  f"Чтобы задать новый пароль, откройте ссылку:\n{link}\n",
                  settings.DEFAULT_FROM_EMAIL, [email])
    except Exception as exc:
        logger.warning("Password reset delivery failed request_id=%s exception=%s", request_id, type(exc).__name__)


class ForgotView(PublicAuthView):
    def post(self, request):
        query(request)
        limit(request, "forgot")
        data = body(request, Forgot)
        user = Account.objects.filter(email=identity_key(data["email"]), is_active=True).first()
        if user is not None:
            token = token_urlsafe(32)
            with transaction.atomic():
                PasswordResetToken.objects.create(
                    user=user, token_hash=hash_token(token),
                    expires_at=timezone.now() + timedelta(seconds=settings.API_RESET_TOKEN_SECONDS),
                )
                transaction.on_commit(lambda: deliver_reset(request.request_id, user.email, token))
        return Response({"message": "Если адрес зарегистрирован, на него отправлена ссылка."}, status=202)


class ResetView(PublicAuthView):
    def post(self, request):
        query(request)
        limit(request, "reset")
        data = body(request, Reset)
        hashed = hash_token(data["token"])
        token = PasswordResetToken.objects.filter(token_hash=hashed).first()
        if token is None:
            raise APIError(422, "RESET_TOKEN_INVALID", "Ссылка недействительна или просрочена.")
        with transaction.atomic():
            user = Account.objects.select_for_update().get(pk=token.user_id)
            now = timezone.now()
            token = PasswordResetToken.objects.select_for_update().filter(
                pk=token.pk, used_at__isnull=True, expires_at__gt=now,
            ).first()
            if token is None or not user.is_active:
                raise APIError(422, "RESET_TOKEN_INVALID", "Ссылка недействительна или просрочена.")
            check_password_policy(data["password"], user)
            user.set_password(data["password"])
            user.save(update_fields=["password", "updated_at"])
            PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
            Session.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=now)
        return Response(status=204)
