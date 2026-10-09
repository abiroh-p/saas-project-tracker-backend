from django.urls import path
from apps.issues.views import ProjectIssueListCreateView

from .views import (
    ProjectArchiveView,
    ProjectDetailView,
    ProjectListCreateView,
    ProjectMemberDetailView,
    ProjectMemberListCreateView,
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
        '<int:project_id>/members/',
        ProjectMemberListCreateView.as_view(),
        name='project-member-list-create',
    ),
    path(
        '<int:project_id>/members/<int:member_id>/',
        ProjectMemberDetailView.as_view(),
        name='project-member-detail',
    ),
    path(
        '<int:project_id>/issues/',
        ProjectIssueListCreateView.as_view(),
        name='project-issue-list-create',
),
]
