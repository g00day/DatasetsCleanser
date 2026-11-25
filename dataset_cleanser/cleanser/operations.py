import hashlib
import json
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from auth_app.models import Account, identity_key

from .catalog import ACTIONS, ORIGINAL_VERSION_NAME, PSEUDONYM_STRATEGIES, RULES, RULESET_VERSION
from .http import APIError, StrictSerializer, TextField
from .models import (
    ACTIVE_STATUSES, CheckConfiguration, CleaningOperation, CleaningRun, Dataset, DatasetVersion,
    IdempotencyRecord, Job, QualityCheckRun, Status,
)

RESOURCE_TYPES = {Job.Kind.IMPORT: "dataset", Job.Kind.CHECK: "quality_check", Job.Kind.CLEANING: "cleaning"}


class ActionInput(StrictSerializer):
    code = TextField(max_length=48)
    parameters = serializers.DictField(required=False, default=dict)


class ColumnActionInput(ActionInput):
    columnId = serializers.UUIDField()


class CleaningInput(StrictSerializer):
    sourceVersionId = serializers.UUIDField()
    expectedLatestVersionId = serializers.UUIDField()
    versionName = TextField(max_length=80)
    datasetActions = ActionInput(many=True, required=False, default=list, max_length=2)
    columnActions = ColumnActionInput(many=True, required=False, default=list, max_length=256)


def assert_capacity(user):
    if Job.objects.filter(owner=user, status__in=ACTIVE_STATUSES).count() >= settings.MAX_ACTIVE_JOBS_PER_OWNER:
        raise APIError(429, "RATE_LIMITED", "Достигнут лимит активных заданий.", wait=5)


def configuration_conflict(revision):
    raise APIError(409, "CONFIGURATION_CONFLICT", "Настройки проверки уже изменились.",
                   extra={"currentRevision": revision})


def invalid_column():
    raise APIError(422, "INVALID_COLUMN", "Столбец не принадлежит указанной версии или повторяется.")


def idempotent_operation(request, content, create_job):
    try:
        key = UUID(request.headers.get("Idempotency-Key", ""))
    except ValueError:
        raise APIError(422, fields={"Idempotency-Key": ["Передайте UUID операции."]}) from None
    raw = json.dumps(content, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    request_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    route = request.path_info
    with transaction.atomic():
        # Serialize submissions per owner. The response and SQL-backed queue commit together.
        user = Account.objects.select_for_update().get(pk=request.user.pk)
        now = timezone.now()
        records = IdempotencyRecord.objects.filter(user=user, route=route, key=key)
        record = records.select_related("job").first()
        if record is not None and record.expires_at > now:
            if record.request_hash != request_hash:
                raise APIError(409, "IDEMPOTENCY_CONFLICT", "Этот ключ использован с другим запросом.")
            return record.job, record.response_status
        if record is not None:
            record.delete()
        job = create_job(user)
        IdempotencyRecord.objects.create(
            user=user, route=route, key=key, request_hash=request_hash, resource_type=RESOURCE_TYPES[job.kind],
            resource_id=job.resource_id, job=job,
            expires_at=now + timedelta(seconds=settings.IDEMPOTENCY_TTL_SECONDS),
        )
    return job, 202


def new_job(owner_id, dataset_id, kind, resource_id, previous=None):
    return Job.objects.create(owner_id=owner_id, dataset_id=dataset_id, kind=kind, resource_id=resource_id,
                              attempt=previous.attempt + 1 if previous else 1, retry_of_job=previous)


def create_check(version, configuration, owner_id):
    run = QualityCheckRun.objects.create(
        version=version, configuration_revision=configuration.revision,
        configuration_snapshot={
            "columnIds": [str(column_id) for column_id in configuration.columns.order_by("position", "id")
                          .values_list("id", flat=True)],
            "ruleCodes": list(configuration.rule_codes),
        },
        ruleset_version=RULESET_VERSION,
    )
    run.current_job = new_job(owner_id, version.dataset_id, Job.Kind.CHECK, run.id)
    run.save(update_fields=["current_job"])
    return run


def initialize_configuration(version, columns):
    configuration = CheckConfiguration.objects.create(version=version, rule_codes=list(RULES))
    configuration.columns.set(columns)
    return configuration


def validate_operations(source, data):
    columns = {column.id: column for column in source.columns.order_by("position", "id")}
    dataset_actions = data["datasetActions"]
    column_actions = data["columnActions"]
    if not dataset_actions and not column_actions:
        raise APIError(422, fields={"datasetActions": ["План очистки не может быть пустым."]})

    operations = []
    seen = set()
    for scope, actions in (("dataset", dataset_actions), ("column", column_actions)):
        for item in actions:
            code = item["code"]
            definition = ACTIONS.get(code)
            if not definition or definition["scope"] != scope:
                raise APIError(422, "UNSUPPORTED_ACTION", "Действие недоступно для указанной области.")
            key = item.get("columnId", code)
            if key in seen:
                if scope == "column":
                    invalid_column()
                raise APIError(422, "UNSUPPORTED_ACTION", "Действие на датасете указано несколько раз.")
            seen.add(key)
            column = columns.get(key)
            if scope == "column" and column is None:
                invalid_column()
            if column and column.data_type not in definition["applicableDataTypes"]:
                raise APIError(422, "UNSUPPORTED_ACTION", "Действие недоступно для типа столбца.")

            parameters = item["parameters"]
            properties = definition["parametersSchema"]["properties"]
            if set(parameters) - properties.keys():
                raise APIError(422, "UNSUPPORTED_ACTION", "Переданы неизвестные параметры действия.")
            normalized = {}
            for name, spec in properties.items():
                choices = spec["enum"]
                if code == "pseudonymize":
                    choices = [PSEUDONYM_STRATEGIES[column.data_type]]
                value = parameters.get(name, choices[0])
                if value not in choices:
                    raise APIError(422, "UNSUPPORTED_ACTION", "Недопустимые параметры действия.")
                normalized[name] = value
            operations.append((code, column, normalized, definition))

    operations.sort(key=lambda item: (item[3]["executionOrder"], item[1].position if item[1] else 0))
    return operations


def assert_name_available(dataset, key, *, exclude_version=None):
    versions = DatasetVersion.objects.filter(dataset=dataset, name_key=key).exclude(pk=exclude_version)
    reserved = CleaningRun.objects.filter(dataset=dataset, requested_name_key=key, status__in=ACTIVE_STATUSES)
    if key == identity_key(ORIGINAL_VERSION_NAME) or versions.exists() or reserved.exists():
        raise APIError(409, "VERSION_NAME_TAKEN", "Имя версии уже занято или зарезервировано.")


def assert_dataset_writable(dataset):
    if dataset.status != Dataset.State.READY or dataset.cleanings.filter(status__in=ACTIVE_STATUSES).exists():
        raise APIError(409, "DATASET_BUSY", "Датасет недоступен для очистки.")


def assert_latest_version(dataset, expected):
    if dataset.latest_version_id != expected:
        raise APIError(409, "STALE_BASE_VERSION", "Доступна более новая версия датасета.")


def create_cleaning(dataset, owner, source, data):
    key = identity_key(data["versionName"])
    assert_dataset_writable(dataset)
    assert_latest_version(dataset, data["expectedLatestVersionId"])
    assert_name_available(dataset, key)
    operations = validate_operations(source, data)
    assert_capacity(owner)

    snapshot = {"datasetActions": [], "columnActions": []}
    for code, column, parameters, definition in operations:
        item = {"code": code, "parameters": parameters, "version": definition["version"]}
        if column:
            snapshot["columnActions"].append({"columnId": str(column.pk), **item})
        else:
            snapshot["datasetActions"].append(item)
    run = CleaningRun.objects.create(
        dataset=dataset, source_version=source, expected_latest_version_id=data["expectedLatestVersionId"],
        requested_version_name=data["versionName"], requested_name_key=key, plan_snapshot=snapshot,
        created_by=owner,
    )
    CleaningOperation.objects.bulk_create([
        CleaningOperation(cleaning_run=run, order=index, scope=definition["scope"], column=column,
                          action_code=code, parameters=parameters)
        for index, (code, column, parameters, definition) in enumerate(operations)
    ])
    run.current_job = new_job(owner.pk, dataset.pk, Job.Kind.CLEANING, run.pk)
    run.save(update_fields=["current_job"])
    return run.current_job


def job_resource(job, dataset):
    if job.kind == Job.Kind.IMPORT:
        return dataset
    if job.kind == Job.Kind.CHECK:
        return QualityCheckRun.objects.get(pk=job.resource_id, version__dataset=dataset)
    return CleaningRun.objects.get(pk=job.resource_id, dataset=dataset)


def retry_job(job, owner):
    dataset = Dataset.objects.select_for_update().get(pk=job.dataset_id, project__owner=owner)
    job = Job.objects.get(pk=job.pk)
    resource = job_resource(job, dataset)
    is_import = job.kind == Job.Kind.IMPORT
    current_id = resource.import_job_id if is_import else resource.current_job_id
    if Job.objects.filter(pk=current_id, status__in=ACTIVE_STATUSES).exists():
        raise APIError(409, "JOB_ALREADY_RUNNING", "Попытка уже выполняется или ожидает выполнения.")
    if current_id != job.pk or job.status != Status.FAILED or not job.retryable:
        raise APIError(409, "JOB_NOT_RETRYABLE", "Эту попытку нельзя повторить.")
    if job.kind == Job.Kind.CLEANING:
        assert_dataset_writable(dataset)
        assert_latest_version(dataset, resource.expected_latest_version_id)
        assert_name_available(dataset, resource.requested_name_key)
    if job.kind == Job.Kind.CHECK and resource.version.checks.filter(status__in=ACTIVE_STATUSES).exists():
        raise APIError(409, "JOB_ALREADY_RUNNING", "У этой версии уже есть активная проверка.")
    assert_capacity(owner)
    attempt = new_job(owner.pk, dataset.pk, job.kind, job.resource_id, previous=job)
    if is_import:
        resource.import_job = attempt
        resource.status = Dataset.State.IMPORTING
        resource.save(update_fields=["import_job", "status", "updated_at"])
    else:
        resource.current_job = attempt
        resource.status = Status.QUEUED
        resource.started_at = resource.finished_at = None
        resource.save(update_fields=["current_job", "status", "started_at", "finished_at"])
    return attempt
