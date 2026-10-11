from django.urls import path

from .views import (
    AssigneeWorkloadReportView,
    PriorityDistributionReportView,
    ProjectOverviewReportView,
    StatusDistributionReportView,
    TrendsReportView,
)

# Mounted under ``api/v1/``, next to the other project-scoped feeds.
urlpatterns = [
    path(
        'projects/<int:project_id>/reports/overview/',
        ProjectOverviewReportView.as_view(),
        name='project-report-overview',
    ),
    path(
        'projects/<int:project_id>/reports/status-distribution/',
        StatusDistributionReportView.as_view(),
        name='project-report-status-distribution',
    ),
    path(
        'projects/<int:project_id>/reports/priority-distribution/',
        PriorityDistributionReportView.as_view(),
        name='project-report-priority-distribution',
    ),
    path(
        'projects/<int:project_id>/reports/assignee-workload/',
        AssigneeWorkloadReportView.as_view(),
        name='project-report-assignee-workload',
    ),
    path(
        'projects/<int:project_id>/reports/trends/',
        TrendsReportView.as_view(),
        name='project-report-trends',
    ),
]
