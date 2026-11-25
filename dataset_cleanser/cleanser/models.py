import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class CreatedModel(UUIDModel):
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class UpdatedModel(CreatedModel):
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Status(models.TextChoices):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ACTIVE_STATUSES = (Status.QUEUED, Status.RUNNING)


class Project(UpdatedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=1000, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["owner", "created_at", "id"])]


class StoredFile(CreatedModel):
    class Kind(models.TextChoices):
        SOURCE = "source"
        VERSION_DATA = "version_data"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    storage_key = models.CharField(max_length=32, unique=True)
    original_name = models.CharField(max_length=255)
    media_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    kind = models.CharField(max_length=12, choices=Kind.choices)


class Dataset(UpdatedModel):
    class State(models.TextChoices):
        IMPORTING = "importing"
        READY = "ready"
        IMPORT_FAILED = "import_failed"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="datasets")
    name = models.CharField(max_length=80)
    status = models.CharField(max_length=13, choices=State.choices, default=State.IMPORTING)
    original_file = models.ForeignKey(StoredFile, on_delete=models.PROTECT)
    original_version = models.ForeignKey("DatasetVersion", on_delete=models.SET_NULL, null=True, related_name="+")
    latest_version = models.ForeignKey("DatasetVersion", on_delete=models.SET_NULL, null=True, related_name="+")
    import_job = models.ForeignKey("Job", on_delete=models.SET_NULL, null=True, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    delimiter = models.CharField(max_length=4, default="auto")
    encoding = models.CharField(max_length=9, default="utf-8")

    class Meta:
        indexes = [models.Index(fields=["project", "uploaded_at", "id"])]


class DatasetVersion(UpdatedModel):
    class Kind(models.TextChoices):
        ORIGINAL = "original"
        PROCESSED = "processed"

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    name = models.CharField(max_length=80)
    name_key = models.CharField(max_length=240, editable=False)
    kind = models.CharField(max_length=9, choices=Kind.choices)
    parent_version = models.ForeignKey("self", on_delete=models.PROTECT, null=True)
    data_file = models.ForeignKey(StoredFile, on_delete=models.PROTECT)
    row_count = models.PositiveIntegerField()
    column_count = models.PositiveIntegerField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset", "number"], name="version_unique_number"),
            models.UniqueConstraint(fields=["dataset", "name_key"], name="version_unique_name"),
            models.CheckConstraint(
                condition=Q(kind="original", number=1, parent_version__isnull=True)
                | Q(kind="processed", number__gt=1, parent_version__isnull=False),
                name="version_valid_lineage",
            ),
        ]


class DataType(models.TextChoices):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    EMAIL = "email"


class VersionColumn(CreatedModel):
    version = models.ForeignKey(DatasetVersion, on_delete=models.CASCADE, related_name="columns")
    key = models.UUIDField(default=uuid.uuid4)
    position = models.PositiveIntegerField()
    name = models.TextField()
    data_type = models.CharField(max_length=8, choices=DataType.choices)
    nullable = models.BooleanField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["version", "position"], name="column_unique_position"),
            models.UniqueConstraint(fields=["version", "key"], name="column_unique_key"),
        ]


class VersionRow(models.Model):
    version = models.ForeignKey(DatasetVersion, on_delete=models.CASCADE, related_name="rows")
    row_index = models.PositiveIntegerField()
    values = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "row_index"], name="row_unique_position")]


class CheckConfiguration(UUIDModel):
    version = models.OneToOneField(DatasetVersion, on_delete=models.CASCADE, related_name="check_configuration")
    revision = models.PositiveIntegerField(default=1)
    columns = models.ManyToManyField(VersionColumn, related_name="+")
    rule_codes = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)


class Run(CreatedModel):
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.QUEUED)
    current_job = models.ForeignKey("Job", on_delete=models.SET_NULL, null=True, related_name="+")
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        abstract = True


class QualityCheckRun(Run):
    version = models.ForeignKey(DatasetVersion, on_delete=models.CASCADE, related_name="checks")
    configuration_revision = models.PositiveIntegerField()
    configuration_snapshot = models.JSONField()
    ruleset_version = models.PositiveIntegerField()
    checked_row_count = models.PositiveIntegerField(null=True)
    checked_column_count = models.PositiveIntegerField(null=True)
    issue_count = models.PositiveIntegerField(null=True)
    affected_row_count = models.PositiveIntegerField(null=True)
    quality_score = models.DecimalField(max_digits=8, decimal_places=4, null=True)
    score_formula_version = models.PositiveIntegerField(null=True)

    class Meta:
        indexes = [models.Index(fields=["version", "created_at", "id"])]
        constraints = [
            models.UniqueConstraint(fields=["version"], condition=Q(status__in=ACTIVE_STATUSES),
                                    name="one_active_check_per_version"),
        ]


class QualityIssue(UUIDModel):
    check_run = models.ForeignKey(QualityCheckRun, on_delete=models.CASCADE, related_name="issues")
    column = models.ForeignKey(VersionColumn, on_delete=models.CASCADE)
    row_index = models.PositiveIntegerField()
    rule_code = models.CharField(max_length=24)
    message = models.CharField(max_length=160)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["check_run", "column", "rule_code", "row_index"],
                                    name="issue_unique_cell_rule"),
        ]
        indexes = [models.Index(fields=["check_run", "row_index"])]


class CleaningRun(Run):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="cleanings")
    source_version = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT, related_name="+")
    expected_latest_version = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT, related_name="+")
    requested_version_name = models.CharField(max_length=80)
    requested_name_key = models.CharField(max_length=240, editable=False)
    plan_snapshot = models.JSONField()
    result_version = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT, related_name="+", null=True)
    result_check_run = models.ForeignKey(QualityCheckRun, on_delete=models.SET_NULL, null=True)
    removed_row_count = models.PositiveIntegerField(null=True)
    changed_cell_count = models.PositiveIntegerField(null=True)
    operation_results = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset"], condition=Q(status__in=ACTIVE_STATUSES),
                                    name="one_active_cleaning_per_dataset"),
        ]
        indexes = [models.Index(fields=["dataset", "created_at", "id"])]


class CleaningOperation(UUIDModel):
    cleaning_run = models.ForeignKey(CleaningRun, on_delete=models.CASCADE, related_name="operations")
    order = models.PositiveIntegerField()
    scope = models.CharField(max_length=7, choices=[("dataset", "Dataset"), ("column", "Column")])
    column = models.ForeignKey(VersionColumn, on_delete=models.PROTECT, null=True)
    action_code = models.CharField(max_length=24)
    parameters = models.JSONField()
    removed_row_count = models.PositiveIntegerField(null=True)
    changed_cell_count = models.PositiveIntegerField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cleaning_run", "order"], name="operation_unique_order"),
            models.UniqueConstraint(fields=["cleaning_run", "column"], name="operation_unique_column"),
        ]


class Job(CreatedModel):
    class Kind(models.TextChoices):
        IMPORT = "import"
        CHECK = "quality_check"
        CLEANING = "cleaning"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE)
    kind = models.CharField(max_length=13, choices=Kind.choices)
    resource_id = models.UUIDField()
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.QUEUED)
    stage = models.CharField(max_length=24, default="queued")
    progress_percent = models.PositiveSmallIntegerField(null=True)
    attempt = models.PositiveIntegerField(default=1)
    retry_of_job = models.ForeignKey("self", on_delete=models.PROTECT, null=True)
    error_code = models.CharField(max_length=40, blank=True)
    error_message = models.CharField(max_length=200, blank=True)
    retryable = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    heartbeat_at = models.DateTimeField(null=True)
    lease_expires_at = models.DateTimeField(null=True)
    deadline_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["status", "created_at", "id"]),
            models.Index(fields=["status", "lease_expires_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["kind", "resource_id"], condition=Q(status__in=ACTIVE_STATUSES),
                                    name="one_active_attempt_per_resource"),
        ]


class AuditEvent(CreatedModel):
    class Type(models.TextChoices):
        CLEANING = "cleaning_operation_applied"
        RENAME = "version_renamed"

    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    cleaning_run = models.ForeignKey(CleaningRun, on_delete=models.PROTECT, null=True)
    source_version = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT, related_name="+", null=True)
    result_version = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT, related_name="+", null=True)
    operation = models.OneToOneField(CleaningOperation, on_delete=models.PROTECT, null=True)
    type = models.CharField(max_length=26, choices=Type.choices)
    summary = models.CharField(max_length=160)
    details = models.JSONField()

    class Meta:
        indexes = [
            models.Index(fields=["dataset", "created_at", "id"]),
            models.Index(fields=["project", "created_at", "id"]),
        ]


class IdempotencyRecord(CreatedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    route = models.CharField(max_length=120)
    key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    resource_type = models.CharField(max_length=13)
    resource_id = models.UUIDField()
    job = models.ForeignKey(Job, on_delete=models.PROTECT)
    response_status = models.PositiveSmallIntegerField(default=202)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "route", "key"], name="unique_idempotency_key"),
        ]
