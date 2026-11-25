import logging
import re
from uuid import UUID

from django.core.exceptions import SuspiciousOperation
from django.core.paginator import Paginator
from django.db import OperationalError
from django.http import JsonResponse
from rest_framework import exceptions, serializers
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)

DEFAULT_ERRORS = {
    400: ("MALFORMED_REQUEST", "Не удалось разобрать запрос."),
    401: ("UNAUTHENTICATED", "Войдите в систему."),
    403: ("FORBIDDEN", "Операция запрещена."),
    404: ("NOT_FOUND", "Ресурс не найден."),
    405: ("METHOD_NOT_ALLOWED", "Метод не поддерживается."),
    406: ("NOT_ACCEPTABLE", "Формат ответа не поддерживается."),
    413: ("FILE_TOO_LARGE", "Файл превышает допустимый размер."),
    415: ("UNSUPPORTED_FILE_TYPE", "Формат запроса не поддерживается."),
    422: ("VALIDATION_ERROR", "Проверьте заполнение полей."),
    429: ("RATE_LIMITED", "Превышен лимит запросов."),
    500: ("INTERNAL_ERROR", "Внутренняя ошибка сервера."),
    503: ("SERVICE_UNAVAILABLE", "Сервис временно недоступен."),
}


class APIError(exceptions.APIException):
    def __init__(self, status_code, code=None, message=None, *, fields=None, extra=None, wait=None):
        default_code, default_message = DEFAULT_ERRORS.get(status_code, ("CONFLICT", "Конфликт состояния."))
        self.status_code = status_code
        self.code = code or default_code
        self.message = message or default_message
        self.fields = fields
        self.extra = extra or {}
        self.wait = wait
        super().__init__(self.message, self.code)


def error_body(request, code, message, fields=None, extra=None):
    error = {"code": code, "message": message, "requestId": request.request_id}
    if fields:
        error["fields"] = fields
    return {"error": {**error, **(extra or {})}}


def json_error(request, status, code=None, message=None):
    default_code, default_message = DEFAULT_ERRORS.get(status, DEFAULT_ERRORS[500])
    return JsonResponse(error_body(request, code or default_code, message or default_message), status=status)


def exception_handler(exc, context):
    request = context["request"]
    if isinstance(exc, APIError):
        response = drf_exception_handler(exc, context)
        response.data = error_body(request, exc.code, exc.message, exc.fields, exc.extra)
        return response
    if isinstance(exc, exceptions.ValidationError):
        code, message = DEFAULT_ERRORS[422]
        fields = exc.detail if isinstance(exc.detail, dict) else {"nonFieldErrors": exc.detail}
        return Response(error_body(request, code, message, fields), status=422)
    if isinstance(exc, SuspiciousOperation):
        code, message = DEFAULT_ERRORS[400]
        return Response(error_body(request, code, message), status=400)
    if isinstance(exc, OperationalError):
        logger.warning("API database unavailable request_id=%s", request.request_id)
        code, message = DEFAULT_ERRORS[503]
        return Response(error_body(request, code, message), status=503)

    response = drf_exception_handler(exc, context)
    if response is None:
        # Exception text can contain customer data. Keep only an operational identifier.
        logger.error("Unhandled API error request_id=%s exception=%s", request.request_id, type(exc).__name__)
        code, message = DEFAULT_ERRORS[500]
        return Response(error_body(request, code, message), status=500)
    code, message = DEFAULT_ERRORS.get(response.status_code, DEFAULT_ERRORS[500])
    response.data = error_body(request, code, message)
    return response


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if hasattr(data, "keys"):
            unknown = set(data) - self.fields.keys()
            if unknown:
                raise serializers.ValidationError({key: ["Неизвестное поле."] for key in sorted(unknown)})
            if hasattr(data, "getlist"):
                repeated = [key for key in data if len(data.getlist(key)) != 1]
                if repeated:
                    raise serializers.ValidationError({key: ["Поле передано несколько раз."] for key in repeated})
        return super().to_internal_value(data)


class TextField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class EmailField(serializers.EmailField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


def body(request, serializer=StrictSerializer):
    validated = serializer(data=request.data)
    validated.is_valid(raise_exception=True)
    return validated.validated_data


def query(request, *allowed, paginated=False):
    allowed = set(allowed)
    if paginated:
        allowed.update(("page", "pageSize"))
    fields = {}
    for key, values in request.query_params.lists():
        if key not in allowed:
            fields[key] = ["Неизвестный параметр."]
        elif len(values) != 1:
            if key in {"page", "pageSize"}:
                raise APIError(400, "INVALID_PAGINATION", "Некорректные параметры пагинации.")
            fields[key] = ["Параметр передан несколько раз."]
    if fields:
        raise APIError(422, fields=fields)
    return request.query_params


def integer_param(value, name, *, minimum=0, maximum=2_147_483_647):
    if value is not None and re.fullmatch(r"[0-9]+", value):
        try:
            number = int(value)
        except ValueError:
            pass
        else:
            if minimum <= number and (maximum is None or number <= maximum):
                return number
    raise APIError(422, fields={name: ["Укажите допустимое целое число."]})


def uuid_param(value, name, *, code=None, status=422):
    try:
        return UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise APIError(status, code, fields={name: ["Укажите корректный UUID."]}) from None


def boolean_param(params, name, default=False):
    value = params.get(name)
    if value is None:
        return default
    if value in {"true", "false"}:
        return value == "true"
    raise APIError(422, fields={name: ["Допустимы true и false."]})


def choice_param(params, name, choices, default=None):
    value = params.get(name, default)
    if value is not None and value not in choices:
        raise APIError(422, fields={name: ["Недопустимое значение."]})
    return value


def page(qs, params):
    try:
        page_number = integer_param(params.get("page", "1"), "page", minimum=1, maximum=None)
        page_size = integer_param(params.get("pageSize", "10"), "pageSize", minimum=1, maximum=100)
    except APIError as exc:
        raise APIError(400, "INVALID_PAGINATION", "Некорректные параметры пагинации.",
                       fields=exc.fields) from None
    paginator = Paginator(qs, page_size, allow_empty_first_page=False)
    items = list(paginator.page(page_number).object_list) if page_number <= paginator.num_pages else []
    return items, {"page": page_number, "pageSize": page_size, "total": paginator.count,
                   "totalPages": paginator.num_pages}


def paginated(qs, params, dto):
    items, pagination = page(qs, params)
    return Response({"items": [dto(item) for item in items], "pagination": pagination})
