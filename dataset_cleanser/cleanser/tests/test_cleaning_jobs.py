import csv
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from urllib.parse import unquote
from uuid import uuid4

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from cleanser.csv_data import ProcessingError
from cleanser.models import AuditEvent, CleaningRun, Dataset, DatasetVersion, Job, StoredFile
from cleanser.models import IdempotencyRecord
from cleanser.management.commands.run_jobs import maintenance
from cleanser.worker import PROCESSORS, claim, process_next_job, publish_version

from .base import API, EndpointTestCase

SOURCE = (
    b'Email,Title,Value\nA@EXAMPLE.COM,"  First  ",X\nA@EXAMPLE.COM,"  First  ",X\n'
    b'A@EXAMPLE.COM,"  First  ",Y\nb@example.com," Second ",Z\nb@example.com,,X\nbad-email,"  Third  ",W\n'
)


class CleaningJobsEndpoints(EndpointTestCase):
    def setUp(self):
        super().setUp()
        self.register()
        self.project_id = self.project()
        data = self.imported(self.project_id, SOURCE)
        self.dataset_id = data["datasetId"]
        self.version_id = data["versionId"]
        self.email, self.title, self.value = [column["id"] for column in data["columns"]]
        self.dataset = f"/datasets/{self.dataset_id}"
        self.version = f"/versions/{self.version_id}"
        self.cleanings = f"{self.dataset}/cleanings"

    def plan(self, name="План", **changes):
        return {"sourceVersionId": self.version_id, "expectedLatestVersionId": self.version_id, "versionName": name,
                "columnActions": [{"columnId": self.title, "code": "trim"}], **changes}

    def submit(self, *args, idem=None, **changes):
        response = self.mutate("post", self.cleanings, self.plan(*args, **changes), idem=idem or uuid4())
        self.assertEqual(response.status_code, 202, response.content)
        return response.json()

    def test_cleaning_order_counters_columns_and_follow_up_check(self):
        self.assertEqual(self.get(self.cleanings)["items"], [])
        config = self.mutate("put", f"{self.version}/check-configuration",
                             {"expectedRevision": 1, "columnIds": [self.email, self.value]})
        self.assertEqual(config.status_code, 200, config.content)

        key = uuid4()
        plan = self.plan("  Очищено  ", datasetActions=[
            {"code": "drop_duplicate_rows", "parameters": {"keep": "first"}},
            {"code": "drop_rows_with_missing", "parameters": {"columnScope": "all", "match": "any"}},
        ], columnActions=[
            {"columnId": self.title, "code": "trim", "parameters": {}},
            {"columnId": self.email, "code": "pseudonymize", "parameters": {"strategy": "email_token"}},
        ])
        response = self.mutate("post", self.cleanings, plan, idem=key)
        self.assertEqual(response.status_code, 202, response.content)
        run_id, job_id = response.json()["cleaningRunId"], response.json()["jobId"]
        self.assertEqual(self.mutate("post", self.cleanings, plan, idem=key).json(), response.json())
        self.error(self.mutate("post", self.cleanings, {**plan, "versionName": "Changed"}, idem=key),
                   409, "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.get(self.dataset)["activeCleaningRunId"], run_id)
        run = self.get(f"/cleanings/{run_id}")
        self.assertEqual(run["status"], "queued")
        self.assertEqual(run["currentJobId"], job_id)
        self.assertIsNone(run["resultVersionId"])
        self.error(self.mutate("post", self.cleanings, self.plan("Queued"), idem=uuid4()), 409, "DATASET_BUSY")
        self.assertTrue(process_next_job())
        run = self.get(f"/cleanings/{run_id}")
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["requestedVersionName"], "Очищено")
        self.assertEqual(run["removedRowCount"], 2)
        self.assertEqual(run["changedCellCount"], 8)
        self.assertEqual([item["actionCode"] for item in run["operationResults"]],
                         ["drop_rows_with_missing", "drop_duplicate_rows", "pseudonymize", "trim"])
        self.assertEqual([item["removedRowCount"] for item in run["operationResults"]], [1, 1, 0, 0])
        self.assertEqual([item["changedCellCount"] for item in run["operationResults"]], [0, 0, 4, 4])
        self.assertEqual(self.get(self.cleanings)["items"], [run])
        dataset = self.get(self.dataset)
        self.assertEqual(dataset["originalVersionId"], self.version_id)
        self.assertEqual(dataset["latestVersionId"], run["resultVersionId"])
        self.assertIsNone(dataset["activeCleaningRunId"])
        latest = f"/versions/{run['resultVersionId']}"
        details = self.get(latest)
        self.assertEqual(details["parentVersionId"], self.version_id)
        self.assertEqual(details["number"], 2)
        self.assertEqual(details["rowCount"], 4)
        self.assertEqual(details["kind"], "processed")
        self.assertTrue(details["canRename"])
        original = self.get(self.version)
        self.assertEqual([column["key"] for column in details["columns"]],
                         [column["key"] for column in original["columns"]])
        self.assertNotEqual(details["columns"][0]["id"], self.email)
        configuration = self.get(f"{latest}/check-configuration")
        self.assertEqual(configuration["columnIds"], [details["columns"][i]["id"] for i in (0, 2)])
        self.assertEqual(self.get(f"{latest}/quality-summary")["status"], "queued")
        self.drain()
        self.assertEqual(self.get(f"/checks/{run['resultCheckRunId']}")["status"], "succeeded")

        rows = self.get(f"{latest}/rows")["items"]
        self.assertEqual([row["rowIndex"] for row in rows], [0, 1, 2, 3])
        self.assertEqual([row["cells"][1]["value"] for row in rows], ["First", "First", "Second", "Third"])
        tokens = [row["cells"][0]["value"] for row in rows]
        self.assertEqual(tokens[0], tokens[1])
        self.assertEqual(len(set(tokens)), 3)
        self.assertTrue(all(token.endswith("@example.invalid") for token in tokens))
        original_rows = self.get(f"{self.version}/rows")["items"]
        self.assertEqual(original_rows[0]["cells"][0]["value"], "A@EXAMPLE.COM")
        self.assertEqual(len(original_rows), 6)
        download = self.client.get(f"{API}{self.version}/download", {"format": "original"})
        self.assertEqual(b"".join(download.streaming_content), SOURCE)
        self.assertEqual(self.get("/uploads")["pagination"]["total"], 1)
        events = self.get(f"{self.dataset}/audit-events")["items"]
        self.assertEqual(len(events), 4)
        self.assertEqual({event["type"] for event in events}, {"cleaning_operation_applied"})
        self.assertEqual({event["actor"]["username"] for event in events}, {"DataOwner"})
        self.assertEqual({event["resultVersion"]["id"] for event in events}, {run["resultVersionId"]})
        self.assertNotIn("A@EXAMPLE.COM", repr(events))

    def test_cleaning_validates_plan_source_names_and_concurrency(self):
        for changes, code, status in (
            ({"columnActions": []}, "VALIDATION_ERROR", 422),
            ({"columnActions": [{"columnId": str(uuid4()), "code": "trim"}]}, "INVALID_COLUMN", 422),
            ({"columnActions": [{"columnId": self.title, "code": "trim"}] * 2}, "INVALID_COLUMN", 422),
            ({"columnActions": [{"columnId": self.title, "code": "delete"}]}, "UNSUPPORTED_ACTION", 422),
            ({"columnActions": [{"columnId": self.email, "code": "pseudonymize",
                                 "parameters": {"strategy": "text_token"}}]}, "UNSUPPORTED_ACTION", 422),
            ({"datasetActions": [{"code": "drop_duplicate_rows", "parameters": {"keep": "last"}}]},
             "UNSUPPORTED_ACTION", 422),
            ({"versionName": " исходный ФАЙЛ "}, "VERSION_NAME_TAKEN", 409),
            ({"sourceVersionId": str(uuid4())}, "NOT_FOUND", 404),
            ({"expectedLatestVersionId": str(uuid4())}, "STALE_BASE_VERSION", 409),
        ):
            with self.subTest(changes=changes):
                response = self.mutate("post", self.cleanings, self.plan(**changes), idem=uuid4())
                self.error(response, status, code)
        self.assertFalse(CleaningRun.objects.exists())
        self.assertEqual(DatasetVersion.objects.count(), 1)

        first = self.submit("First")
        self.drain()
        version_id = self.get(f"/cleanings/{first['cleaningRunId']}")["resultVersionId"]
        data = self.plan("fIRst", expectedLatestVersionId=version_id)
        self.error(self.mutate("post", self.cleanings, data, idem=uuid4()), 409, "VERSION_NAME_TAKEN")
        self.error(self.mutate("post", self.cleanings, self.plan("Old pointer"), idem=uuid4()),
                   409, "STALE_BASE_VERSION")
        self.submit("Reserved", expectedLatestVersionId=version_id)
        self.error(self.mutate("patch", f"/versions/{version_id}", {"name": " RESERVED "}),
                   409, "VERSION_NAME_TAKEN")
        self.drain()
        self.assertEqual(self.get(self.dataset)["originalVersionId"], self.version_id)
        self.assertEqual(self.get(f"{self.dataset}/versions")["pagination"]["total"], 3)

    def test_processed_rename_audit_links_and_export_filename(self):
        result = self.submit("Историческое")
        self.drain()
        version_id = self.get(f"/cleanings/{result['cleaningRunId']}")["resultVersionId"]
        path = f"/versions/{version_id}"
        rename = self.mutate("patch", path, {"name": "  Финальный отчёт "})
        self.assertEqual(rename.status_code, 200, rename.content)
        self.assertEqual(rename.json()["name"], "Финальный отчёт")
        self.assertEqual(rename.json()["number"], 2)
        self.assertEqual(self.get(f"{self.dataset}/versions")["items"][0]["name"], "Финальный отчёт")
        download = self.client.get(f"{API}{path}/download")
        self.assertEqual(download.status_code, 200, download.content if not download.streaming else "")
        self.assertIn("Финальный отчёт.csv", unquote(download.headers["Content-Disposition"]))
        content = b"".join(download.streaming_content).decode()
        self.assertEqual(list(csv.reader(StringIO(content)))[1][1], "First")
        self.error(self.client.get(f"{API}{path}/download?format=original"), 422, "VALIDATION_ERROR")
        audit = self.get(f"/projects/{self.project_id}/audit-events", datasetId=self.dataset_id, pageSize=5)
        self.assertEqual(audit["pagination"]["total"], 2)
        self.assertEqual(audit["items"][0]["details"], {"oldName": "Историческое", "newName": "Финальный отчёт"})
        self.assertEqual(audit["items"][1]["resultVersion"]["name"], "Финальный отчёт")
        only = self.get(f"{self.dataset}/audit-events", versionId=version_id, type="version_renamed",
                        **{"from": "2000-01-01T00:00:00Z", "to": "2100-01-01T00:00:00Z"})
        self.assertEqual(only["items"], audit["items"][:1])
        self.assertEqual(self.get(f"{self.dataset}/audit-events", **{"to": "2000-01-01T00:00:00Z"})["items"], [])
        self.error(self.client.get(f"{API}{self.dataset}/audit-events?from=bad"), 422, "VALIDATION_ERROR")

    def test_audit_page_sizes_for_34_events(self):
        result = self.submit("Version 0")
        self.drain()
        version_id = self.get(f"/cleanings/{result['cleaningRunId']}")["resultVersionId"]
        for index in range(33):
            response = self.mutate("patch", f"/versions/{version_id}", {"name": f"Rename {index}"})
            self.assertEqual(response.status_code, 200, response.content)
        audit_path = f"{self.dataset}/audit-events"
        ids = []
        for index, amount in enumerate((10, 10, 10, 4, 0), 1):
            page = self.get(audit_path, page=index)
            self.assertEqual(len(page["items"]), amount)
            self.assertEqual(page["pagination"]["total"], 34)
            ids.extend(record["id"] for record in page["items"])
        self.assertEqual(len(set(ids)), 34)
        self.assertEqual([event["id"] for event in self.get(audit_path, pageSize=5)["items"]], ids[:5])

    def test_zero_rows_retains_schema_and_exports_header(self):
        data = self.imported(self.project_id, b"Name,Value\nOne,\n,Two\n")
        plan = {"sourceVersionId": data["versionId"], "expectedLatestVersionId": data["versionId"],
                "versionName": "Empty", "datasetActions": [{"code": "drop_rows_with_missing"}]}
        response = self.mutate("post", f"/datasets/{data['datasetId']}/cleanings", plan, idem=uuid4())
        self.assertEqual(response.status_code, 202, response.content)
        self.drain()
        result = self.get(f"/cleanings/{response.json()['cleaningRunId']}")
        self.assertEqual(result["removedRowCount"], 2)
        path = f"/versions/{result['resultVersionId']}"
        self.assertEqual(self.get(path)["columnCount"], 2)
        self.assertEqual(self.get(path)["rowCount"], 0)
        self.assertEqual(self.get(f"{path}/rows")["items"], [])
        self.assertEqual(self.get(f"{path}/quality-summary")["result"]["issueCount"], 0)
        download = self.client.get(f"{API}{path}/download")
        self.assertEqual(b"".join(download.streaming_content), b"Name,Value\n")

    def test_lowercase_does_not_run_duplicate_removal_again_and_preserves_zero_counts(self):
        data = self.imported(self.project_id, b"Word\nHELLO\nhello\n")
        plan = {"sourceVersionId": data["versionId"], "expectedLatestVersionId": data["versionId"],
                "versionName": "Lowercase", "datasetActions": [{"code": "drop_duplicate_rows"}],
                "columnActions": [{"code": "lowercase", "columnId": data["columns"][0]["id"]}]}
        response = self.mutate("post", f"/datasets/{data['datasetId']}/cleanings", plan, idem=uuid4())
        self.assertEqual(response.status_code, 202, response.content)
        self.drain()
        result = self.get(f"/cleanings/{response.json()['cleaningRunId']}")
        self.assertEqual(result["operationResults"][0]["removedRowCount"], 0)
        self.assertEqual(result["changedCellCount"], 1)
        rows = self.get(f"/versions/{result['resultVersionId']}/rows")["items"]
        self.assertEqual([row["cells"][0]["value"] for row in rows], ["hello", "hello"])

    def test_failure_rolls_back_publication_and_retry_is_idempotent(self):
        response = self.submit()
        run_id, job_id = response["cleaningRunId"], response["jobId"]

        def fail_after_inserts(*args, **kwargs):
            publish_version(*args, **kwargs)
            raise ProcessingError("TEMPORARY_STORAGE_FAILURE", "Временный сбой.", retryable=True)

        with patch("cleanser.worker.publish_version", side_effect=fail_after_inserts):
            self.assertTrue(process_next_job())
        failed = self.get(f"/jobs/{job_id}")
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["error"]["retryable"])
        self.assertEqual(self.get(f"/cleanings/{run_id}")["status"], "failed")
        self.assertEqual(self.get(self.dataset)["latestVersionId"], self.version_id)
        self.assertFalse(AuditEvent.objects.exists())
        self.assertEqual(DatasetVersion.objects.count(), 1)
        self.assertEqual(StoredFile.objects.count(), 2)

        retry = f"/jobs/{job_id}/retry"
        key = uuid4()
        submitted = self.mutate("post", retry, idem=key)
        self.assertEqual(submitted.status_code, 202, submitted.content)
        self.assertEqual(submitted.json()["resourceType"], "cleaning")
        self.assertEqual(submitted.json()["resourceId"], run_id)
        self.assertEqual(self.mutate("post", retry, idem=key).json(), submitted.json())
        self.error(self.mutate("post", retry, idem=uuid4()), 409, "JOB_ALREADY_RUNNING")
        self.drain()
        self.assertFalse(process_next_job())
        attempt_id = submitted.json()["jobId"]
        self.assertEqual(self.get(f"/jobs/{attempt_id}")["attempt"], 2)
        self.assertEqual(self.get(f"/jobs/{attempt_id}")["status"], "succeeded")
        self.assertEqual(self.get(f"/jobs/{attempt_id}")["progressPercent"], 100)
        self.assertEqual(self.get(f"/cleanings/{run_id}")["status"], "succeeded")
        self.assertEqual(self.get(f"/cleanings/{run_id}")["currentJobId"], attempt_id)
        self.assertEqual(DatasetVersion.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.count(), 1)
        self.assertEqual(CleaningRun.objects.count(), 1)
        self.error(self.mutate("post", f"/jobs/{attempt_id}/retry", idem=uuid4()), 409, "JOB_NOT_RETRYABLE")

    def test_retry_refuses_stale_base_after_other_cleaning_succeeds(self):
        response = self.submit("Failed")
        failure = ProcessingError("TEMPORARY", "Временный сбой.", retryable=True)
        with patch("cleanser.worker.publish_version", side_effect=failure):
            self.assertTrue(process_next_job())
        self.submit("Successful")
        self.drain()
        self.error(self.mutate("post", f"/jobs/{response['jobId']}/retry", idem=uuid4()), 409, "STALE_BASE_VERSION")

    def test_cleaning_stays_succeeded_if_automatic_result_check_fails(self):
        result = self.submit()
        self.assertTrue(process_next_job())
        run = self.get(f"/cleanings/{result['cleaningRunId']}")
        version_id = run["resultVersionId"]
        check_id = run["resultCheckRunId"]

        def fail(execution):
            raise ProcessingError("CHECK_UNAVAILABLE", "Сбой проверки.", retryable=True)

        with patch.dict(PROCESSORS, {Job.Kind.CHECK: fail}):
            self.assertTrue(process_next_job())
        self.assertEqual(self.get(f"/cleanings/{result['cleaningRunId']}")["status"], "succeeded")
        self.assertEqual(self.get(self.dataset)["latestVersionId"], version_id)
        check = self.get(f"/checks/{check_id}")
        self.assertEqual(check["status"], "failed")
        retry = self.mutate("post", f"/jobs/{check['currentJobId']}/retry", idem=uuid4())
        self.assertEqual(retry.status_code, 202, retry.content)
        self.drain()
        self.assertEqual(self.get(f"/checks/{check_id}")["status"], "succeeded")
        self.assertEqual(DatasetVersion.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.count(), 1)

    def test_expiring_idempotency_record_does_not_delete_job_or_its_resource(self):
        response = self.submit("History preserved")
        job_id, run_id = response["jobId"], response["cleaningRunId"]
        record = IdempotencyRecord.objects.get(job_id=job_id)
        record.expires_at = timezone.now() - timedelta(seconds=1)
        record.save(update_fields=["expires_at"])
        maintenance()
        self.assertFalse(IdempotencyRecord.objects.filter(pk=record.pk).exists())
        job = self.get(f"/jobs/{job_id}")
        self.assertEqual(job["status"], "queued")
        self.assertEqual(self.get(f"/cleanings/{run_id}")["currentJobId"], job_id)
        self.assertEqual(self.get("/jobs/%s" % job_id), job)

    def test_lost_import_worker_updates_resource_and_retry_reuses_dataset(self):
        upload = self.upload(self.project_id)
        self.assertEqual(upload.status_code, 202, upload.content)
        original_job_id = upload.json()["jobId"]
        dataset_id = upload.json()["datasetId"]
        lease = claim()
        self.assertEqual(str(lease.pk), original_job_id)
        running = self.get(f"/jobs/{original_job_id}")
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["stage"], "reading_file")
        self.assertIsNone(running["progressPercent"])
        self.assertFalse(process_next_job())
        Job.objects.filter(pk=lease.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertFalse(process_next_job())
        self.assertEqual(self.get(f"/jobs/{original_job_id}")["error"]["code"], "WORKER_LOST")
        self.assertEqual(self.get(f"/datasets/{dataset_id}")["status"], "import_failed")
        retry = self.mutate("post", f"/jobs/{original_job_id}/retry", idem=uuid4())
        self.assertEqual(retry.status_code, 202, retry.content)
        self.assertEqual(retry.json()["resourceId"], dataset_id)
        self.assertEqual(retry.json()["resourceType"], "dataset")
        self.assertEqual(self.get(f"/datasets/{dataset_id}")["status"], "importing")
        self.drain()
        self.assertEqual(self.get(f"/datasets/{dataset_id}")["status"], "ready")
        self.assertEqual(self.get(f"/datasets/{dataset_id}")["importJobId"], retry.json()["jobId"])

    def test_upload_respects_active_job_and_storage_limits(self):
        with override_settings(MAX_ACTIVE_JOBS_PER_OWNER=1):
            self.assertEqual(self.upload(self.project_id).status_code, 202)
            limited = self.upload(self.project_id)
            self.error(limited, 429, "RATE_LIMITED")
            self.assertIn("Retry-After", limited.headers)
            self.drain()
        with override_settings(MAX_OWNER_STORAGE_BYTES=settings.MAX_FILE_BYTES, MAX_FILE_BYTES=settings.MAX_FILE_BYTES):
            with override_settings(MAX_OWNER_STORAGE_BYTES=1):
                self.error(self.upload(self.project_id), 413, "STORAGE_QUOTA_EXCEEDED")
        self.assertEqual(Dataset.objects.count(), 2)
