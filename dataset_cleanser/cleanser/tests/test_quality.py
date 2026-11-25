from unittest.mock import patch
from uuid import uuid4

from cleanser.csv_data import ProcessingError
from cleanser.models import Job, QualityCheckRun
from cleanser.worker import PROCESSORS, process_next_job

from .base import API, EndpointTestCase

CSV = b"Email,Qty,Note\nalice@example.com,10,ok\ninvalid,20,note\n,broken,\nbob@example.com,30,   \ncarol@example.com,40,ok\n"


def fail_check(execution):
    raise ProcessingError("CHECK_UNAVAILABLE", "Временный сбой проверки.", retryable=True)


class QualityEndpoints(EndpointTestCase):
    def setUp(self):
        super().setUp()
        self.register()
        self.project_id = self.project()
        self.dataset = self.imported(self.project_id, CSV)
        self.path = f"/versions/{self.dataset['versionId']}"
        self.columns = [column["id"] for column in self.dataset["columns"]]
        self.initial = self.get(f"{self.path}/checks")["items"][0]

    def test_automatic_check_configures_all_columns_and_reports_real_metrics(self):
        configuration = self.get(f"{self.path}/check-configuration")
        self.assertEqual(configuration["revision"], 1)
        self.assertEqual(configuration["columnIds"], self.columns)
        self.assertEqual(configuration["ruleCodes"], ["required", "data_type", "email_format"])
        self.assertEqual(self.initial["configurationSnapshot"],
                         {"columnIds": self.columns, "ruleCodes": configuration["ruleCodes"]})
        self.assertEqual(self.get(f"/checks/{self.initial['id']}"), self.initial)
        self.assertEqual(self.initial["status"], "succeeded")
        self.assertEqual(self.initial["checkedRowCount"], 5)
        self.assertEqual(self.initial["checkedColumnCount"], 3)
        self.assertEqual(self.initial["issueCount"], 6)
        self.assertEqual(self.initial["affectedRowCount"], 3)
        self.assertIsNone(self.initial["qualityScore"])
        self.assertIsNone(self.initial["scoreFormulaVersion"])
        summary = self.get(f"{self.path}/quality-summary")
        self.assertEqual(summary["status"], "ready")
        self.assertFalse(summary["isStale"])
        self.assertIsNone(summary["activeCheckRunId"])
        self.assertEqual(summary["lastSuccessfulCheckRunId"], self.initial["id"])
        self.assertEqual(summary["result"]["issueCount"], 6)
        self.assertEqual(self.get(f"/datasets/{self.dataset['datasetId']}/audit-events")["items"], [])

    def test_issue_endpoints_filter_and_group_without_exposing_cell_values(self):
        run = f"/checks/{self.initial['id']}"
        issues = self.get(f"{run}/issues", pageSize=2)
        self.assertEqual(issues["pagination"]["total"], 6)
        self.assertEqual(len(issues["items"]), 2)
        self.assertNotIn("value", issues["items"][0])
        narrowed = self.get(f"{run}/issues", columnId=self.columns[0], ruleCode="email_format", rowIndex=1)
        self.assertEqual(narrowed["pagination"]["total"], 1)
        self.assertEqual(narrowed["items"][0]["ruleCode"], "email_format")
        self.assertEqual(self.get(f"{run}/issues", rowIndex=999)["items"], [])

        summary = self.get(f"{run}/column-summary", pageSize=3)
        self.assertEqual(summary["pagination"]["total"], 5)
        self.assertEqual(summary["pagination"]["totalPages"], 2)
        self.assertEqual({group["ruleCode"] for group in summary["items"]}, {"required", "data_type", "email_format"})
        for group in summary["items"]:
            self.assertEqual(group["columnName"], "Email")
            self.assertEqual(group["columnId"], self.columns[0])
            self.assertEqual(group["issueCount"], group["affectedRowCount"])
            self.assertTrue(group["label"])
        note_group = self.get(f"{run}/column-summary", page=2, pageSize=3)["items"][-1]
        self.assertEqual((note_group["columnName"], note_group["issueCount"]), ("Note", 2))

    def test_problem_rows_filter_has_unique_indices_and_annotates_preserved_values(self):
        run_id = self.initial["id"]
        path = f"{self.path}/rows"
        all_rows = self.get(path, checkRunId=run_id)["items"]
        self.assertEqual(len(all_rows), 5)
        invalid = all_rows[1]["cells"][0]
        self.assertEqual(invalid["value"], "invalid")
        self.assertEqual({issue["ruleCode"] for issue in invalid["issues"]}, {"data_type", "email_format"})
        missing = all_rows[2]["cells"][0]
        self.assertEqual(missing["issues"], [{"ruleCode": "required", "message": "Пустое значение"}])
        self.assertIsNone(missing["value"])
        self.assertEqual(missing["displayValue"], "—")
        self.assertEqual(all_rows[2]["cells"][1]["value"], "broken")
        self.assertEqual(all_rows[3]["cells"][2]["value"], "   ")
        filtered = self.get(path, checkRunId=run_id, onlyProblemRows="true", pageSize=2)
        self.assertEqual(filtered["pagination"]["total"], 3)
        self.assertEqual([row["rowIndex"] for row in filtered["items"]], [1, 2])
        second = self.get(path, checkRunId=run_id, onlyProblemRows="true", pageSize=2, page=2)
        self.assertEqual([row["rowIndex"] for row in second["items"]], [3])
        email = self.get(path, checkRunId=run_id, columnId=self.columns[0])
        self.assertEqual([row["rowIndex"] for row in email["items"]], [1, 2])
        required = self.get(path, checkRunId=run_id, columnId=self.columns[0], ruleCode="required")
        self.assertEqual([row["rowIndex"] for row in required["items"]], [2])
        self.error(self.client.get(f"{API}{path}?columnId={self.columns[0]}"), 422, "VALIDATION_ERROR")
        self.error(self.client.get(f"{API}{path}?checkRunId={run_id}&ruleCode=unknown"), 422, "VALIDATION_ERROR")

    def test_update_configuration_checks_revision_and_keeps_old_result(self):
        path = f"{self.path}/check-configuration"
        for invalid, code in (([], "VALIDATION_ERROR"), ([self.columns[0]] * 2, "INVALID_COLUMN"),
                              ([str(uuid4())], "INVALID_COLUMN")):
            self.error(self.mutate("put", path, {"columnIds": invalid, "expectedRevision": 1}), 422, code)

        valid = {"columnIds": [self.columns[1]], "expectedRevision": 1}
        response = self.mutate("put", path, valid)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["revision"], 2)
        self.assertEqual(response.json()["columnIds"], [self.columns[1]])
        error = self.error(self.mutate("put", path, valid), 409, "CONFIGURATION_CONFLICT")
        self.assertEqual(error["currentRevision"], 2)
        self.assertEqual(self.get(f"{self.path}/checks")["pagination"]["total"], 1)
        summary = self.get(f"{self.path}/quality-summary")
        self.assertTrue(summary["isStale"])
        self.assertEqual(summary["selectedColumnCount"], 1)
        self.assertEqual(summary["configurationRevision"], 2)
        self.assertEqual(summary["result"]["checkRunId"], self.initial["id"])
        self.assertEqual(summary["result"]["configurationRevision"], 1)

    def test_manual_run_is_idempotent_and_uses_immutable_configuration_snapshot(self):
        config = f"{self.path}/check-configuration"
        self.assertEqual(self.mutate("put", config, {"columnIds": [self.columns[1]], "expectedRevision": 1})
                         .status_code, 200)
        path = f"{self.path}/checks"
        key = uuid4()
        self.error(self.mutate("post", path, {"configurationRevision": 1}, idem=uuid4()),
                   409, "CONFIGURATION_CONFLICT")
        response = self.mutate("post", path, {"configurationRevision": 2}, idem=key)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(self.mutate("post", path, {"configurationRevision": 2}, idem=key).json(), response.json())
        self.error(self.mutate("post", path, {"configurationRevision": 1}, idem=key), 409, "IDEMPOTENCY_CONFLICT")
        self.error(self.mutate("post", path, {"configurationRevision": 2}, idem=uuid4()), 409, "JOB_ALREADY_RUNNING")
        run_id = response.json()["checkRunId"]
        queued = self.get(f"/checks/{run_id}")
        self.assertEqual(queued["status"], "queued")
        self.assertIsNone(queued["issueCount"])
        self.assertIsNone(queued["checkedRowCount"])
        summary = self.get(f"{self.path}/quality-summary")
        self.assertEqual(summary["status"], "queued")
        self.assertEqual(summary["activeCheckRunId"], run_id)
        self.error(self.client.get(f"{API}{self.path}/rows?checkRunId={run_id}&onlyProblemRows=true"),
                   422, "VALIDATION_ERROR")
        self.assertEqual(self.mutate("put", config, {"columnIds": [self.columns[0]], "expectedRevision": 2})
                         .status_code, 200)
        self.drain()
        result = self.get(f"/checks/{run_id}")
        self.assertEqual(result["configurationSnapshot"]["columnIds"], [self.columns[1]])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["issueCount"], 1)
        self.assertEqual(result["checkedColumnCount"], 1)
        self.assertEqual(self.get(path, pageSize=1)["items"][0]["id"], run_id)
        self.assertTrue(self.get(f"{self.path}/quality-summary")["isStale"])
        self.assertEqual(QualityCheckRun.objects.count(), 2)
        self.assertEqual(self.get(f"/checks/{self.initial['id']}"), self.initial)

    def test_failed_run_keeps_previous_success_and_retry_checks_same_run(self):
        response = self.mutate("post", f"{self.path}/checks", {"configurationRevision": 1}, idem=uuid4())
        self.assertEqual(response.status_code, 202, response.content)
        run_id, job_id = response.json()["checkRunId"], response.json()["jobId"]
        with patch.dict(PROCESSORS, {Job.Kind.CHECK: fail_check}):
            self.assertTrue(process_next_job())
        summary = self.get(f"{self.path}/quality-summary")
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["latestAttemptId"], run_id)
        self.assertEqual(summary["result"]["checkRunId"], self.initial["id"])
        self.assertIsNone(self.get(f"/checks/{run_id}")["issueCount"])
        self.assertEqual(self.get(f"/checks/{run_id}/issues")["items"], [])
        self.assertEqual(self.get(f"/checks/{run_id}/column-summary")["items"], [])
        attempt = self.mutate("post", f"/jobs/{job_id}/retry", idem=uuid4())
        self.assertEqual(attempt.status_code, 202, attempt.content)
        self.assertEqual(attempt.json()["resourceId"], run_id)
        self.assertEqual(attempt.json()["resourceType"], "quality_check")
        self.drain()
        self.assertEqual(self.get(f"/checks/{run_id}")["currentJobId"], attempt.json()["jobId"])
        self.assertEqual(self.get(f"/checks/{run_id}")["status"], "succeeded")
        self.assertEqual(self.get(f"/jobs/{attempt.json()['jobId']}")["attempt"], 2)

    def test_queued_initial_check_does_not_show_fake_metrics(self):
        response = self.upload(self.project_id)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertTrue(process_next_job())
        dataset = self.get(f"/datasets/{response.json()['datasetId']}")
        path = f"/versions/{dataset['originalVersionId']}/quality-summary"
        summary = self.get(path)
        self.assertEqual(summary["status"], "queued")
        self.assertIsNone(summary["result"])
        self.assertIsNone(summary["lastSuccessfulCheckRunId"])
        self.drain()
        self.assertEqual(self.get(path)["result"]["issueCount"], 0)
