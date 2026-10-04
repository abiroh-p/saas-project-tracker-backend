from django.urls import path

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
]