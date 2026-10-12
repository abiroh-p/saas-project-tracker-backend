from django.urls import path

from .views import (
    IssueListView,
    IssueArchiveView,
    IssueDetailView,
    IssueTransitionView,
)

urlpatterns = [
    path(
        '',
        IssueListView.as_view(),
        name='issue-list',
    ),
    path(
        '<int:issue_id>/',
        IssueDetailView.as_view(),
        name='issue-detail',
    ),
    path(
        '<int:issue_id>/archive/',
        IssueArchiveView.as_view(),
        name='issue-archive',
    ),
    path(
        '<int:issue_id>/transition/',
        IssueTransitionView.as_view(),
        name='issue-transition',
    ),
]