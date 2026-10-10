from django.urls import path

from .views import ProjectActivityListView


urlpatterns = [
    path(
        'projects/<int:project_id>/activity/',
        ProjectActivityListView.as_view(),
        name='project-activity-list',
    ),
]
