# DatasetCleanser API

Django REST Framework API for CSV projects, quality checks, cleaning runs, audit events, and versioned exports. Endpoints use the /api/v1/ prefix and return JSON field names in camelCase. Browser requests authenticate through the dc_session HttpOnly cookie and must include an X-CSRFToken obtained from /api/v1/auth/csrf.

## Setup

Use Python 3.12 or newer and PostgreSQL 14 or newer. Copy dataset_cleanser/.env.example to dataset_cleanser/.env, set a private production SECRET_KEY, and configure your database and email provider. The default local development configuration uses SQLite, an insecure development-only key, and host localhost. Set DJANGO_PRODUCTION=true to require an explicit secret key.

~~~sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cd dataset_cleanser
../.venv/bin/python manage.py check
../.venv/bin/python manage.py migrate
~~~

In a second process, run the database-backed worker. Jobs remain in the database if the worker or application restarts.

~~~sh
../.venv/bin/python manage.py run_jobs
~~~

For local development, run the API in another terminal with ../.venv/bin/python manage.py runserver 127.0.0.1:8000.

Configure SMTP before enabling password reset for real users. In development, the default SMTP settings send mail to localhost on port 25. For isolated development, use Django's EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend, which prints recovery links to the terminal.

## Configuration

DJANGO_PRODUCTION, SECRET_KEY, DJANGO_ALLOWED_HOSTS, DJANGO_SECURE_COOKIES, DJANGO_TRUST_PROXY_HTTPS, DJANGO_CSRF_TRUSTED_ORIGINS, API_CORS_ORIGINS, DATABASE_HOST, DATABASE_PORT, DATABASE_NAME, DATABASE_USER, DATABASE_PASSWORD, SQLITE_PATH, PRIVATE_FILE_ROOT, MAX_FILE_BYTES, MAX_OWNER_STORAGE_BYTES, MAX_ACTIVE_JOBS_PER_OWNER, JOB_TIMEOUT_SECONDS, JOB_LEASE_SECONDS, API_SESSION_IDLE_SECONDS, API_SESSION_MAX_SECONDS, API_RESET_TOKEN_SECONDS, FRONTEND_URL, DEFAULT_FROM_EMAIL, EMAIL_BACKEND, EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_USE_TLS, and EMAIL_USE_SSL configure the service. See .env.example for names and safe initial values. Production session and CSRF cookies are secure by default. Add only explicitly approved frontend origins. Do not configure API_CORS_ORIGINS=*.

Uploads and version exports live under PRIVATE_FILE_ROOT, outside Django's public media route. Back up this directory together with the PostgreSQL database. Keep database and file-storage snapshots consistent when restoring.

The service limits one CSV upload to 10 MiB, 256 columns, 100,000 rows, 500,000 cells, and 65,536 characters per cell by default. Storage is limited to 512 MiB per owner, with four queued or running jobs per owner. These values can be overridden through the matching environment variables and are returned by /api/v1/capabilities.

## Background work

run_jobs polls durable SQL jobs. Run enough worker processes for expected throughput. Jobs for the same dataset are serialized, while different datasets can be processed concurrently. Keep JOB_LEASE_SECONDS below or equal to JOB_TIMEOUT_SECONDS. The worker renews leases while processing, detects lost workers, and retries only failures identified as recoverable.

## Tests

The endpoint tests use DRF's APIClient with CSRF checks enabled. A fast local run uses SQLite.

~~~sh
.venv/bin/python manage.py test
~~~

Run the same suite against PostgreSQL in CI, including the idempotency and concurrent-submission test.

## Routes

The API provides authentication, projects, uploads, datasets, versions, row pages and cell values, downloads, quality checks, cleaning runs, audit events, and job retries. Generate migrations after model changes with python manage.py makemigrations.
