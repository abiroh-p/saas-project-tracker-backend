from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.issues.models import Issue
from apps.projects.models import Project
from config.responses import api_error
from config.schema import paginated

from .models import Activity
from .pagination import ActivityPagination
from .serializers import (
    ActivityFilterSerializer,
    ActivitySerializer,
    IssueActivityFilterSerializer,
)

# Built once so both feeds share one schema component.
ACTIVITY_PAGE = paginated(ActivitySerializer)

PAGINATION_PARAMETERS = [
    OpenApiParameter(name='page', type=int, required=False),
    OpenApiParameter(name='page_size', type=int, required=False),
]

ACTION_PARAMETER = OpenApiParameter(
    name='action',
    type=str,
    required=False,
    enum=[value for value, _ in Activity.Action.choices],
)

USER_PARAMETER = OpenApiParameter(
    name='user',
    type=int,
    required=False,
    description='Id of the user who performed the action.',
)


def _apply_filters(activities, filters):
    data = filters.validated_data

    if data.get('action'):
        activities = activities.filter(action=data['action'])

    if data.get('entity_type'):
        activities = activities.filter(entity_type=data['entity_type'])

    if data.get('entity_id'):
        activities = activities.filter(entity_id=data['entity_id'])

    if data.get('user'):
        activities = activities.filter(user_id=data['user'])

    return activities


def _paginated_response(view, request, activities):
    paginator = ActivityPagination()
    page = paginator.paginate_queryset(
        activities.select_related('user').order_by('-created_at', '-id'),
        request,
        view=view,
    )

    return paginator.get_paginated_response(
        ActivitySerializer(page, many=True).data
    )


class ProjectActivityListView(APIView):
    """Read-only history of a project. Any current member may read it,
    including viewers, members who joined later, and archived projects."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id='project_activity_list',
        parameters=[
            ACTION_PARAMETER,
            OpenApiParameter(
                name='entity_type',
                type=str,
                required=False,
                enum=[value for value, _ in Activity.EntityType.choices],
            ),
            OpenApiParameter(
                name='entity_id',
                type=int,
                required=False,
                description='Requires entity_type.',
            ),
            USER_PARAMETER,
            *PAGINATION_PARAMETERS,
        ],
        responses=ACTIVITY_PAGE,
    )
    def get(self, request, project_id):
        project = (
            Project.objects
            .filter(
                id=project_id,
                members__user=request.user,
            )
            .first()
        )

        if project is None:
            return api_error(
                'Project not found.',
                'not_found',
                status.HTTP_404_NOT_FOUND,
            )

        filters = ActivityFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)

        activities = _apply_filters(
            Activity.objects.filter(project=project),
            filters,
        )

        return _paginated_response(self, request, activities)


class IssueActivityListView(APIView):
    """Read-only history of one issue. Access follows the parent project's
    membership, so non-members get the same 404 as for a missing issue."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id='issue_activity_list',
        parameters=[
            ACTION_PARAMETER,
            USER_PARAMETER,
            *PAGINATION_PARAMETERS,
        ],
        responses=ACTIVITY_PAGE,
    )
    def get(self, request, issue_id):
        issue = (
            Issue.objects
            .filter(
                id=issue_id,
                project__members__user=request.user,
            )
            .select_related('project')
            .first()
        )

        if issue is None:
            return api_error(
                'Issue not found.',
                'not_found',
                status.HTTP_404_NOT_FOUND,
            )

        filters = IssueActivityFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)

        activities = _apply_filters(
            Activity.objects.filter(
                project=issue.project,
                entity_type=Activity.EntityType.ISSUE,
                entity_id=issue.id,
            ),
            filters,
        )

        return _paginated_response(self, request, activities)
