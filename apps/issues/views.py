from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .pagination import IssuePagination

from config.responses import api_error

from apps.projects.models import Project
from apps.projects.services.membership import (
    get_project_membership,
)

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

    @extend_schema(parameters=[OpenApiParameter('status', str), OpenApiParameter('priority', str), OpenApiParameter('issue_type', str), OpenApiParameter('assignee', int), OpenApiParameter('page', int), OpenApiParameter('page_size', int)], responses=IssueSerializer(many=True))
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

        status_filter = request.query_params.get('status')
        priority_filter = request.query_params.get('priority')
        issue_type_filter = request.query_params.get('issue_type')
        assignee_filter = request.query_params.get('assignee')

        valid_statuses = {
            choice[0]
            for choice in Issue.Status.choices
        }

        valid_priorities = {
            choice[0]
            for choice in Issue.Priority.choices
        }

        valid_issue_types = {
            choice[0]
            for choice in Issue.IssueType.choices
        }

        if status_filter and status_filter not in valid_statuses:
            return api_error(
                'Invalid status filter.',
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        if priority_filter and priority_filter not in valid_priorities:
            return api_error(
                'Invalid priority filter.',
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        if issue_type_filter and issue_type_filter not in valid_issue_types:
            return api_error(
                'Invalid issue type filter.',
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        if assignee_filter:
            try:
                assignee_id = int(assignee_filter)
            except (TypeError, ValueError):
                return api_error(
                    'Invalid assignee filter.',
                    'bad_request',
                    status.HTTP_400_BAD_REQUEST,
                )
        else:
            assignee_id = None

        if status_filter:
            issues = issues.filter(status=status_filter)

        if priority_filter:
            issues = issues.filter(priority=priority_filter)

        if issue_type_filter:
            issues = issues.filter(issue_type=issue_type_filter)

        if assignee_id is not None:
            issues = issues.filter(assignee_id=assignee_id)

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

        serializer = IssueSerializer(
            data=request.data,
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
