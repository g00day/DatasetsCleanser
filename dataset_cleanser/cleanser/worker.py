import json
import logging
from collections import defaultdict
from datetime import timedelta
from itertools import islice
from tempfile import TemporaryFile
from time import monotonic

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from auth_app.models import Account, identity_key

from .catalog import ACTIONS, ORIGINAL_VERSION_NAME, RULES
from .csv_data import (
    ProcessingError, infer_schema, is_missing, matches_type, pseudonym, read_csv, write_csv,
)
from .files import StorageQuotaExceeded, download_name, stage_file
from .models import (
    AuditEvent, CheckConfiguration, CleaningOperation, Dataset, DatasetVersion, Job, QualityIssue,
    Status, StoredFile, VersionColumn, VersionRow,
)
from .operations import create_check, initialize_configuration, job_resource

logger = logging.getLogger(__name__)
BATCH_SIZE = 500
FIRST_STAGE = {Job.Kind.IMPORT: "reading_file", Job.Kind.CHECK: "checking_rows", Job.Kind.CLEANING: "removing_rows"}


class LeaseLost(Exception):
    pass


def dataset_lock(query, *, skip_locked=False):
    if skip_locked and connection.features.has_select_for_update_skip_locked:
        return query.select_for_update(skip_locked=True).first()
    return query.select_for_update().first()


def claim():
    pending = Job.objects.filter(status=Status.QUEUED).order_by("created_at", "id")
    for job_id, dataset_id in pending.values_list("pk", "dataset_id")[:32]:
        with transaction.atomic():
            dataset = dataset_lock(Dataset.objects.filter(pk=dataset_id), skip_locked=True)
            if dataset is None:
                continue
            job = Job.objects.select_for_update().filter(pk=job_id, status=Status.QUEUED).first()
            if job is None:
                continue
            resource = job_resource(job, dataset)
            now = timezone.now()
            job.status = Status.RUNNING
            job.stage = FIRST_STAGE[job.kind]
            job.started_at = job.heartbeat_at = now
            job.deadline_at = now + timedelta(seconds=settings.JOB_TIMEOUT_SECONDS)
            job.lease_expires_at = min(job.deadline_at, now + timedelta(seconds=settings.JOB_LEASE_SECONDS))
            job.save(update_fields=["status", "stage", "started_at", "heartbeat_at", "deadline_at", "lease_expires_at"])
            if job.kind != Job.Kind.IMPORT:
                resource.status = Status.RUNNING
                resource.started_at = now
                resource.save(update_fields=["status", "started_at"])
            return job
    return None


class Execution:
    def __init__(self, job):
        self.job = job
        self.next_heartbeat = monotonic() + min(5, settings.JOB_LEASE_SECONDS / 3)

    def check_deadline(self):
        if timezone.now() >= self.job.deadline_at:
            raise ProcessingError("JOB_TIMEOUT", "Превышено время обработки.", retryable=True)

    def heartbeat(self, stage=None):
        if stage is None and monotonic() < self.next_heartbeat:
            return
        self.check_deadline()
        now = timezone.now()
        lease = min(self.job.deadline_at, now + timedelta(seconds=settings.JOB_LEASE_SECONDS))
        updates = {"heartbeat_at": now, "lease_expires_at": lease}
        if stage is not None:
            updates["stage"] = stage
        if not Job.objects.filter(pk=self.job.pk, status=Status.RUNNING, lease_expires_at__gt=now).update(**updates):
            raise LeaseLost
        self.next_heartbeat = monotonic() + min(5, settings.JOB_LEASE_SECONDS / 3)

    def lock_publication(self, *, writes_files=False):
        if writes_files:
            Account.objects.select_for_update().get(pk=self.job.owner_id)
        dataset = Dataset.objects.select_for_update().get(pk=self.job.dataset_id)
        job = Job.objects.select_for_update().get(pk=self.job.pk)
        self.check_deadline()
        if job.status != Status.RUNNING or job.lease_expires_at <= timezone.now():
            raise LeaseLost
        resource = job_resource(job, dataset)
        current_id = dataset.import_job_id if job.kind == Job.Kind.IMPORT else resource.current_job_id
        if current_id != job.pk:
            raise LeaseLost
        return job, dataset, resource

    def bulk_create(self, model, objects):
        records = iter(objects)
        while batch := list(islice(records, BATCH_SIZE)):
            self.check_deadline()
            model.objects.bulk_create(batch, batch_size=BATCH_SIZE)

    def complete(self, job):
        self.check_deadline()
        job.status = Status.SUCCEEDED
        job.finished_at = timezone.now()
        job.progress_percent = 100
        job.save(update_fields=["status", "finished_at", "progress_percent"])
        return job.finished_at


def mark_failed(job, dataset, error):
    job.status = Status.FAILED
    job.finished_at = timezone.now()
    job.error_code = error.code
    job.error_message = error.message
    job.retryable = error.retryable
    job.save(update_fields=["status", "finished_at", "error_code", "error_message", "retryable"])

    resource = job_resource(job, dataset)
    if job.kind == Job.Kind.IMPORT:
        if resource.import_job_id == job.pk:
            resource.status = Dataset.State.IMPORT_FAILED
            resource.save(update_fields=["status", "updated_at"])
    elif resource.current_job_id == job.pk:
        resource.status = Status.FAILED
        resource.finished_at = job.finished_at
        resource.save(update_fields=["status", "finished_at"])


def fail(job_id, dataset_id, error=None):
    with transaction.atomic():
        dataset = dataset_lock(Dataset.objects.filter(pk=dataset_id), skip_locked=error is None)
        if dataset is None:
            return
        job = Job.objects.select_for_update().filter(pk=job_id, status=Status.RUNNING).first()
        if job is None:
            return
        if error is not None:
            mark_failed(job, dataset, error)
        elif job.deadline_at <= timezone.now():
            mark_failed(job, dataset, ProcessingError("JOB_TIMEOUT", "Превышено время обработки.", retryable=True))
        elif job.lease_expires_at <= timezone.now():
            mark_failed(job, dataset, ProcessingError("WORKER_LOST", "Исполнитель задания недоступен.", retryable=True))


def reap_expired():
    now = timezone.now()
    expired = Job.objects.filter(status=Status.RUNNING).filter(
        Q(lease_expires_at__lte=now) | Q(deadline_at__lte=now),
    ).order_by("lease_expires_at", "id")
    for job_id, dataset_id in expired.values_list("pk", "dataset_id")[:100]:
        fail(job_id, dataset_id)


def publish_version(execution, dataset, **data):
    rows = data.pop("rows")
    schema = data.pop("schema")
    version = DatasetVersion.objects.create(dataset=dataset, row_count=len(rows), column_count=len(schema), **data)
    columns = VersionColumn.objects.bulk_create([VersionColumn(version=version, **column) for column in schema])
    execution.bulk_create(VersionRow, (
        VersionRow(version=version, row_index=index, values=row) for index, row in enumerate(rows)
    ))
    return version, columns


def run_import(execution):
    job = execution.job
    dataset = Dataset.objects.select_related("original_file").get(pk=job.dataset_id)
    execution.heartbeat("parsing_csv")
    header, rows = read_csv(dataset.original_file, dataset.delimiter, dataset.encoding, execution.heartbeat)
    schema = infer_schema(header, rows, execution.heartbeat)
    with stage_file() as staged:
        execution.heartbeat("saving_version")
        write_csv(staged, header, rows, execution.heartbeat)
        with transaction.atomic():
            job, dataset, _ = execution.lock_publication(writes_files=True)
            file = staged.publish(job.owner_id, StoredFile.Kind.VERSION_DATA, download_name(ORIGINAL_VERSION_NAME))
            version, columns = publish_version(
                execution, dataset, number=1, name=ORIGINAL_VERSION_NAME, name_key=identity_key(ORIGINAL_VERSION_NAME),
                kind=DatasetVersion.Kind.ORIGINAL, rows=rows,
                schema=[{"position": position, **item} for position, item in enumerate(schema)],
                data_file=file, created_by_id=job.owner_id,
            )
            configuration = initialize_configuration(version, columns)
            dataset.status = Dataset.State.READY
            dataset.original_version = dataset.latest_version = version
            dataset.save(update_fields=["original_version", "latest_version", "status", "updated_at"])
            execution.complete(job)
            create_check(version, configuration, job.owner_id)


def row_issues(values, columns, rules):
    for column in columns:
        value = values[column.position]
        if is_missing(value):
            if "required" in rules:
                yield column, "required"
            continue
        normalized = value.strip()
        valid_type = matches_type(normalized, column.data_type)
        if "data_type" in rules and not valid_type:
            yield column, "data_type"
        if "email_format" in rules and column.data_type == "email" and not valid_type:
            yield column, "email_format"


def run_check(execution):
    run = job_resource(execution.job, Dataset(pk=execution.job.dataset_id))
    snapshot = run.configuration_snapshot
    columns = list(run.version.columns.filter(pk__in=snapshot["columnIds"]).order_by("position", "id"))
    rules = frozenset(snapshot["ruleCodes"])
    issue_count = affected_rows = checked_rows = 0
    rows = run.version.rows.order_by("row_index").values_list("row_index", "values")
    with TemporaryFile(mode="w+t", encoding="utf-8") as spool:
        for row_index, values in rows.iterator(chunk_size=BATCH_SIZE):
            execution.heartbeat()
            checked_rows += 1
            row_has_issues = False
            for column, code in row_issues(values, columns, rules):
                spool.write(json.dumps([str(column.id), row_index, code]) + "\n")
                issue_count += 1
                row_has_issues = True
            affected_rows += row_has_issues
        spool.seek(0)
        execution.heartbeat("saving_results")
        with transaction.atomic():
            job, _, run = execution.lock_publication()
            records = (json.loads(line) for line in spool)
            execution.bulk_create(QualityIssue, (
                QualityIssue(check_run=run, column_id=column_id, row_index=row_index, rule_code=code,
                             message=RULES[code]["label"])
                for column_id, row_index, code in records
            ))
            run.status = Status.SUCCEEDED
            run.checked_row_count = checked_rows
            run.checked_column_count = len(columns)
            run.issue_count = issue_count
            run.affected_row_count = affected_rows
            run.finished_at = execution.complete(job)
            run.save(update_fields=["status", "checked_row_count", "checked_column_count",
                                    "issue_count", "affected_row_count", "finished_at"])


def apply_row_removals(rows, operation, heartbeat):
    kept = []
    seen = set()
    is_missing_step = operation.action_code == "drop_rows_with_missing"
    for row in rows:
        heartbeat()
        if is_missing_step:
            if any(is_missing(value) for value in row):
                continue
        else:
            key = tuple(row)
            if key in seen:
                continue
            seen.add(key)
        kept.append(row)
    return kept


def apply_column_actions(rows, operations, run_id, heartbeat):
    transforms = {"trim": str.strip, "lowercase": str.lower}
    tokens = defaultdict(dict)
    for row in rows:
        heartbeat()
        for operation in operations:
            position = operation.column.position
            value = row[position]
            if is_missing(value):
                continue
            if operation.action_code == "pseudonymize":
                strategy = operation.parameters["strategy"]
                result = pseudonym(value, tokens[operation.id], strategy, f"{run_id.hex}{operation.id.hex}")
            else:
                result = transforms[operation.action_code](value)
            if value != result:
                row[position] = result
                operation.changed_cell_count += 1


def run_cleaning(execution):
    run = job_resource(execution.job, Dataset(pk=execution.job.dataset_id))
    source = run.source_version
    columns = list(source.columns.order_by("position", "id"))
    rows = []
    for row in source.rows.order_by("row_index").values_list("values", flat=True).iterator(chunk_size=BATCH_SIZE):
        execution.heartbeat()
        rows.append(row)
    operations = list(run.operations.select_related("column").order_by("order", "id"))
    for operation in operations:
        operation.removed_row_count = operation.changed_cell_count = 0
        if operation.scope == "dataset":
            kept = apply_row_removals(rows, operation, execution.heartbeat)
            operation.removed_row_count = len(rows) - len(kept)
            rows = kept
    execution.heartbeat("applying_column_actions")
    apply_column_actions(rows, [operation for operation in operations if operation.scope == "column"],
                         run.pk, execution.heartbeat)

    with stage_file() as staged:
        execution.heartbeat("saving_version")
        write_csv(staged, [column.name for column in columns], rows, execution.heartbeat)
        with transaction.atomic():
            job, dataset, run = execution.lock_publication(writes_files=True)
            if dataset.latest_version_id != run.expected_latest_version_id:
                raise ProcessingError("STALE_BASE_VERSION", "Доступна более новая версия датасета.")
            file = staged.publish(job.owner_id, StoredFile.Kind.VERSION_DATA, download_name(run.requested_version_name))
            version, new_columns = publish_version(
                execution, dataset, number=dataset.latest_version.number + 1,
                name=run.requested_version_name, name_key=run.requested_name_key, kind=DatasetVersion.Kind.PROCESSED,
                parent_version=source, rows=rows, data_file=file, created_by_id=job.owner_id,
                schema=[{"position": column.position, "key": column.key, "name": column.name,
                         "data_type": column.data_type, "nullable": column.nullable} for column in columns],
            )
            source_config = CheckConfiguration.objects.select_for_update().get(version=source)
            selected_keys = set(source_config.columns.values_list("key", flat=True))
            config = initialize_configuration(version, [col for col in new_columns if col.key in selected_keys])
            CleaningOperation.objects.bulk_update(operations, ["removed_row_count", "changed_cell_count"])
            results = []
            for operation in operations:
                result = {"id": str(operation.id), "order": operation.order, "scope": operation.scope,
                          "columnId": str(operation.column_id) if operation.column_id else None,
                          "actionCode": operation.action_code, "parameters": operation.parameters,
                          "removedRowCount": operation.removed_row_count,
                          "changedCellCount": operation.changed_cell_count}
                results.append(result)
                AuditEvent.objects.create(
                    project_id=dataset.project_id, dataset=dataset, actor_id=job.owner_id, cleaning_run=run,
                    source_version=source, result_version=version, operation=operation,
                    type=AuditEvent.Type.CLEANING, summary=ACTIONS[operation.action_code]["label"],
                    details={**result, "actionVersion": ACTIONS[operation.action_code]["version"]},
                )
            dataset.latest_version = version
            dataset.save(update_fields=["latest_version", "updated_at"])
            run.finished_at = execution.complete(job)
            run.status = Status.SUCCEEDED
            run.result_version = version
            run.removed_row_count = source.row_count - len(rows)
            run.changed_cell_count = sum(operation.changed_cell_count for operation in operations)
            run.operation_results = results
            run.result_check_run = create_check(version, config, job.owner_id)
            run.save(update_fields=["status", "finished_at", "result_version", "result_check_run",
                                    "removed_row_count", "changed_cell_count", "operation_results"])


PROCESSORS = {Job.Kind.IMPORT: run_import, Job.Kind.CHECK: run_check, Job.Kind.CLEANING: run_cleaning}


def process_next_job():
    reap_expired()
    job = claim()
    if job is None:
        return False
    try:
        PROCESSORS[job.kind](Execution(job))
    except LeaseLost:
        fail(job.pk, job.dataset_id)
    except ProcessingError as error:
        fail(job.pk, job.dataset_id, error)
    except StorageQuotaExceeded:
        fail(job.pk, job.dataset_id, ProcessingError("STORAGE_QUOTA_EXCEEDED", "Достигнут лимит места."))
    except Exception as error:
        logger.error("Job processing failed job_id=%s exception=%s", job.pk, type(error).__name__)
        fail(job.pk, job.dataset_id, ProcessingError("PROCESSING_FAILED", "Сбой обработки данных.", retryable=True))
    return True
