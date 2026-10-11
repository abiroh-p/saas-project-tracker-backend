from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .pagination import IssuePagination

from config.query_params import QueryParamError, SEARCH_MAX_LENGTH
from config.responses import api_error
from config.schema import paginated

from apps.projects.models import Project
from apps.projects.services.membership import (
    get_project_membership,
)

from .filters import ORDERING_CHOICES, apply_issue_filters
from .models import Issue
from .serializers import (
    IssueSerializer,
    IssueTransitionSerializer,
)
from .services.issue import (
    create_issue,
    update_issue,
    archive_issue,
    transition_issue,
)


_BAD_REQUEST = 'An invalid value returns 400 with code `bad_request`.'

ISSUE_LIST_PARAMETERS = [
    OpenApiParameter(
        name='search',
        type=str,
        required=False,
        description=(
            'Case-insensitive text search over the issue title and '
            'description, and over the issue key (an exact key such as '
            f'`API-12`). Up to {SEARCH_MAX_LENGTH} characters; an empty value '
            'means no search. Combined with the other filters using AND.'
        ),
    ),
    OpenApiParameter(
        name='status',
        type=str,
        required=False,
        enum=Issue.Status.values,
        description=f'Only issues with this status. {_BAD_REQUEST}',
    ),
    OpenApiParameter(
        name='priority',
        type=str,
        required=False,
        enum=Issue.Priority.values,
        description=f'Only issues with this priority. {_BAD_REQUEST}',
    ),
    OpenApiParameter(
        name='issue_type',
        type=str,
        required=False,
        enum=Issue.IssueType.values,
        description=f'Only issues of this type. {_BAD_REQUEST}',
    ),
    OpenApiParameter(
        name='assignee',
        type=int,
        required=False,
        description=(
            'Only issues assigned to the user with this id (a positive '
            f'integer). {_BAD_REQUEST}'
        ),
    ),
    OpenApiParameter(
        name='due_before',
        type=OpenApiTypes.DATE,
        required=False,
        description=(
            'Only issues due on or before this date (YYYY-MM-DD). Issues '
            f'without a due date are excluded. {_BAD_REQUEST}'
        ),
    ),
    OpenApiParameter(
        name='due_after',
        type=OpenApiTypes.DATE,
        required=False,
        description=(
            'Only issues due on or after this date (YYYY-MM-DD). Issues '
            'without a due date are excluded. It cannot be later than '
            f'`due_before`. {_BAD_REQUEST}'
        ),
    ),
    OpenApiParameter(
        name='ordering',
        type=str,
        required=False,
        enum=ORDERING_CHOICES,
        description=(
            'Sort field; prefix with `-` for descending. A single field '
            'only. Priority sorts by urgency, title ignores case, and '
            'issues without a due date always come last. Ties are broken by '
            'id. Defaults to newest first (`-created_at`). '
            f'{_BAD_REQUEST}'
        ),
    ),
    OpenApiParameter(
        name='page',
        type=int,
        required=False,
        description='Page number, starting at 1.',
    ),
    OpenApiParameter(
        name='page_size',
        type=int,
        required=False,
        description='Results per page (default 20, capped at 100).',
    ),
]


class ProjectIssueListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get_project(self, project_id, user):
        return get_object_or_404(
            Project.objects.filter(
                id=project_id,
                members__user=user,
                is_archived=False,
            ).distinct()
        )

    @extend_schema(
        parameters=ISSUE_LIST_PARAMETERS,
        responses=paginated(IssueSerializer),
    )
    def get(self, request, project_id):
        project = self.get_project(project_id, request.user)

        issues = (
            Issue.objects
            .filter(
                project=project,
                is_archived=False,
            )
            .select_related(
                'project',
                'reporter',
                'assignee',
            )
        )

        try:
            issues = apply_issue_filters(
                issues,
                request.query_params,
                project,
            )
        except QueryParamError as exc:
            return api_error(
                str(exc),
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        paginator = IssuePagination()
        page = paginator.paginate_queryset(
            issues,
            request,
            view=self,
        )

        serializer = IssueSerializer(page, many=True)

        return paginator.get_paginated_response(
            serializer.data
        )

    @extend_schema(request=IssueSerializer, responses={201: IssueSerializer})
    def post(self, request, project_id):
        project = self.get_project(
            project_id,
            request.user,
        )

        membership = get_project_membership(
            project=project,
            user=request.user,
        )

        if membership.role == membership.Role.VIEWER:
            return api_error(
                'Viewers cannot create issues.',
                'permission_denied',
                status.HTTP_403_FORBIDDEN,
            )

        # The project is needed to validate the due date against its dates.
        serializer = IssueSerializer(
            data=request.data,
            context={'project': project},
        )

        serializer.is_valid(
            raise_exception=True,
        )

        try:
            issue = create_issue(
                project=project,
                validated_data=serializer.validated_data,
                user=request.user,
            )
        except ValueError as exc:
            return api_error(
                str(exc),
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = IssueSerializer(issue)

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

class IssueDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, issue_id, user):
        return get_object_or_404(
            Issue.objects
            .select_related(
                'project',
                'reporter',
                'assignee',
            )
            .filter(
                id=issue_id,
                project__members__user=user,
                project__is_archived=False,
            )
        )

    @extend_schema(responses=IssueSerializer)
    def get(self, request, issue_id):
        issue = self.get_object(
            issue_id,
            request.user,
        )

        serializer = IssueSerializer(issue)

        return Response(serializer.data)

    @extend_schema(request=IssueSerializer, responses=IssueSerializer)
    def patch(self, request, issue_id):
        issue = self.get_object(
            issue_id,
            request.user,
        )

        serializer = IssueSerializer(
            issue,
            data=request.data,
            partial=True,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        try:
            issue = update_issue(
                issue=issue,
                validated_data=serializer.validated_data,
                user=request.user,
            )
        except PermissionError as exc:
            return api_error(
                str(exc),
                'permission_denied',
                status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return api_error(
                str(exc),
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = IssueSerializer(issue)

        return Response(response_serializer.data)

class IssueArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=IssueSerializer)
    def post(self, request, issue_id):
        issue = get_object_or_404(
            Issue.objects
            .select_related('project', 'reporter', 'assignee')
            .filter(
                id=issue_id,
                project__members__user=request.user,
                project__is_archived=False,
            )
        )

        try:
            issue = archive_issue(
                issue=issue,
                user=request.user,
            )
        except PermissionError as exc:
            return api_error(
                str(exc),
                'permission_denied',
                status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return api_error(
                str(exc),
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        serializer = IssueSerializer(issue)
        return Response(serializer.data)

class IssueTransitionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=IssueTransitionSerializer, responses=IssueSerializer)
    def post(self, request, issue_id):
        issue = get_object_or_404(
            Issue.objects
            .select_related('project', 'reporter', 'assignee')
            .filter(
                id=issue_id,
                project__members__user=request.user,
                project__is_archived=False,
            )
        )

        serializer = IssueTransitionSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            issue = transition_issue(
                issue=issue,
                user=request.user,
                new_status=serializer.validated_data['status'],
            )
        except PermissionError as exc:
            return api_error(
                str(exc),
                'permission_denied',
                status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return api_error(
                str(exc),
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = IssueSerializer(issue)

        return Response(response_serializer.data)
