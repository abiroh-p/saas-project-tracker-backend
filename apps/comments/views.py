from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.issues.models import Issue
from config.responses import api_error
from config.schema import paginated

from .models import Comment
from .pagination import CommentPagination
from .serializers import CommentInputSerializer, CommentSerializer
from .services.comment import create_comment

COMMENT_PAGE = paginated(CommentSerializer)


def get_issue(issue_id, user):
    """The issue, if the user belongs to its project. Same lookup (and so the
    same 404s) as the issue endpoints, including for archived projects."""
    return get_object_or_404(
        Issue.objects
        .select_related('project')
        .filter(
            id=issue_id,
            project__members__user=user,
            project__is_archived=False,
        )
    )


def get_comment(issue, comment_id):
    return get_object_or_404(
        Comment.objects.select_related('author', 'issue__project'),
        id=comment_id,
        issue=issue,
    )


def _error_response(exc):
    if isinstance(exc, PermissionError):
        return api_error(
            str(exc),
            'permission_denied',
            status.HTTP_403_FORBIDDEN,
        )

    return api_error(
        str(exc),
        'bad_request',
        status.HTTP_400_BAD_REQUEST,
    )


class IssueCommentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id='issue_comment_list',
        parameters=[
            OpenApiParameter(name='page', type=int, required=False),
            OpenApiParameter(name='page_size', type=int, required=False),
        ],
        responses=COMMENT_PAGE,
    )
    def get(self, request, issue_id):
        issue = get_issue(issue_id, request.user)

        paginator = CommentPagination()
        page = paginator.paginate_queryset(
            issue.comments.select_related('author'),
            request,
            view=self,
        )

        return paginator.get_paginated_response(
            CommentSerializer(page, many=True).data
        )

    @extend_schema(
        operation_id='issue_comment_create',
        request=CommentInputSerializer,
        responses={201: CommentSerializer},
    )
    def post(self, request, issue_id):
        issue = get_issue(issue_id, request.user)

        serializer = CommentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            comment = create_comment(
                issue=issue,
                user=request.user,
                body=serializer.validated_data['body'],
            )
        except (PermissionError, ValueError) as exc:
            return _error_response(exc)

        return Response(
            CommentSerializer(comment).data,
            status=status.HTTP_201_CREATED,
        )


class IssueCommentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id='issue_comment_retrieve',
        responses=CommentSerializer,
    )
    def get(self, request, issue_id, comment_id):
        issue = get_issue(issue_id, request.user)
        comment = get_comment(issue, comment_id)

        return Response(CommentSerializer(comment).data)
