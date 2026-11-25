from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from auth_app.models import identity_key

from .catalog import DELIMITERS, ENCODINGS, RULES
from .csv_data import is_missing
from .dto import (
    audit_dto, check_dto, check_metrics, cleaning_dto, column_dto, configuration_dto, dataset_detail,
    dataset_summary, issue_dto, job_dto, project_detail, project_summary, row_column_dto, upload_dto,
    version_dto,
)
from .files import StorageQuotaExceeded, download_name, stage_file, stage_upload, stored_path
from .http import (
    APIError, StrictSerializer, TextField, body, boolean_param, choice_param, integer_param, page, paginated,
    query, uuid_param,
)
from .models import (
    ACTIVE_STATUSES, AuditEvent, CheckConfiguration, CleaningRun, Dataset, DatasetVersion, Job, Project,
    QualityCheckRun, Status, StoredFile, VersionColumn,
)
from .operations import (
    RESOURCE_TYPES, CleaningInput, assert_capacity, assert_name_available, configuration_conflict, create_check,
    create_cleaning, idempotent_operation, invalid_column, new_job, retry_job,
)

NEWEST = ("-created_at", "-id")
UPLOAD_ORDER = ("-uploaded_at", "-id")


class NameInput(StrictSerializer):
    name = TextField(max_length=80)


class ProjectInput(NameInput):
    description = TextField(max_length=1000, allow_blank=True, required=False, trim_whitespace=False)


class ProjectPatch(ProjectInput):
    name = TextField(max_length=80, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Укажите хотя бы одно поле.")
        return attrs


class UploadInput(NameInput):
    file = serializers.FileField(allow_empty_file=True)
    delimiter = serializers.ChoiceField(choices=DELIMITERS, default="auto")
    encoding = serializers.ChoiceField(choices=ENCODINGS, default="utf-8")


class ConfigurationInput(StrictSerializer):
    columnIds = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=256)
    expectedRevision = serializers.IntegerField(min_value=1, max_value=2_147_483_647)


class CheckInput(StrictSerializer):
    configurationRevision = serializers.IntegerField(min_value=1, max_value=2_147_483_647)


def owned_project(user, project_id):
    return get_object_or_404(Project.objects.filter(owner=user), pk=project_id)


def datasets(user):
    return Dataset.objects.filter(project__owner=user)


def owned_dataset(user, dataset_id):
    return get_object_or_404(datasets(user).select_related("project", "original_file"), pk=dataset_id)


def owned_version(user, version_id):
    return get_object_or_404(DatasetVersion.objects.filter(dataset__project__owner=user), pk=version_id)


def owned_check(user, check_id):
    return get_object_or_404(QualityCheckRun.objects.filter(version__dataset__project__owner=user), pk=check_id)


def owned_job(user, job_id):
    return get_object_or_404(Job.objects.filter(owner=user, dataset__project__owner=user), pk=job_id)


class DashboardView(APIView):
    def get(self, request):
        query(request)
        return Response({"projectCount": Project.objects.filter(owner=request.user).count(),
                         "datasetCount": datasets(request.user).count()})


class UploadsView(APIView):
    def get(self, request):
        params = query(request, "projectId", paginated=True)
        uploads = datasets(request.user)
        if "projectId" in params:
            project = owned_project(request.user, uuid_param(params["projectId"], "projectId"))
            uploads = uploads.filter(project=project)
        return paginated(uploads.select_related("original_file", "project").order_by(*UPLOAD_ORDER), params, upload_dto)


class ProjectsView(APIView):
    def get(self, request):
        params = query(request, "search", "sort", paginated=True)
        choice_param(params, "sort", {"createdAt:desc"})
        projects = Project.objects.filter(owner=request.user)
        if search := params.get("search", "").strip():
            projects = projects.filter(name__icontains=search)
        return paginated(projects.annotate(dataset_count=Count("datasets")).order_by(*NEWEST), params, project_summary)

    def post(self, request):
        query(request)
        project = Project.objects.create(owner=request.user, **body(request, ProjectInput))
        project.dataset_count = 0
        return Response(project_detail(project), status=201, headers={"Location": f"/api/v1/projects/{project.id}"})


class ProjectView(APIView):
    def get(self, request, project_id):
        query(request)
        project = get_object_or_404(Project.objects.filter(owner=request.user).annotate(dataset_count=Count("datasets")),
                                    pk=project_id)
        return Response(project_detail(project))

    def patch(self, request, project_id):
        query(request)
        project = owned_project(request.user, project_id)
        changes = body(request, ProjectPatch)
        for field, value in changes.items():
            setattr(project, field, value)
        project.save(update_fields=[*changes, "updated_at"])
        project.dataset_count = project.datasets.count()
        return Response(project_detail(project))


class ProjectDatasetsView(APIView):
    parser_classes = [MultiPartParser]

    def get(self, request, project_id):
        params = query(request, "search", "includeSchema", paginated=True)
        project = owned_project(request.user, project_id)
        include_schema = boolean_param(params, "includeSchema")
        results = project.datasets.select_related("latest_version")
        if search := params.get("search", "").strip():
            results = results.filter(name__icontains=search)
        if include_schema:
            results = results.prefetch_related(
                Prefetch("latest_version__columns", queryset=VersionColumn.objects.order_by("position", "id")),
            )
        return paginated(results.order_by(*UPLOAD_ORDER), params, lambda item: dataset_summary(item, include_schema))

    def post(self, request, project_id):
        query(request)
        project = owned_project(request.user, project_id)
        if request._request.content_type != "multipart/form-data":
            raise APIError(415)
        data = body(request, UploadInput)
        with stage_file() as staged:
            filename = stage_upload(data.pop("file"), staged)
            content = {**data, "sha256": staged.sha256, "nameOnUpload": filename}

            def submit(owner):
                assert_capacity(owner)
                try:
                    file = staged.publish(owner.id, StoredFile.Kind.SOURCE, filename)
                except StorageQuotaExceeded:
                    raise APIError(413, "STORAGE_QUOTA_EXCEEDED", "Достигнут лимит места.") from None
                dataset = Dataset.objects.create(project=project, original_file=file, **data)
                dataset.import_job = new_job(owner.id, dataset.id, Job.Kind.IMPORT, dataset.id)
                dataset.save(update_fields=["import_job"])
                return dataset.import_job

            job, status = idempotent_operation(request, content, submit)
        return Response({"datasetId": job.resource_id, "jobId": job.id}, status=status,
                        headers={"Location": f"/api/v1/jobs/{job.id}"})


class DatasetView(APIView):
    def get(self, request, dataset_id):
        query(request)
        return Response(dataset_detail(owned_dataset(request.user, dataset_id)))

    def patch(self, request, dataset_id):
        query(request)
        dataset = owned_dataset(request.user, dataset_id)
        dataset.name = body(request, NameInput)["name"]
        dataset.save(update_fields=["name", "updated_at"])
        return Response(dataset_detail(dataset))


class VersionsView(APIView):
    def get(self, request, dataset_id):
        params = query(request, "sort", paginated=True)
        choice_param(params, "sort", {"number:desc"})
        dataset = owned_dataset(request.user, dataset_id)
        return paginated(dataset.versions.order_by("-number", "-id"), params, version_dto)


class VersionView(APIView):
    def get(self, request, version_id):
        query(request)
        version = owned_version(request.user, version_id)
        return Response({**version_dto(version), "columns": [
            column_dto(column) for column in version.columns.order_by("position", "id")
        ]})

    def patch(self, request, version_id):
        query(request)
        version = owned_version(request.user, version_id)
        if version.kind == DatasetVersion.Kind.ORIGINAL:
            raise APIError(422, "ORIGINAL_VERSION_IMMUTABLE", "Исходную версию нельзя переименовать.")
        name = body(request, NameInput)["name"]
        key = identity_key(name)
        with transaction.atomic():
            dataset = Dataset.objects.select_for_update().get(pk=version.dataset_id)
            version = dataset.versions.get(pk=version.pk)
            assert_name_available(dataset, key, exclude_version=version.pk)
            if version.name != name:
                old_name = version.name
                version.name, version.name_key = name, key
                version.save(update_fields=["name", "name_key", "updated_at"])
                AuditEvent.objects.create(
                    project_id=dataset.project_id, dataset=dataset, actor=request.user, source_version=version,
                    result_version=version, type=AuditEvent.Type.RENAME, summary="Версия переименована",
                    details={"oldName": old_name, "newName": name},
                )
        return Response(version_dto(version))


def filter_issues(run, params):
    issues = run.issues.all()
    if "columnId" in params:
        column = uuid_param(params["columnId"], "columnId", code="INVALID_COLUMN")
        if not run.version.columns.filter(pk=column).exists():
            invalid_column()
        issues = issues.filter(column_id=column)
    if "ruleCode" in params:
        issues = issues.filter(rule_code=choice_param(params, "ruleCode", RULES))
    if "rowIndex" in params:
        issues = issues.filter(row_index=integer_param(params["rowIndex"], "rowIndex"))
    return issues


def cell_preview(column_id, value, issues):
    length = settings.CELL_PREVIEW_CHARS
    truncated = value is not None and len(value) > length
    shown = value[:length] if truncated else value
    display = "—" if is_missing(value) else (f"{shown}…" if truncated else value)
    return {"columnId": column_id, "value": shown, "displayValue": display,
            "isTruncated": truncated, "issues": issues}


class RowsView(APIView):
    def get(self, request, version_id):
        params = query(request, "checkRunId", "onlyProblemRows", "columnId", "ruleCode", paginated=True)
        version = owned_version(request.user, version_id)
        only_problem_rows = boolean_param(params, "onlyProblemRows")
        has_filters = any(field in params for field in ("onlyProblemRows", "columnId", "ruleCode"))
        run = issues = None
        rows = version.rows.order_by("row_index")
        if "checkRunId" in params:
            run = get_object_or_404(version.checks, pk=uuid_param(params["checkRunId"], "checkRunId"))
            if has_filters and run.status != Status.SUCCEEDED:
                raise APIError(422, fields={"checkRunId": ["Для фильтрации нужна успешная проверка."]})
            issues = filter_issues(run, params)
            if only_problem_rows or "columnId" in params or "ruleCode" in params:
                rows = rows.filter(row_index__in=issues.order_by().values("row_index"))
        elif has_filters:
            raise APIError(422, fields={"checkRunId": ["Укажите проверку этой версии."]})

        columns = list(version.columns.order_by("position", "id"))
        records, pagination = page(rows, params)
        annotations = defaultdict(list)
        if issues is not None and records:
            for issue in issues.filter(row_index__in=[row.row_index for row in records]).order_by(
                "row_index", "column_id", "rule_code", "id",
            ):
                annotations[(issue.row_index, issue.column_id)].append(
                    {"ruleCode": issue.rule_code, "message": issue.message},
                )
        return Response({
            "versionId": version.id, "checkRunId": run.id if run else None,
            "columns": [row_column_dto(column) for column in columns], "pagination": pagination,
            "items": [
                {"rowIndex": row.row_index, "rowNumber": row.row_index + 1,
                 "cells": [cell_preview(column.id, row.values[column.position], annotations[(row.row_index, column.id)])
                           for column in columns]}
                for row in records
            ],
        })


class CellView(APIView):
    def get(self, request, version_id, row_index, column_id):
        query(request)
        version = owned_version(request.user, version_id)
        try:
            index = integer_param(row_index, "rowIndex")
        except APIError:
            raise APIError(404) from None
        column = get_object_or_404(version.columns, pk=column_id)
        row = get_object_or_404(version.rows, row_index=index)
        return Response({"versionId": version.id, "rowIndex": row.row_index,
                         "columnId": column.id, "value": row.values[column.position]})


class DownloadView(APIView):
    def get(self, request, version_id):
        params = query(request, "format")
        version = owned_version(request.user, version_id)
        file_format = choice_param(params, "format", {"csv", "original"}, "csv")
        if file_format == "original":
            if version.kind != DatasetVersion.Kind.ORIGINAL:
                raise APIError(422, fields={"format": ["Исходные байты доступны только у исходной версии."]})
            file = version.dataset.original_file
            name = file.original_name
        else:
            file = version.data_file
            name = download_name(version.name)
        try:
            stream = stored_path(file).open("rb")
        except OSError:
            raise APIError(503) from None
        return FileResponse(stream, as_attachment=True, filename=name, content_type="text/csv; charset=utf-8")


class ConfigurationView(APIView):
    def get(self, request, version_id):
        query(request)
        version = owned_version(request.user, version_id)
        return Response(configuration_dto(version.check_configuration))

    def put(self, request, version_id):
        query(request)
        version = owned_version(request.user, version_id)
        data = body(request, ConfigurationInput)
        requested = set(data["columnIds"])
        with transaction.atomic():
            configuration = CheckConfiguration.objects.select_for_update().get(version=version)
            if configuration.revision != data["expectedRevision"]:
                configuration_conflict(configuration.revision)
            if len(requested) != len(data["columnIds"]) or version.columns.filter(pk__in=requested).count() != len(requested):
                invalid_column()
            if requested != set(configuration.columns.values_list("pk", flat=True)):
                configuration.columns.set(requested)
                configuration.revision += 1
                configuration.save(update_fields=["revision", "updated_at"])
            result = configuration_dto(configuration)
        return Response(result)


class ChecksView(APIView):
    def get(self, request, version_id):
        params = query(request, paginated=True)
        version = owned_version(request.user, version_id)
        return paginated(version.checks.order_by(*NEWEST), params, check_dto)

    def post(self, request, version_id):
        query(request)
        version = owned_version(request.user, version_id)
        data = body(request, CheckInput)

        def submit(owner):
            Dataset.objects.select_for_update().get(pk=version.dataset_id)
            configuration = CheckConfiguration.objects.select_for_update().get(version=version)
            if configuration.revision != data["configurationRevision"]:
                configuration_conflict(configuration.revision)
            if version.checks.filter(status__in=ACTIVE_STATUSES).exists():
                raise APIError(409, "JOB_ALREADY_RUNNING", "У этой версии уже есть активная проверка.")
            assert_capacity(owner)
            return create_check(version, configuration, owner.id).current_job

        job, status = idempotent_operation(request, data, submit)
        return Response({"checkRunId": job.resource_id, "jobId": job.id}, status=status)


class CheckView(APIView):
    def get(self, request, check_id):
        query(request)
        return Response(check_dto(owned_check(request.user, check_id)))


class QualitySummaryView(APIView):
    def get(self, request, version_id):
        query(request)
        version = owned_version(request.user, version_id)
        configuration = version.check_configuration
        runs = version.checks.order_by("-current_job__created_at", "-current_job_id", "-id")
        latest = runs.first()
        successful = latest if latest and latest.status == Status.SUCCEEDED else runs.filter(status=Status.SUCCEEDED).first()
        active = latest if latest and latest.status in ACTIVE_STATUSES else None
        return Response({
            "versionId": version.id, "status": "not_checked" if latest is None else
            ("ready" if latest.status == Status.SUCCEEDED else latest.status),
            "configurationRevision": configuration.revision, "selectedColumnCount": configuration.columns.count(),
            "totalColumnCount": version.column_count, "activeCheckRunId": active.id if active else None,
            "latestAttemptId": latest.id if latest else None, "lastSuccessfulCheckRunId": successful.id if successful else None,
            "isStale": bool(successful and successful.configuration_revision != configuration.revision),
            "result": {"checkRunId": successful.id, **check_metrics(successful)} if successful else None,
        })


class ColumnSummaryView(APIView):
    def get(self, request, check_id):
        params = query(request, paginated=True)
        run = owned_check(request.user, check_id)
        groups = (run.issues.values("column_id", "column__name", "column__position", "rule_code")
                  .annotate(issue_count=Count("id"), affected_rows=Count("row_index", distinct=True))
                  .order_by("column__position", "column_id", "rule_code"))
        return paginated(groups, params, lambda group: {
            "columnId": group["column_id"], "columnName": group["column__name"], "ruleCode": group["rule_code"],
            "label": RULES[group["rule_code"]]["label"], "issueCount": group["issue_count"],
            "affectedRowCount": group["affected_rows"],
        })


class IssuesView(APIView):
    def get(self, request, check_id):
        params = query(request, "columnId", "ruleCode", "rowIndex", paginated=True)
        run = owned_check(request.user, check_id)
        return paginated(filter_issues(run, params).order_by("row_index", "column__position", "rule_code", "id"),
                         params, issue_dto)


class CleaningsView(APIView):
    def get(self, request, dataset_id):
        params = query(request, paginated=True)
        dataset = owned_dataset(request.user, dataset_id)
        return paginated(dataset.cleanings.order_by(*NEWEST), params, cleaning_dto)

    def post(self, request, dataset_id):
        query(request)
        dataset = owned_dataset(request.user, dataset_id)
        data = body(request, CleaningInput)

        def submit(owner):
            locked = Dataset.objects.select_for_update().get(pk=dataset.pk)
            source = get_object_or_404(locked.versions, pk=data["sourceVersionId"])
            return create_cleaning(locked, owner, source, data)

        job, status = idempotent_operation(request, data, submit)
        return Response({"cleaningRunId": job.resource_id, "jobId": job.id}, status=status)


class CleaningView(APIView):
    def get(self, request, cleaning_id):
        query(request)
        run = get_object_or_404(CleaningRun.objects.filter(dataset__project__owner=request.user), pk=cleaning_id)
        return Response(cleaning_dto(run))


def audit_list(params, events):
    if event_type := choice_param(params, "type", AuditEvent.Type.values):
        events = events.filter(type=event_type)
    bounds = {}
    for field in ("from", "to"):
        if field in params:
            try:
                bounds[field] = serializers.DateTimeField().run_validation(params[field])
            except serializers.ValidationError as exc:
                raise APIError(422, fields={field: exc.detail}) from None
    if "from" in bounds and "to" in bounds and bounds["from"] > bounds["to"]:
        raise APIError(422, fields={"to": ["Конечная дата должна быть не раньше начальной."]})
    if "from" in bounds:
        events = events.filter(created_at__gte=bounds["from"])
    if "to" in bounds:
        events = events.filter(created_at__lte=bounds["to"])
    return paginated(events.select_related("actor", "project", "dataset", "source_version", "result_version")
                     .order_by(*NEWEST), params, audit_dto)


class ProjectAuditView(APIView):
    def get(self, request, project_id):
        params = query(request, "datasetId", "type", "from", "to", paginated=True)
        project = owned_project(request.user, project_id)
        events = AuditEvent.objects.filter(project=project)
        if "datasetId" in params:
            dataset = get_object_or_404(project.datasets, pk=uuid_param(params["datasetId"], "datasetId"))
            events = events.filter(dataset=dataset)
        return audit_list(params, events)


class DatasetAuditView(APIView):
    def get(self, request, dataset_id):
        params = query(request, "versionId", "type", "from", "to", paginated=True)
        dataset = owned_dataset(request.user, dataset_id)
        events = AuditEvent.objects.filter(dataset=dataset)
        if "versionId" in params:
            version = get_object_or_404(dataset.versions, pk=uuid_param(params["versionId"], "versionId"))
            events = events.filter(Q(source_version=version) | Q(result_version=version))
        return audit_list(params, events)


class JobView(APIView):
    def get(self, request, job_id):
        query(request)
        return Response(job_dto(owned_job(request.user, job_id)))


class RetryView(APIView):
    def post(self, request, job_id):
        query(request)
        job = owned_job(request.user, job_id)
        data = body(request)
        attempt, status = idempotent_operation(request, data, lambda owner: retry_job(job, owner))
        return Response({"jobId": attempt.id, "resourceType": RESOURCE_TYPES[attempt.kind],
                         "resourceId": attempt.resource_id}, status=status)
