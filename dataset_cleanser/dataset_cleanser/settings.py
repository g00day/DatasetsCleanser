import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", encoding="utf-8")


def flag(name, default=False):
    return os.getenv(name, str(default)).lower() in {"true", "1", "yes"}


def entries(name, default=""):
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


PRODUCTION = flag("DJANGO_PRODUCTION")
DEBUG = flag("DJANGO_DEBUG") and not PRODUCTION
SECRET_KEY = os.getenv("SECRET_KEY", "")
if PRODUCTION and not SECRET_KEY:
    raise ImproperlyConfigured("Set SECRET_KEY in production.")
SECRET_KEY = SECRET_KEY or "django-insecure-local-development-key-datasets-cleanser-only"
ALLOWED_HOSTS = entries("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]" if not PRODUCTION else "")
API_CORS_ORIGINS = entries("API_CORS_ORIGINS")
if any("*" in origin for origin in API_CORS_ORIGINS):
    raise ImproperlyConfigured("API_CORS_ORIGINS must list exact origins.")
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([*entries("DJANGO_CSRF_TRUSTED_ORIGINS"), *API_CORS_ORIGINS]))
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE = PRODUCTION or flag("DJANGO_SECURE_COOKIES")
if flag("DJANGO_TRUST_PROXY_HTTPS"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "auth_app",
    "cleanser",
]

MIDDLEWARE = [
    "dataset_cleanser.middleware.APIRequestMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "dataset_cleanser.urls"
WSGI_APPLICATION = "dataset_cleanser.wsgi.application"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

if os.getenv("DATABASE_NAME"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.getenv("DATABASE_HOST", ""),
        "PORT": os.getenv("DATABASE_PORT", ""),
        "NAME": os.environ["DATABASE_NAME"],
        "USER": os.getenv("DATABASE_USER", ""),
        "PASSWORD": os.getenv("DATABASE_PASSWORD", ""),
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("SQLITE_PATH", BASE_DIR / "db.sqlite3"),
        "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 30},
    }}

AUTH_USER_MODEL = "auth_app.Account"
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": PASSWORD_MIN_LENGTH}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["auth_app.authentication.CookieSessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "cleanser.http.exception_handler",
    "NON_FIELD_ERRORS_KEY": "nonFieldErrors",
    "URL_FORMAT_OVERRIDE": None,
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
APPEND_SLASH = False

API_SESSION_COOKIE = "dc_session"
API_SESSION_IDLE_SECONDS = int(os.getenv("API_SESSION_IDLE_SECONDS", "1800"))
API_SESSION_MAX_SECONDS = int(os.getenv("API_SESSION_MAX_SECONDS", "604800"))
API_RESET_TOKEN_SECONDS = int(os.getenv("API_RESET_TOKEN_SECONDS", "1800"))
API_AUTH_LIMITS = {
    "register": (10, 3600),
    "login": (20, 300),
    "forgot": (10, 3600),
    "reset": (20, 300),
}
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@example.com")
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = flag("EMAIL_USE_TLS")
EMAIL_USE_SSL = flag("EMAIL_USE_SSL")
EMAIL_TIMEOUT = 10

PRIVATE_FILE_ROOT = Path(os.getenv("PRIVATE_FILE_ROOT", "private_files"))
if not PRIVATE_FILE_ROOT.is_absolute():
    PRIVATE_FILE_ROOT = BASE_DIR / PRIVATE_FILE_ROOT
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(10 * 1024 * 1024)))
MAX_OWNER_STORAGE_BYTES = int(os.getenv("MAX_OWNER_STORAGE_BYTES", str(512 * 1024 * 1024)))
MAX_ACTIVE_JOBS_PER_OWNER = int(os.getenv("MAX_ACTIVE_JOBS_PER_OWNER", "4"))
MAX_CSV_COLUMNS = 256
MAX_CSV_FIELD_CHARS = 65_536
MAX_CSV_ROWS = 100_000
MAX_CSV_CELLS = 500_000
CSV_PARSE_TIMEOUT_SECONDS = int(os.getenv("CSV_PARSE_TIMEOUT_SECONDS", "30"))
CELL_PREVIEW_CHARS = 256
JOB_TIMEOUT_SECONDS = int(os.getenv("JOB_TIMEOUT_SECONDS", "600"))
JOB_LEASE_SECONDS = int(os.getenv("JOB_LEASE_SECONDS", "60"))
IDEMPOTENCY_TTL_SECONDS = max(86_400, int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400")))
DATA_UPLOAD_MAX_NUMBER_FILES = 1
