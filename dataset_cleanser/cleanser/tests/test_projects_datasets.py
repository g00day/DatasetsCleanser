import csv
from io import StringIO
from uuid import uuid4

from django.test import override_settings

from cleanser.models import Dataset, DatasetVersion, Job, StoredFile
from cleanser.worker import process_next_job

from .base import API, EndpointTestCase


class ProjectDatasetEndpoints(EndpointTestCase):
    def setUp(self):
        super().setUp()
        self.account = self.register()

    def test_dashboard_upload_history_project_collection_empty_and_search(self):
        self.assertEqual(self.get("/dashboard"), {"projectCount": 0, "datasetCount": 0})
        for path in ("/projects", "/uploads"):
            self.assertEqual(self.get(path), {
                "items": [], "pagination": {"page": 1, "pageSize": 10, "total": 0, "totalPages": 0},
            })
        first = self.project("First item")
        self.project("Second item")
        self.project("Second item")
        result = self.get("/projects", search="SECOND", sort="createdAt:desc", pageSize=1, page=2)
        self.assertEqual(result["pagination"], {"page": 2, "pageSize": 1, "total": 2, "totalPages": 2})
        self.assertEqual(result["items"][0]["name"], "Second item")
        self.assertEqual(set(result["items"][0]), {"id", "name", "datasetCount", "updatedAt"})
        self.assertEqual(self.get("/projects", page=500)["pagination"]["total"], 3)
        self.assertEqual(self.get("/projects", page=500)["items"], [])
        self.assertEqual(self.get(f"/projects/{first}/datasets")["items"], [])
        self.assertEqual(self.get(f"/projects/{first}/audit-events")["items"], [])
        self.assertEqual(self.get("/dashboard"), {"projectCount": 3, "datasetCount": 0})

    def test_project_create_and_patch_and_detail_contract(self):
        response = self.mutate("post", "/projects", {"name": "  Мой проект ", "description": "  описание  "})
        self.assertEqual(response.status_code, 201, response.content)
        project = response.json()
        path = f"/projects/{project['id']}"
        self.assertEqual(response.headers["Location"], f"{API}{path}")
        self.assertEqual(project["name"], "Мой проект")
        self.assertEqual(project["description"], "  описание  ")
        self.assertEqual(self.get(path), project)
        for invalid in ({}, {"name": "  "}, {"name": 10}, {"description": "x" * 1001}, {"ownerId": self.account["id"]}):
            self.error(self.mutate("patch", path, invalid), 422, "VALIDATION_ERROR")
        response = self.mutate("patch", path, {"name": "  Изменён ", "description": ""})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.get(path)["name"], "Изменён")
        self.assertEqual(self.get(path)["description"], "")

    def test_pagination_sort_and_malformed_body_errors_use_envelope(self):
        self.project()
        for parameter in ("page=0", "page=bad", "pageSize=101", "page=1&page=2"):
            self.error(self.client.get(f"{API}/projects?{parameter}"), 400, "INVALID_PAGINATION")
        for parameter in ("sort=name:asc", "ownerId=invalid"):
            self.error(self.client.get(f"{API}/projects?{parameter}"), 422, "VALIDATION_ERROR")
        malformed = self.client.post(f"{API}/projects", data='{"name"', content_type="application/json",
                                     HTTP_X_CSRFTOKEN=self.csrf())
        self.error(malformed, 400, "MALFORMED_REQUEST")
        self.error(self.client.get(f"{API}/projects/not-a-uuid"), 404, "NOT_FOUND")
        self.error(self.mutate("delete", "/projects"), 405, "METHOD_NOT_ALLOWED")

    def test_upload_dataset_detail_history_schemas_and_rename(self):
        project_id = self.project()
        payload = 'Email;Email;Note\r\nann@example.com;bob@example.com;"note;"\r\n'.encode()
        uploaded = self.upload(project_id, payload)
        self.assertEqual(uploaded.status_code, 202, uploaded.content)
        dataset_id, job_id = uploaded.json()["datasetId"], uploaded.json()["jobId"]
        self.assertEqual(uploaded.headers["Location"], f"{API}/jobs/{job_id}")
        path = f"/datasets/{dataset_id}"
        dataset = self.get(path)
        self.assertEqual(dataset["status"], "importing")
        self.assertIsNone(dataset["latestVersionId"])
        self.assertEqual(dataset["originalFile"], {"name": "test.csv", "sizeBytes": len(payload)})
        summary = self.get(f"/projects/{project_id}/datasets", includeSchema="true")["items"][0]
        self.assertIsNone(summary["rowCount"])
        self.assertIsNone(summary["columnCount"])
        self.assertIsNone(summary["schema"])
        history = self.get("/uploads", projectId=project_id)["items"][0]
        self.assertEqual(history["datasetId"], dataset_id)
        self.assertEqual(history["status"], "importing")
        self.assertEqual(history["importJobId"], job_id)
        self.assertEqual(self.get("/dashboard"), {"projectCount": 1, "datasetCount": 1})
        self.assertEqual(self.get(f"/projects/{project_id}")["datasetCount"], 1)
        self.assertEqual(self.get(f"/jobs/{job_id}")["status"], "queued")
        self.assertTrue(process_next_job())
        dataset = self.get(path)
        self.assertEqual(dataset["status"], "ready")
        self.assertEqual(dataset["originalVersionId"], dataset["latestVersionId"])
        changed = self.mutate("patch", path, {"name": "  Переименовано  "})
        self.assertEqual(changed.status_code, 200, changed.content)
        self.assertEqual(changed.json()["name"], "Переименовано")
        self.error(self.mutate("patch", path, {"name": "valid", "status": "ready"}), 422, "VALIDATION_ERROR")
        summary = self.get(f"/projects/{project_id}/datasets", includeSchema="true", search="Переименовано")["items"][0]
        self.assertEqual(summary["rowCount"], 1)
        self.assertEqual(summary["columnCount"], 3)
        self.assertEqual([col["name"] for col in summary["schema"]], ["Email", "Email", "Note"])
        self.assertNotEqual(summary["schema"][0]["id"], summary["schema"][1]["id"])
        self.assertNotIn("schema", self.get(f"/projects/{project_id}/datasets")["items"][0])
        self.assertEqual(self.get("/uploads")["items"][0]["datasetName"], "Переименовано")

    def test_upload_idempotency_includes_content_and_import_parameters(self):
        project_id = self.project()
        key = uuid4()
        first = self.upload(project_id, idem=key)
        self.assertEqual(first.status_code, 202, first.content)
        self.drain()
        replay = self.upload(project_id, idem=key)
        self.assertEqual(replay.status_code, 202, replay.content)
        self.assertEqual(first.json(), replay.json())
        self.error(self.upload(project_id, b"Name\nBob\n", idem=key), 409, "IDEMPOTENCY_CONFLICT")
        self.error(self.upload(project_id, idem=key, delimiter=";"), 409, "IDEMPOTENCY_CONFLICT")
        self.error(self.upload(project_id, idem=False), 422, "VALIDATION_ERROR")
        self.error(self.upload(project_id, idem="not-uuid"), 422, "VALIDATION_ERROR")
        self.assertEqual(Dataset.objects.count(), 1)
        self.assertEqual(StoredFile.objects.count(), 2)
        self.assertEqual(Job.objects.count(), 2)

    def test_upload_format_encoding_and_size_are_rejected_synchronously(self):
        project_id = self.project()
        path = f"/projects/{project_id}/datasets"
        self.error(self.mutate("post", path, {"name": "x"}, idem=uuid4()), 415, "UNSUPPORTED_FILE_TYPE")
        self.error(self.upload(project_id, filename="data.pdf", media_type="application/pdf"),
                   415, "UNSUPPORTED_FILE_TYPE")
        self.error(self.upload(project_id, b"bad\xff"), 415, "UNSUPPORTED_ENCODING")
        self.error(self.upload(project_id, b"x,y\x00\na,b"), 415, "UNSUPPORTED_ENCODING")
        self.error(self.upload(project_id, ownerId=self.account["id"]), 422, "VALIDATION_ERROR")
        self.error(self.upload(project_id, delimiter="\t"), 422, "VALIDATION_ERROR")
        with override_settings(MAX_FILE_BYTES=8):
            self.error(self.upload(project_id, b"column\ndata"), 413, "FILE_TOO_LARGE")
        self.assertFalse(Dataset.objects.exists())

    def test_import_failures_are_terminal_with_non_sensitive_row_diagnostics(self):
        project_id = self.project()
        cases = ((b"a,b\nvalid,1\nmissing\n", 3), (b'a,b\nfoo"bad,1\n', 2),
                 (b'a,b\n"unclosed,1\n', 2), (b"a,\nno,1\n", 1), (b"a,b\n", 2), (b"", 1))
        for payload, line in cases:
            with self.subTest(payload=payload):
                response = self.upload(project_id, payload)
                self.assertEqual(response.status_code, 202, response.content)
                item = response.json()
                self.drain()
                job = self.get(f"/jobs/{item['jobId']}")
                self.assertEqual(job["status"], "failed")
                self.assertEqual(job["error"]["code"], "CSV_PARSE_ERROR")
                self.assertFalse(job["error"]["retryable"])
                self.assertIn(f"Строка {line}:", job["error"]["message"])
                self.assertEqual(self.get(f"/datasets/{item['datasetId']}")["status"], "import_failed")
                self.assertEqual(self.get(f"/datasets/{item['datasetId']}/versions")["items"], [])
                self.error(self.mutate("post", f"/jobs/{item['jobId']}/retry", idem=uuid4()), 409, "JOB_NOT_RETRYABLE")
        self.assertFalse(DatasetVersion.objects.exists())
        self.assertEqual(self.get("/uploads")["pagination"]["total"], len(cases))
        self.assertEqual(self.get("/dashboard")["datasetCount"], len(cases))

    def test_row_pagination_detail_cell_and_streaming_download(self):
        project_id = self.project()
        long_value = "w" * 300
        rows = [f'"{long_value if ix == 0 else "—"}";{ix};"α\r\nβ"' for ix in range(37)]
        source = ("\ufeffText;Number;Note\r\n" + "\r\n".join(rows) + "\r\n").encode()
        result = self.imported(project_id, source, encoding="utf-8-sig")
        path = f"/versions/{result['versionId']}"
        detail = self.get(path)
        self.assertEqual(detail["name"], "Исходный файл")
        self.assertEqual(detail["rowCount"], 37)
        self.assertEqual(detail["columns"][1]["dataType"], "integer")
        versions = self.get(f"/datasets/{result['datasetId']}/versions", sort="number:desc")
        self.assertEqual(versions["items"][0]["id"], result["versionId"])
        self.assertNotIn("columns", versions["items"][0])
        self.assertFalse(versions["items"][0]["canRename"])

        all_indices = []
        for page, expected in enumerate((10, 10, 10, 7, 0), 1):
            data = self.get(f"{path}/rows", page=page)
            self.assertEqual(len(data["items"]), expected)
            self.assertEqual(data["pagination"]["total"], 37)
            all_indices.extend(row["rowIndex"] for row in data["items"])
        self.assertEqual(all_indices, list(range(37)))
        row = self.get(f"{path}/rows", pageSize=2)["items"]
        self.assertEqual(row[0]["rowNumber"], 1)
        self.assertTrue(row[0]["cells"][0]["isTruncated"])
        self.assertEqual(len(row[0]["cells"][0]["value"]), 256)
        self.assertTrue(row[0]["cells"][0]["displayValue"].endswith("…"))
        self.assertEqual(row[0]["cells"][1]["value"], "0")
        self.assertEqual(row[1]["cells"][0]["value"], "—")
        column = detail["columns"][0]["id"]
        self.assertEqual(self.get(f"{path}/rows/0/cells/{column}")["value"], long_value)
        self.error(self.client.get(f"{API}{path}/rows/37/cells/{column}"), 404, "NOT_FOUND")
        self.error(self.client.get(f"{API}{path}/rows/0/cells/{uuid4()}"), 404, "NOT_FOUND")
        self.error(self.mutate("patch", path, {"name": "Other"}), 422, "ORIGINAL_VERSION_IMMUTABLE")

        original = self.client.get(f"{API}{path}/download", {"format": "original"})
        self.assertTrue(original.streaming)
        self.assertIn("attachment", original.headers["Content-Disposition"])
        self.assertEqual(b"".join(original.streaming_content), source)
        normalized = self.client.get(f"{API}{path}/download", {"format": "csv"})
        exported = b"".join(normalized.streaming_content).decode()
        records = list(csv.reader(StringIO(exported, newline="")))
        self.assertEqual(records[0], ["Text", "Number", "Note"])
        self.assertEqual(records[1], [long_value, "0", "α\r\nβ"])
        self.assertEqual(len(records), 38)
        self.error(self.client.get(f"{API}{path}/download?format=xlsx"), 422, "VALIDATION_ERROR")
