from django.urls import path

from .views import IssueActivityListView, ProjectActivityListView

urlpatterns = [
    path(
        'projects/<int:project_id>/activity/',
        ProjectActivityListView.as_view(),
        name='project-activity-list',
    ),
    path(
        'issues/<int:issue_id>/activity/',
        IssueActivityListView.as_view(),
        name='issue-activity-list',
    ),
]
