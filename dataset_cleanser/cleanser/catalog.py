from django.conf import settings
from rest_framework.response import Response

from auth_app.api import PublicAuthView

from .http import query
from .models import DataType

RULESET_VERSION = 1
ORIGINAL_VERSION_NAME = "Исходный файл"
DELIMITERS = ("auto", ",", ";")
ENCODINGS = ("utf-8", "utf-8-sig")
EXPORT_ENCODING = "utf-8"
EXPORT_DELIMITER = ","

RULES = {
    "required": {
        "label": "Пустое значение", "applicableDataTypes": DataType.values,
        "parametersSchema": {"type": "object", "additionalProperties": False}, "version": 1,
    },
    "data_type": {
        "label": "Несоответствие типу", "applicableDataTypes": DataType.values,
        "parametersSchema": {"type": "object", "additionalProperties": False}, "version": 1,
    },
    "email_format": {
        "label": "Неверный формат email", "applicableDataTypes": [DataType.EMAIL],
        "parametersSchema": {"type": "object", "additionalProperties": False}, "version": 1,
    },
}


def parameters_schema(**properties):
    return {
        "type": "object", "additionalProperties": False, "required": list(properties),
        "properties": {name: {"type": "string", "enum": values} for name, values in properties.items()},
    }


def cleaning_action(label, scope, types, schema, order):
    return {"label": label, "scope": scope, "applicableDataTypes": types, "parametersSchema": schema,
            "version": 1, "changesRowCount": scope == "dataset", "changesValues": scope == "column",
            "executionOrder": order}


TEXT_TYPES = [DataType.STRING, DataType.EMAIL]
ACTIONS = {
    "drop_rows_with_missing": cleaning_action(
        "Удалить строки с пропусками", "dataset", [],
        parameters_schema(columnScope=["all"], match=["any"]), 1,
    ),
    "drop_duplicate_rows": cleaning_action(
        "Удалить дубликаты строк", "dataset", [], parameters_schema(keep=["first"]), 2,
    ),
    "trim": cleaning_action("Убрать крайние пробелы", "column", TEXT_TYPES, parameters_schema(), 3),
    "lowercase": cleaning_action("Привести к нижнему регистру", "column", TEXT_TYPES, parameters_schema(), 3),
    "pseudonymize": cleaning_action(
        "Псевдонимизировать", "column", TEXT_TYPES, parameters_schema(strategy=["email_token", "text_token"]), 3,
    ),
}
PSEUDONYM_STRATEGIES = {DataType.EMAIL: "email_token", DataType.STRING: "text_token"}


class CapabilitiesView(PublicAuthView):
    def get(self, request):
        query(request)
        return Response({
            "files": {
                "formats": ["csv"], "extensions": [".csv"], "encodings": ENCODINGS, "delimiters": DELIMITERS,
                "maxFileBytes": settings.MAX_FILE_BYTES, "maxColumns": settings.MAX_CSV_COLUMNS,
                "maxFieldCharacters": settings.MAX_CSV_FIELD_CHARS, "maxRows": settings.MAX_CSV_ROWS,
                "maxCells": settings.MAX_CSV_CELLS, "parseTimeoutSeconds": settings.CSV_PARSE_TIMEOUT_SECONDS,
                "maxPreviewCharacters": settings.CELL_PREVIEW_CHARS,
                "maxStorageBytesPerUser": settings.MAX_OWNER_STORAGE_BYTES,
                "csv": {
                    "autoDelimiter": "Проверяет запятую и точку с запятой. Предпочитает корректную схему "
                                     "с большим числом столбцов. При равенстве выбирает запятую.",
                    "headerRequired": True, "dataRowsRequired": True, "allowUtf8Bom": True,
                    "quoting": "Поля в двойных кавычках могут содержать переносы строк. "
                               "Внутренняя кавычка удваивается. Пустая физическая запись недопустима.",
                    "missingValues": "Пустые поля становятся null. Проверка required также считает пустыми "
                                     "значения только из пробельных символов.",
                    "export": {"delimiter": EXPORT_DELIMITER, "encoding": EXPORT_ENCODING,
                               "lineEnding": "LF", "nullRepresentation": ""},
                },
            },
            "passwordPolicy": {
                "minLength": settings.PASSWORD_MIN_LENGTH, "maxLength": settings.PASSWORD_MAX_LENGTH,
                "disallowCommonPasswords": True, "disallowEntirelyNumeric": True,
                "disallowSimilarityToAccount": True,
            },
            "session": {"idleTimeoutSeconds": settings.API_SESSION_IDLE_SECONDS,
                        "maxLifetimeSeconds": settings.API_SESSION_MAX_SECONDS,
                        "resetTokenLifetimeSeconds": settings.API_RESET_TOKEN_SECONDS,
                        "csrfHeader": "X-CSRFToken"},
            "pagination": {"defaultPageSize": 10, "maxPageSize": 100, "suggestedPageSizes": [10, 25, 50]},
            "idempotency": {"header": "Idempotency-Key", "ttlSeconds": settings.IDEMPOTENCY_TTL_SECONDS},
            "jobs": {"maxActivePerUser": settings.MAX_ACTIVE_JOBS_PER_OWNER,
                     "timeoutSeconds": settings.JOB_TIMEOUT_SECONDS},
            "qualityRules": [{"code": code, **item} for code, item in RULES.items()],
            "rulesetVersion": RULESET_VERSION,
            "typeInference": {
                "method": "Строгое большинство непустых значений. В неоднозначных случаях используется string.",
                "trimForValidation": True,
                "priority": ["email", "boolean", "integer", "decimal", "date", "datetime"],
                "emailHeaders": ["email", "e-mail", "e_mail", "электронная почта"],
                "integer": "Цифры ASCII с необязательным знаком.",
                "decimal": "Десятичная точка, необязательный знак и необязательная экспонента.",
                "boolean": "true/false без учёта регистра.",
                "date": "ISO 8601 YYYY-MM-DD.",
                "datetime": "ISO 8601 с датой, T и как минимум часами и минутами. Часовой пояс необязателен.",
                "email": "Валидация синтаксиса адреса средствами Django.",
            },
            "cleaningActions": [
                {"code": code, **item, **({"strategiesByDataType": PSEUDONYM_STRATEGIES}
                                         if code == "pseudonymize" else {})}
                for code, item in ACTIONS.items()
            ],
        })
