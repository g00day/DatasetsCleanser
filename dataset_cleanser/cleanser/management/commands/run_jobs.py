from datetime import timedelta
from time import monotonic, sleep

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections
from django.utils import timezone

from auth_app.models import AuthRateLimit, PasswordResetToken, Session
from cleanser.files import remove_orphan_files
from cleanser.models import IdempotencyRecord
from cleanser.worker import process_next_job


def maintenance():
    now = timezone.now()
    IdempotencyRecord.objects.filter(expires_at__lte=now).delete()
    AuthRateLimit.objects.filter(window_start__lte=now - timedelta(days=1)).delete()
    PasswordResetToken.objects.filter(expires_at__lte=now - timedelta(days=1)).delete()
    Session.objects.filter(expires_at__lte=now - timedelta(days=1)).delete()
    remove_orphan_files()


class Command(BaseCommand):
    help = "Process durable jobs and periodically clean up expired records and unreferenced files."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process jobs until the queue is empty.")
        parser.add_argument("--poll-interval", type=float, default=1.0)

    def handle(self, *args, **options):
        interval = options["poll_interval"]
        if not 0 < interval <= 60:
            raise CommandError("--poll-interval must be greater than 0 and at most 60 seconds.")
        if not 0 < settings.JOB_LEASE_SECONDS <= settings.JOB_TIMEOUT_SECONDS:
            raise CommandError("Set 0 < JOB_LEASE_SECONDS <= JOB_TIMEOUT_SECONDS.")

        next_maintenance = 0
        while True:
            try:
                close_old_connections()
                if monotonic() >= next_maintenance:
                    maintenance()
                    next_maintenance = monotonic() + 600
                worked = process_next_job()
            except KeyboardInterrupt:
                return
            except OperationalError as exc:
                if options["once"]:
                    raise CommandError("Job database is temporarily unavailable.") from exc
                self.stderr.write("Job database temporarily unavailable. Retrying.")
                sleep(interval)
                continue
            if not worked:
                if options["once"]:
                    return
                sleep(interval)
