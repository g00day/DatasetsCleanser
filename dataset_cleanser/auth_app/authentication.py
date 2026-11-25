import hashlib
from datetime import timedelta
from secrets import token_urlsafe

from django.conf import settings
from django.middleware.csrf import rotate_token
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication

from .models import Session


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def live_sessions(now):
    return Session.objects.filter(
        revoked_at__isnull=True, expires_at__gt=now, user__is_active=True,
        last_seen_at__gt=now - timedelta(seconds=settings.API_SESSION_IDLE_SECONDS),
    )


class CookieSessionAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = request.COOKIES.get(settings.API_SESSION_COOKIE)
        if not token or len(token) != 43:
            return None
        now = timezone.now()
        live = live_sessions(now)
        session = live.select_related("user").filter(token_hash=hash_token(token)).first()
        if session is None:
            return None
        if session.last_seen_at < now:
            updated = live.filter(pk=session.pk, last_seen_at__lt=now).update(last_seen_at=now)
            if not updated and not live.filter(pk=session.pk).exists():
                return None
        return session.user, session

    def authenticate_header(self, request):
        return "Session"


def revoke_current(request, now):
    token = request.COOKIES.get(settings.API_SESSION_COOKIE)
    if token and len(token) == 43:
        Session.objects.filter(token_hash=hash_token(token), revoked_at__isnull=True).update(revoked_at=now)


def start_session(request, user):
    now = timezone.now()
    revoke_current(request, now)
    token = token_urlsafe(32)
    Session.objects.create(user=user, token_hash=hash_token(token), last_seen_at=now,
                           expires_at=now + timedelta(seconds=settings.API_SESSION_MAX_SECONDS))
    rotate_token(request._request)
    return token


def set_session_cookie(response, token=""):
    response.set_cookie(settings.API_SESSION_COOKIE, token, max_age=settings.API_SESSION_MAX_SECONDS if token else 0,
                        secure=settings.SESSION_COOKIE_SECURE, httponly=True, samesite="Lax", path="/")
