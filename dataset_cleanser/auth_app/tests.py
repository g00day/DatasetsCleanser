from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from auth_app.authentication import hash_token
from auth_app.models import Account, PasswordResetToken, Session

API = "/api/v1"
PASSWORD = "Correct-Jubilee-19!"
OTHER_PASSWORD = "Second-Glacier-41!"


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class AuthenticationEndpoints(APITestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)

    def csrf(self, client=None):
        client = client if client is not None else self.client
        response = client.get(f"{API}/auth/csrf")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["csrfToken"]

    def mutate(self, method, path, data=None, *, client=None, idem=None, csrf=True, **headers):
        client = client if client is not None else self.client
        if csrf:
            headers.setdefault("HTTP_X_CSRFTOKEN", self.csrf(client))
        if idem is not None:
            headers["HTTP_IDEMPOTENCY_KEY"] = str(idem)
        return getattr(client, method)(f"{API}{path}", data=data, format="json", **headers)

    def register(self, username="DataOwner", email="owner@example.com", client=None):
        response = self.mutate("post", "/auth/register", {
            "username": username, "email": email, "password": PASSWORD, "passwordConfirmation": PASSWORD,
        }, client=client)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def get(self, path, *, client=None, **params):
        client = client if client is not None else self.client
        response = client.get(f"{API}{path}", data=params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        error = response.json()["error"]
        self.assertEqual(error["code"], code, error)
        self.assertTrue(error["message"])
        self.assertEqual(error["requestId"], response.headers["X-Request-ID"])
        return error

    def test_public_capabilities_publish_actual_limits_and_actions(self):
        data = self.get("/capabilities")
        self.assertEqual(data["files"]["maxFileBytes"], settings.MAX_FILE_BYTES)
        self.assertEqual(data["jobs"]["maxActivePerUser"], settings.MAX_ACTIVE_JOBS_PER_OWNER)
        self.assertEqual(data["passwordPolicy"]["minLength"], settings.PASSWORD_MIN_LENGTH)
        self.assertGreaterEqual(data["idempotency"]["ttlSeconds"], 24 * 3600)
        self.assertEqual(data["pagination"], {"defaultPageSize": 10, "maxPageSize": 100,
                                            "suggestedPageSizes": [10, 25, 50]})
        self.assertEqual({item["code"] for item in data["qualityRules"]}, {"required", "data_type", "email_format"})
        self.assertEqual({item["code"] for item in data["cleaningActions"]},
                         {"trim", "lowercase", "pseudonymize", "drop_rows_with_missing", "drop_duplicate_rows"})
        self.assertNotIn("Set-Cookie", self.client.get(f"{API}/capabilities").headers)

    def test_csrf_endpoint_and_forged_origin_on_anonymous_post(self):
        data = self.get("/auth/csrf")
        self.assertIn(settings.CSRF_COOKIE_NAME, self.client.cookies)
        self.assertNotEqual(self.client.cookies[settings.CSRF_COOKIE_NAME].value, data["csrfToken"])
        credentials = {"username": "Example", "password": PASSWORD}
        self.error(self.mutate("post", "/auth/login", credentials, csrf=False), 403, "CSRF_FAILED")
        self.error(self.mutate("post", "/auth/login", credentials, HTTP_ORIGIN="https://example.invalid"),
                   403, "CSRF_FAILED")
        self.error(self.mutate("post", "/auth/login", credentials, HTTP_ORIGIN="http://testserver"),
                   401, "INVALID_CREDENTIALS")

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_register_normalizes_name_email_and_stores_hashed_session(self):
        response = self.mutate("post", "/auth/register", {
            "username": "  DátáOwner ", "email": "OWNER@Example.COM",
            "password": PASSWORD, "passwordConfirmation": PASSWORD,
        })
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(set(data), {"id", "username", "email", "avatarUrl", "createdAt"})
        self.assertEqual(data["username"], "DátáOwner")
        self.assertEqual(data["email"], "owner@example.com")
        self.assertTrue(data["createdAt"].endswith("Z"))
        cookie = response.cookies[settings.API_SESSION_COOKIE]
        self.assertEqual(cookie["path"], "/")
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(Session.objects.get().token_hash, hash_token(cookie.value))
        self.assertTrue(Account.objects.get().check_password(PASSWORD))
        self.assertEqual(self.get("/auth/me"), data)

    def test_register_validates_contract_and_case_insensitive_conflicts(self):
        self.register("Straße", "current@example.com")
        data = {"username": "STRASSE", "email": "second@example.com",
                "password": PASSWORD, "passwordConfirmation": PASSWORD}
        self.error(self.mutate("post", "/auth/register", data), 409, "USERNAME_TAKEN")
        data.update(username="Someone", email="CURRENT@EXAMPLE.COM")
        self.error(self.mutate("post", "/auth/register", data), 409, "EMAIL_TAKEN")
        for changes, field in (({"username": "   "}, "username"), ({"role": "admin"}, "role"),
                               ({"passwordConfirmation": "different"}, "passwordConfirmation"),
                               ({"email": "invalid"}, "email"),
                               ({"password": "12345", "passwordConfirmation": "12345"}, "password")):
            with self.subTest(field=field):
                response = self.mutate("post", "/auth/register", {**data, "email": "new@example.com", **changes})
                self.assertIn(field, self.error(response, 422, "VALIDATION_ERROR")["fields"])

    def test_me_login_rotation_logout_revocation_and_repeat_logout(self):
        self.error(self.client.get(f"{API}/auth/me"), 401, "UNAUTHENTICATED")
        data = self.register()
        old_cookie = self.client.cookies[settings.API_SESSION_COOKIE].value
        old_csrf = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        self.error(self.mutate("post", "/auth/login", {"username": data["username"], "password": "wrong"}),
                   401, "INVALID_CREDENTIALS")
        response = self.mutate("post", "/auth/login", {"username": "DATAOWNER", "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), data)
        new_cookie = response.cookies[settings.API_SESSION_COOKIE].value
        self.assertNotEqual(old_cookie, new_cookie)
        self.assertNotEqual(old_csrf, self.client.cookies[settings.CSRF_COOKIE_NAME].value)
        old_client = APIClient(enforce_csrf_checks=True)
        old_client.cookies[settings.API_SESSION_COOKIE] = old_cookie
        self.error(old_client.get(f"{API}/auth/me"), 401, "UNAUTHENTICATED")
        self.error(self.mutate("post", "/auth/logout", csrf=False), 403, "CSRF_FAILED")
        response = self.mutate("post", "/auth/logout")
        self.assertEqual(response.status_code, 204, response.content)
        self.assertEqual(response.cookies[settings.API_SESSION_COOKIE]["max-age"], 0)
        self.assertIsNotNone(Session.objects.get(token_hash=hash_token(new_cookie)).revoked_at)
        self.assertEqual(self.mutate("post", "/auth/logout").status_code, 204)
        self.error(self.client.get(f"{API}/auth/me"), 401, "UNAUTHENTICATED")

    def test_idle_and_absolute_expiration(self):
        self.register()
        session = Session.objects.get()
        now = timezone.now()
        Session.objects.update(last_seen_at=now - timedelta(seconds=settings.API_SESSION_IDLE_SECONDS + 1))
        self.error(self.client.get(f"{API}/auth/me"), 401, "UNAUTHENTICATED")
        Session.objects.filter(pk=session.pk).update(last_seen_at=now, expires_at=now)
        self.error(self.client.get(f"{API}/auth/me"), 401, "UNAUTHENTICATED")

    def test_password_reset_email_token_is_single_use_and_all_sessions_are_revoked(self):
        self.register()
        second = APIClient(enforce_csrf_checks=True)
        self.assertEqual(self.mutate("post", "/auth/login", {"username": "DataOwner", "password": PASSWORD},
                                     client=second).status_code, 200)
        with self.captureOnCommitCallbacks(execute=True):
            existing = self.mutate("post", "/auth/password/forgot", {"email": "Owner@EXAMPLE.com"})
            also_existing = self.mutate("post", "/auth/password/forgot", {"email": "owner@example.com"})
            nonexistent = self.mutate("post", "/auth/password/forgot", {"email": "nobody@example.com"})
        self.assertEqual(existing.status_code, 202)
        self.assertEqual(also_existing.status_code, 202)
        self.assertEqual(nonexistent.status_code, 202)
        self.assertEqual(existing.json(), nonexistent.json())
        self.assertEqual(existing.json(), also_existing.json())
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ["owner@example.com"])
        self.assertEqual(mail.outbox[1].to, ["owner@example.com"])
        emailed_url = mail.outbox[0].body.splitlines()[1]
        self.assertEqual(urlsplit(emailed_url).path, "/reset-password")
        token = parse_qs(urlsplit(emailed_url).query)["token"][0]
        self.assertEqual(PasswordResetToken.objects.count(), 2)
        token_row = PasswordResetToken.objects.get(token_hash=hash_token(token))
        self.assertEqual(token_row.token_hash, hash_token(token))
        self.assertIsNone(token_row.used_at)
        data = {"token": token, "password": OTHER_PASSWORD, "passwordConfirmation": OTHER_PASSWORD}
        response = self.mutate("post", "/auth/password/reset", data)
        self.assertEqual(response.status_code, 204, response.content)
        token_row.refresh_from_db()
        self.assertEqual(PasswordResetToken.objects.filter(used_at__isnull=False).count(), 2)
        self.assertIsNotNone(token_row.used_at)
        self.assertEqual(Session.objects.filter(revoked_at__isnull=False).count(), 2)
        for client in (self.client, second):
            self.error(client.get(f"{API}/auth/me"), 401, "UNAUTHENTICATED")
        replay = self.mutate("post", "/auth/password/reset", data)
        self.error(replay, 422, "RESET_TOKEN_INVALID")
        self.error(self.mutate("post", "/auth/login", {"username": "DataOwner", "password": PASSWORD}),
                   401, "INVALID_CREDENTIALS")
        self.assertEqual(self.mutate("post", "/auth/login", {"username": "DataOwner", "password": OTHER_PASSWORD})
                         .status_code, 200)

    def test_expired_and_unknown_reset_tokens_use_same_error(self):
        self.register()
        user = Account.objects.get()
        PasswordResetToken.objects.create(user=user, token_hash=hash_token("expired"), expires_at=timezone.now())
        data = {"password": OTHER_PASSWORD, "passwordConfirmation": OTHER_PASSWORD}
        messages = []
        for token in ("expired", "unknown"):
            error = self.error(self.mutate("post", "/auth/password/reset", {"token": token, **data}),
                               422, "RESET_TOKEN_INVALID")
            messages.append(error["message"])
        self.assertEqual(messages[0], messages[1])
        self.assertEqual(self.get("/auth/me")["id"], str(user.id))

    @override_settings(
        API_CORS_ORIGINS=["https://app.example.test"],
        CSRF_TRUSTED_ORIGINS=["https://app.example.test"],
    )
    def test_cross_origin_requests_allow_only_configured_credentials_origins_and_headers(self):
        url = f"{API}/projects"
        preflight = self.client.options(url, HTTP_ORIGIN="https://app.example.test",
                                        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                                        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type, x-csrftoken, idempotency-key")
        self.assertEqual(preflight.status_code, 204, preflight.content)
        self.assertEqual(preflight.headers["Access-Control-Allow-Origin"], "https://app.example.test")
        self.assertEqual(preflight.headers["Access-Control-Allow-Credentials"], "true")
        self.assertIn("x-csrftoken", preflight.headers["Access-Control-Allow-Headers"])
        denied = self.client.options(url, HTTP_ORIGIN="https://attacker.example",
                                     HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.error(denied, 403, "FORBIDDEN")
        invalid_method = self.client.options(url, HTTP_ORIGIN="https://app.example.test",
                                             HTTP_ACCESS_CONTROL_REQUEST_METHOD="DELETE")
        self.error(invalid_method, 403, "FORBIDDEN")
        invalid_header = self.client.options(url, HTTP_ORIGIN="https://app.example.test",
                                             HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                                             HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization")
        self.error(invalid_header, 403, "FORBIDDEN")
        actual = self.client.get(f"{API}/capabilities", HTTP_ORIGIN="https://attacker.example")
        self.assertEqual(actual.status_code, 200, actual.content)
        self.assertNotIn("Access-Control-Allow-Origin", actual.headers)

    @override_settings(API_AUTH_LIMITS={"login": (1, 300), "register": (1, 300),
                                       "forgot": (1, 300), "reset": (1, 300)})
    def test_rate_limits_all_four_sensitive_auth_operations(self):
        actions = {
            "/auth/register": ({"username": "DataOwner", "email": "owner@example.com",
                                "password": PASSWORD, "passwordConfirmation": PASSWORD}, 201),
            "/auth/login": ({"username": "DataOwner", "password": "incorrect"}, 401),
            "/auth/password/forgot": ({"email": "nobody@example.com"}, 202),
            "/auth/password/reset": ({"token": "unknown", "password": OTHER_PASSWORD,
                                      "passwordConfirmation": OTHER_PASSWORD}, 422),
        }
        for path, (data, status) in actions.items():
            with self.subTest(path=path):
                self.assertEqual(self.mutate("post", path, data).status_code, status)
                response = self.mutate("post", path, data)
                self.error(response, 429, "RATE_LIMITED")
                self.assertGreater(int(response.headers["Retry-After"]), 0)
