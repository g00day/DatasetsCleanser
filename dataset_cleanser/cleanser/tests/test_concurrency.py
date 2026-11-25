from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import skipUnless
from uuid import uuid4

from django.db import connection, connections
from django.test import override_settings
from rest_framework.test import APIClient, APITransactionTestCase

from cleanser.models import AuditEvent, CleaningRun, DatasetVersion

from .base import EndpointTestCase


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row-level locking requires PostgreSQL.")
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ConcurrentEndpointTests(APITransactionTestCase):
    csrf = EndpointTestCase.csrf
    mutate = EndpointTestCase.mutate
    register = EndpointTestCase.register
    project = EndpointTestCase.project
    upload = EndpointTestCase.upload
    imported = EndpointTestCase.imported
    drain = EndpointTestCase.drain
    get = EndpointTestCase.get

    def setUp(self):
        super().setUp()
        self.client = APIClient(enforce_csrf_checks=True)
        files = TemporaryDirectory(prefix="datasets-cleanser-concurrency-")
        self.addCleanup(files.cleanup)
        storage = override_settings(PRIVATE_FILE_ROOT=Path(files.name))
        storage.enable()
        self.addCleanup(storage.disable)

    def test_concurrent_cleaning_submissions_share_one_idempotent_run_and_result(self):
        self.register()
        dataset = self.imported(self.project())
        barrier = Barrier(2, timeout=10)
        path = f"/datasets/{dataset['datasetId']}/cleanings"
        key = uuid4()
        data = {"sourceVersionId": dataset["versionId"], "expectedLatestVersionId": dataset["versionId"],
                "versionName": "Concurrent", "columnActions": [{"columnId": dataset["columns"][0]["id"], "code": "trim"}]}
        session_cookies = self.client.cookies.copy()

        def submit():
            try:
                client = APIClient(enforce_csrf_checks=True)
                client.cookies.update(session_cookies)
                barrier.wait()
                response = self.mutate("post", path, data, client=client, idem=key)
                return response.status_code, response.json()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [pool.submit(submit) for _ in range(2)]
            responses = [attempt.result(timeout=15) for attempt in attempts]
        self.assertEqual(responses[0], responses[1])
        self.assertEqual(responses[0][0], 202)
        self.assertEqual(CleaningRun.objects.count(), 1)
        self.drain()
        self.assertEqual(DatasetVersion.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.count(), 1)
