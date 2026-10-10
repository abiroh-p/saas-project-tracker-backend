from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.projects.models import Project
from config.responses import api_error
from config.schema import paginated

from .models import Activity
from .pagination import ActivityPagination
from .serializers import ActivityFilterSerializer, ActivitySerializer


class ProjectActivityListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id='project_activity_list',
        parameters=[
            OpenApiParameter(
                name='action',
                type=str,
                required=False,
                enum=[value for value, _ in Activity.Action.choices],
            ),
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
            ),
        ],
        responses=paginated(ActivitySerializer),
    )
    def get(self, request, project_id):
        project = (
            Project.objects
            .filter(
                id=project_id,
                members__user=request.user,
                is_archived=False,
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

        activities = (
            Activity.objects
            .filter(project=project)
            .select_related('user')
            .order_by('-created_at', '-id')
        )

        if filters.validated_data.get('action'):
            activities = activities.filter(
                action=filters.validated_data['action'],
            )

        if filters.validated_data.get('entity_type'):
            activities = activities.filter(
                entity_type=filters.validated_data['entity_type'],
            )

        if filters.validated_data.get('entity_id'):
            activities = activities.filter(
                entity_id=filters.validated_data['entity_id'],
            )

        paginator = ActivityPagination()
        page = paginator.paginate_queryset(
            activities,
            request,
            view=self,
        )
        serializer = ActivitySerializer(page, many=True)

        return paginator.get_paginated_response(serializer.data)
