from django.urls import path

from .views import IssueCommentDetailView, IssueCommentListCreateView

urlpatterns = [
    path(
        'issues/<int:issue_id>/comments/',
        IssueCommentListCreateView.as_view(),
        name='issue-comment-list',
    ),
    path(
        'issues/<int:issue_id>/comments/<int:comment_id>/',
        IssueCommentDetailView.as_view(),
        name='issue-comment-detail',
    ),
]
