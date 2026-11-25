from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from cleanser.worker import process_next_job

API = "/api/v1"
PASSWORD = "Correct-Jubilee-19!"
OTHER_PASSWORD = "Second-Glacier-41!"


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class EndpointTestCase(APITestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient(enforce_csrf_checks=True)
        files = TemporaryDirectory(prefix="datasets-cleanser-test-")
        self.addCleanup(files.cleanup)
        storage = override_settings(PRIVATE_FILE_ROOT=Path(files.name))
        storage.enable()
        self.addCleanup(storage.disable)

    def csrf(self, client=None, **headers):
        client = client if client is not None else self.client
        response = client.get(f"{API}/auth/csrf", **headers)
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

    def project(self, name="Проект", client=None):
        response = self.mutate("post", "/projects", {"name": name}, client=client)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["id"]

    def upload(self, project_id, csv=b"Name,Email\nAnn,ann@example.com\n", *, name="Таблица", idem=True,
               client=None, filename="test.csv", media_type="text/csv", **fields):
        client = client if client is not None else self.client
        headers = {"HTTP_X_CSRFTOKEN": self.csrf(client)}
        if idem:
            headers["HTTP_IDEMPOTENCY_KEY"] = str(uuid4() if idem is True else idem)
        return client.post(f"{API}/projects/{project_id}/datasets", {
            "name": name, "file": SimpleUploadedFile(filename, csv, content_type=media_type), **fields,
        }, format="multipart", **headers)

    def imported(self, project_id, csv=b"Name,Email\nAnn,ann@example.com\n", *, client=None, **fields):
        client = client if client is not None else self.client
        response = self.upload(project_id, csv, client=client, **fields)
        self.assertEqual(response.status_code, 202, response.content)
        self.drain()
        result = response.json()
        dataset = self.get(f"/datasets/{result['datasetId']}", client=client)
        self.assertEqual(dataset["status"], "ready", dataset)
        result["versionId"] = dataset["originalVersionId"]
        result["columns"] = self.get(f"/versions/{result['versionId']}", client=client)["columns"]
        return result

    def drain(self):
        for _ in range(20):
            if not process_next_job():
                return
        self.fail("Worker did not empty the queue.")

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
