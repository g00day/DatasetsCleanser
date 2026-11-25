from .models import ACTIVE_STATUSES, DatasetVersion, Status
from .operations import RESOURCE_TYPES


def reference(resource):
    return {"id": resource.id, "name": resource.name}


def project_summary(project):
    return {**reference(project), "datasetCount": project.dataset_count, "updatedAt": project.updated_at}


def project_detail(project):
    return {**project_summary(project), "description": project.description, "createdAt": project.created_at}


def upload_dto(dataset):
    return {"datasetId": dataset.id, "datasetName": dataset.name, "projectId": dataset.project_id,
            "projectName": dataset.project.name, "originalFileName": dataset.original_file.original_name,
            "sizeBytes": dataset.original_file.size_bytes, "uploadedAt": dataset.uploaded_at,
            "status": dataset.status, "importJobId": dataset.import_job_id}


def column_dto(column):
    return {"id": column.id, "key": column.key, "position": column.position, "name": column.name,
            "dataType": column.data_type, "nullable": column.nullable}


def row_column_dto(column):
    return {"id": column.id, "position": column.position, "name": column.name, "dataType": column.data_type}


def dataset_summary(dataset, include_schema):
    version = dataset.latest_version
    result = {**reference(dataset), "status": dataset.status, "latestVersionId": dataset.latest_version_id,
              "rowCount": version.row_count if version else None,
              "columnCount": version.column_count if version else None, "uploadedAt": dataset.uploaded_at}
    if include_schema:
        result["schema"] = [column_dto(column) for column in version.columns.all()] if version else None
    return result


def dataset_detail(dataset):
    active = dataset.cleanings.filter(status__in=ACTIVE_STATUSES).values_list("id", flat=True).first()
    return {**reference(dataset), "project": reference(dataset.project), "status": dataset.status,
            "originalVersionId": dataset.original_version_id, "latestVersionId": dataset.latest_version_id,
            "importJobId": dataset.import_job_id, "activeCleaningRunId": active,
            "originalFile": {"name": dataset.original_file.original_name, "sizeBytes": dataset.original_file.size_bytes},
            "uploadedAt": dataset.uploaded_at}


def version_dto(version):
    return {**reference(version), "datasetId": version.dataset_id, "number": version.number, "kind": version.kind,
            "parentVersionId": version.parent_version_id, "rowCount": version.row_count,
            "columnCount": version.column_count, "canRename": version.kind == DatasetVersion.Kind.PROCESSED,
            "createdAt": version.created_at, "updatedAt": version.updated_at}


def configuration_dto(configuration):
    return {"id": configuration.id, "versionId": configuration.version_id, "revision": configuration.revision,
            "columnIds": list(configuration.columns.order_by("position", "id").values_list("pk", flat=True)),
            "ruleCodes": configuration.rule_codes, "updatedAt": configuration.updated_at}


def check_metrics(run):
    return {"configurationRevision": run.configuration_revision, "checkedRowCount": run.checked_row_count,
            "checkedColumnCount": run.checked_column_count, "issueCount": run.issue_count,
            "affectedRowCount": run.affected_row_count, "qualityScore": run.quality_score,
            "scoreFormulaVersion": run.score_formula_version}


def check_dto(run):
    return {"id": run.id, "versionId": run.version_id, **check_metrics(run),
            "configurationSnapshot": run.configuration_snapshot, "status": run.status,
            "currentJobId": run.current_job_id, "rulesetVersion": run.ruleset_version,
            "createdAt": run.created_at, "startedAt": run.started_at, "finishedAt": run.finished_at}


def issue_dto(issue):
    return {"id": issue.id, "checkRunId": issue.check_run_id, "columnId": issue.column_id,
            "rowIndex": issue.row_index, "ruleCode": issue.rule_code, "message": issue.message}


def cleaning_dto(run):
    return {"id": run.id, "datasetId": run.dataset_id, "sourceVersionId": run.source_version_id,
            "requestedVersionName": run.requested_version_name, "plan": run.plan_snapshot, "status": run.status,
            "currentJobId": run.current_job_id, "resultVersionId": run.result_version_id,
            "resultCheckRunId": run.result_check_run_id, "removedRowCount": run.removed_row_count,
            "changedCellCount": run.changed_cell_count, "operationResults": run.operation_results,
            "createdAt": run.created_at, "startedAt": run.started_at, "finishedAt": run.finished_at}


def audit_version(version):
    return {**reference(version), "number": version.number} if version else None


def audit_dto(event):
    return {"id": event.id, "type": event.type, "summary": event.summary,
            "actor": {"id": event.actor_id, "username": event.actor.username}, "project": reference(event.project),
            "dataset": reference(event.dataset), "sourceVersion": audit_version(event.source_version),
            "resultVersion": audit_version(event.result_version), "details": event.details, "createdAt": event.created_at}


def job_dto(job):
    error = None
    if job.status == Status.FAILED:
        error = {"code": job.error_code, "message": job.error_message, "retryable": job.retryable}
    return {"id": job.id, "kind": job.kind, "resourceType": RESOURCE_TYPES[job.kind], "resourceId": job.resource_id,
            "status": job.status, "stage": job.stage, "progressPercent": job.progress_percent, "attempt": job.attempt,
            "error": error, "createdAt": job.created_at, "startedAt": job.started_at, "finishedAt": job.finished_at}
