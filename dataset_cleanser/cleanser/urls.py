from django.urls import path

from auth_app import views as auth

from . import views
from .catalog import CapabilitiesView

urlpatterns = [
    path("capabilities", CapabilitiesView.as_view(), name="capabilities"),
    path("auth/csrf", auth.CSRFView.as_view(), name="csrf"),
    path("auth/register", auth.RegisterView.as_view(), name="register"),
    path("auth/login", auth.LoginView.as_view(), name="login"),
    path("auth/logout", auth.LogoutView.as_view(), name="logout"),
    path("auth/me", auth.MeView.as_view(), name="me"),
    path("auth/password/forgot", auth.ForgotView.as_view(), name="password-forgot"),
    path("auth/password/reset", auth.ResetView.as_view(), name="password-reset"),
    path("dashboard", views.DashboardView.as_view(), name="dashboard"),
    path("uploads", views.UploadsView.as_view(), name="uploads"),
    path("projects", views.ProjectsView.as_view(), name="projects"),
    path("projects/<uuid:project_id>", views.ProjectView.as_view(), name="project"),
    path("projects/<uuid:project_id>/datasets", views.ProjectDatasetsView.as_view(), name="project-datasets"),
    path("projects/<uuid:project_id>/audit-events", views.ProjectAuditView.as_view(), name="project-audit"),
    path("datasets/<uuid:dataset_id>", views.DatasetView.as_view(), name="dataset"),
    path("datasets/<uuid:dataset_id>/versions", views.VersionsView.as_view(), name="versions"),
    path("versions/<uuid:version_id>", views.VersionView.as_view(), name="version"),
    path("versions/<uuid:version_id>/rows", views.RowsView.as_view(), name="rows"),
    path("versions/<uuid:version_id>/rows/<str:row_index>/cells/<uuid:column_id>", views.CellView.as_view(), name="cell"),
    path("versions/<uuid:version_id>/download", views.DownloadView.as_view(), name="download"),
    path("versions/<uuid:version_id>/check-configuration", views.ConfigurationView.as_view(), name="check-configuration"),
    path("versions/<uuid:version_id>/checks", views.ChecksView.as_view(), name="checks"),
    path("checks/<uuid:check_id>", views.CheckView.as_view(), name="check"),
    path("versions/<uuid:version_id>/quality-summary", views.QualitySummaryView.as_view(), name="quality-summary"),
    path("checks/<uuid:check_id>/column-summary", views.ColumnSummaryView.as_view(), name="column-summary"),
    path("checks/<uuid:check_id>/issues", views.IssuesView.as_view(), name="issues"),
    path("datasets/<uuid:dataset_id>/cleanings", views.CleaningsView.as_view(), name="cleanings"),
    path("cleanings/<uuid:cleaning_id>", views.CleaningView.as_view(), name="cleaning"),
    path("datasets/<uuid:dataset_id>/audit-events", views.DatasetAuditView.as_view(), name="dataset-audit"),
    path("jobs/<uuid:job_id>", views.JobView.as_view(), name="job"),
    path("jobs/<uuid:job_id>/retry", views.RetryView.as_view(), name="job-retry"),
]
