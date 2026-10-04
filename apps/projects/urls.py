from django.urls import path
from apps.issues.views import ProjectIssueListCreateView

from .views import (
    ProjectArchiveView,
    ProjectDetailView,
    ProjectListCreateView,
)

urlpatterns = [
    path(
        '',
        ProjectListCreateView.as_view(),
        name='project-list-create',
    ),
    path(
        '<int:project_id>/',
        ProjectDetailView.as_view(),
        name='project-detail',
    ),

    path(
        '<int:project_id>/archive/',
        ProjectArchiveView.as_view(),
        name='project-archive',
    ),
    path(
        '<int:project_id>/issues/',
        ProjectIssueListCreateView.as_view(),
        name='project-issue-list-create',
),
]
