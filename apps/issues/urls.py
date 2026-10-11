from django.urls import path

from .views import (
    IssueCommentDetailView,
    IssueCommentListCreateView,
    IssueArchiveView,
    IssueDetailView,
    IssueTransitionView,
)

urlpatterns = [
    path(
        '<int:issue_id>/comments/',
        IssueCommentListCreateView.as_view(),
        name='issue-comment-list-create',
    ),
    path(
        '<int:issue_id>/comments/<int:comment_id>/',
        IssueCommentDetailView.as_view(),
        name='issue-comment-detail',
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
