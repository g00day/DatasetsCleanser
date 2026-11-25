from copy import copy
from uuid import uuid4

from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler
from django.http import HttpResponse
from django.utils.cache import patch_vary_headers
from rest_framework.authentication import CSRFCheck

from cleanser.http import APIError, json_error

API_METHODS = {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH"}
API_HEADERS = {"accept", "content-type", "idempotency-key", "x-csrftoken"}


class BoundedUpload(FileUploadHandler):
    def receive_data_chunk(self, raw_data, start):
        if start + len(raw_data) > settings.MAX_FILE_BYTES:
            raise APIError(413)
        return raw_data

    def file_complete(self, file_size):
        return None


class APIRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def is_api(request):
        return request.path_info == "/api/v1" or request.path_info.startswith("/api/v1/")

    def __call__(self, request):
        if not self.is_api(request):
            return self.get_response(request)
        request.request_id = str(uuid4())
        request.sensitive_post_parameters = "__ALL__"
        origin = request.headers.get("Origin")
        allow_origin = origin in settings.API_CORS_ORIGINS and origin != "*"
        requested_method = request.headers.get("Access-Control-Request-Method")
        if request.method == "OPTIONS" and requested_method:
            response = self.preflight(request, requested_method, allow_origin)
        else:
            response = self.get_response(request)
        if response.status_code >= 400 and not response.get("Content-Type", "").startswith("application/json"):
            response = json_error(request, response.status_code)
        if settings.API_CORS_ORIGINS:
            patch_vary_headers(response, ("Origin",))
        if allow_origin:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Expose-Headers"] = "Content-Disposition, Location, Retry-After, X-Request-ID"
        response["X-Request-ID"] = request.request_id
        response["Cache-Control"] = "private, no-store"
        return response

    @staticmethod
    def preflight(request, requested_method, allow_origin):
        requested_headers = {name.strip().lower() for name in
                             request.headers.get("Access-Control-Request-Headers", "").split(",") if name.strip()}
        if not allow_origin or requested_method not in API_METHODS or not requested_headers <= API_HEADERS:
            return json_error(request, 403)
        return HttpResponse(status=204, headers={
            "Access-Control-Allow-Methods": ", ".join(sorted(API_METHODS)),
            "Access-Control-Allow-Headers": ", ".join(sorted(API_HEADERS)),
        })

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not self.is_api(request) or request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
            return None
        if request.content_type == "multipart/form-data":
            request.upload_handlers.insert(0, BoundedUpload(request))

        csrf_check = CSRFCheck(lambda req: None)
        csrf_check.process_request(request)

        # The API uses X-CSRFToken. Django also checks Origin/Referer through its normal policy.
        # A body-free request keeps untrusted multipart parsing inside the authenticated DRF view.
        csrf_request = copy(request)
        csrf_request._post = {}
        csrf_request._files = {}
        if csrf_check.process_view(csrf_request, lambda req: None, (), {}):
            return json_error(request, 403, "CSRF_FAILED", "Проверка CSRF не пройдена.")
        request.csrf_processing_done = True
        return None
