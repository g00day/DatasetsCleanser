from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from .base import API, EndpointTestCase


class OwnershipEndpoints(EndpointTestCase):
    def setUp(self):
        super().setUp()
        self.register()
        self.project_a = self.project("A")
        self.data_a = self.imported(self.project_a)
        self.v_a = self.data_a["versionId"]
        self.d_a = self.data_a["datasetId"]
        self.run_a = self.get(f"/versions/{self.v_a}/checks")["items"][0]["id"]
        self.client_b = APIClient(enforce_csrf_checks=True)
        self.register("OtherOwner", "second@example.com", client=self.client_b)
        self.project_b = self.project("B", client=self.client_b)
        self.data_b = self.imported(self.project_b, client=self.client_b)
        self.v_b = self.data_b["versionId"]
        self.d_b = self.data_b["datasetId"]
        self.run_b = self.get(f"/versions/{self.v_b}/checks", client=self.client_b)["items"][0]["id"]
        clean = self.mutate("post", f"/datasets/{self.d_b}/cleanings", {
            "sourceVersionId": self.v_b, "expectedLatestVersionId": self.v_b, "versionName": "B private version",
            "columnActions": [{"columnId": self.data_b["columns"][0]["id"], "code": "trim"}],
        }, client=self.client_b, idem=uuid4())
        self.assertEqual(clean.status_code, 202, clean.content)
        self.cleaning_b = clean.json()["cleaningRunId"]
        self.drain()
        self.processed_b = self.get(f"/cleanings/{self.cleaning_b}", client=self.client_b)["resultVersionId"]

    def test_foreign_resources_are_hidden_across_all_reader_routes(self):
        col = self.data_b["columns"][0]["id"]
        paths = [
            f"/projects/{self.project_b}", f"/projects/{self.project_b}/datasets",
            f"/projects/{self.project_b}/audit-events", f"/datasets/{self.d_b}",
            f"/datasets/{self.d_b}/versions", f"/versions/{self.v_b}", f"/versions/{self.v_b}/rows",
            f"/versions/{self.v_b}/rows/0/cells/{col}", f"/versions/{self.v_b}/download",
            f"/versions/{self.v_b}/check-configuration", f"/versions/{self.v_b}/checks",
            f"/versions/{self.v_b}/quality-summary", f"/checks/{self.run_b}",
            f"/checks/{self.run_b}/column-summary", f"/checks/{self.run_b}/issues",
            f"/datasets/{self.d_b}/cleanings", f"/datasets/{self.d_b}/audit-events",
            f"/cleanings/{self.cleaning_b}", f"/jobs/{self.data_b['jobId']}",
            f"/uploads?projectId={self.project_b}",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.error(self.client.get(f"{API}{path}"), 404, "NOT_FOUND")
        self.assertEqual(self.get("/dashboard"), {"projectCount": 1, "datasetCount": 1})
        self.assertEqual([item["id"] for item in self.get("/projects")["items"]], [self.project_a])
        self.assertEqual([item["datasetId"] for item in self.get("/uploads")["items"]], [self.d_a])

    def test_foreign_resources_cannot_be_modified(self):
        actions = [
            ("patch", f"/projects/{self.project_b}", {"name": "Intrusion"}),
            ("patch", f"/datasets/{self.d_b}", {"name": "Intrusion"}),
            ("patch", f"/versions/{self.processed_b}", {"name": "Intrusion"}),
            ("put", f"/versions/{self.v_b}/check-configuration",
             {"columnIds": [self.data_b["columns"][0]["id"]], "expectedRevision": 1}),
            ("post", f"/versions/{self.v_b}/checks", {"configurationRevision": 1}),
            ("post", f"/datasets/{self.d_b}/cleanings", {}),
            ("post", f"/jobs/{self.data_b['jobId']}/retry", None),
        ]
        for method, path, data in actions:
            with self.subTest(path=path):
                self.error(self.mutate(method, path, data, idem=uuid4()), 404, "NOT_FOUND")
        upload = self.client.post(f"{API}/projects/{self.project_b}/datasets", {
            "name": "Intrusion", "file": SimpleUploadedFile("private.csv", b"Name\nOther\n", content_type="text/csv"),
        }, format="multipart", HTTP_X_CSRFTOKEN=self.csrf(), HTTP_IDEMPOTENCY_KEY=str(uuid4()))
        self.error(upload, 404, "NOT_FOUND")
        self.assertEqual(self.get(f"/versions/{self.processed_b}", client=self.client_b)["name"], "B private version")

    def test_nested_ids_must_belong_to_the_requested_resource(self):
        col_b = self.data_b["columns"][0]["id"]
        col_a = self.data_a["columns"][0]["id"]
        not_found = [
            f"/versions/{self.v_a}/rows/0/cells/{col_b}",
            f"/versions/{self.v_a}/rows?checkRunId={self.run_b}&onlyProblemRows=true",
            f"/projects/{self.project_a}/audit-events?datasetId={self.d_b}",
            f"/datasets/{self.d_a}/audit-events?versionId={self.v_b}",
        ]
        for path in not_found:
            with self.subTest(path=path):
                self.error(self.client.get(f"{API}{path}"), 404, "NOT_FOUND")
        invalid_column = [
            f"/versions/{self.v_a}/rows?checkRunId={self.run_a}&columnId={col_b}",
            f"/checks/{self.run_a}/issues?columnId={col_b}",
        ]
        for path in invalid_column:
            with self.subTest(path=path):
                self.error(self.client.get(f"{API}{path}"), 422, "INVALID_COLUMN")
        self.error(self.mutate("put", f"/versions/{self.v_a}/check-configuration",
                              {"columnIds": [col_a, col_b], "expectedRevision": 1}), 422, "INVALID_COLUMN")
        base = {"sourceVersionId": self.v_a, "expectedLatestVersionId": self.v_a, "versionName": "Local"}
        action = {"columnId": col_b, "code": "trim"}
        self.error(self.mutate("post", f"/datasets/{self.d_a}/cleanings",
                              {**base, "columnActions": [action]}, idem=uuid4()), 422, "INVALID_COLUMN")
        self.error(self.mutate("post", f"/datasets/{self.d_a}/cleanings", {
            **base, "sourceVersionId": self.v_b, "columnActions": [{"columnId": col_a, "code": "trim"}],
        }, idem=uuid4()), 404, "NOT_FOUND")
        version_b_columns = self.get(f"/versions/{self.processed_b}", client=self.client_b)["columns"]
        self.error(self.client_b.get(f"{API}/versions/{self.v_b}/rows/0/cells/{version_b_columns[0]['id']}"),
                   404, "NOT_FOUND")
