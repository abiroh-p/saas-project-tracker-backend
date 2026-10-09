from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from config.responses import api_error

from .models import Project, ProjectMember
from .serializers import (
    AddProjectMemberSerializer,
    ProjectMemberSerializer,
    ProjectSerializer,
    UpdateProjectMemberRoleSerializer,
)
from .services.membership import (
    add_project_member,
    change_member_role,
    get_project_membership,
    is_project_manager,
    remove_project_member,
)

from .services.project import (
    archive_project,
    create_project,
    update_project,
)


class ProjectListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ProjectSerializer(many=True))
    def get(self, request):
        projects = Project.objects.filter(
            members__user=request.user,
            is_archived=False,
        ).distinct().order_by('-created_at').prefetch_related('members')

        serializer = ProjectSerializer(
            projects,
            many=True,
            context={'request': request},
        )

        return Response(serializer.data)

    @extend_schema(request=ProjectSerializer, responses={201: ProjectSerializer})
    def post(self, request):
        serializer = ProjectSerializer(
            data=request.data,
            context={'request': request},
        )

        serializer.is_valid(raise_exception=True)

        project = create_project(
            validated_data=serializer.validated_data,
            user=request.user,
        )

        response_serializer = ProjectSerializer(project, context={'request': request})

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )


class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, project_id, user):
        return Project.objects.get(
            id=project_id,
            members__user=user,
            is_archived=False,
        )

    @extend_schema(responses=ProjectSerializer)
    def get(self, request, project_id):
        try:
            project = self.get_object(
                project_id,
                request.user,
            )
        except Project.DoesNotExist:
            return api_error(
                'Project not found.',
                'not_found',
                status.HTTP_404_NOT_FOUND,
            )

        serializer = ProjectSerializer(project, context={'request': request})

        return Response(serializer.data)

    @extend_schema(request=ProjectSerializer, responses=ProjectSerializer)
    def patch(self, request, project_id):
        try:
            project = self.get_object(
                project_id,
                request.user,
            )
        except Project.DoesNotExist:
            return api_error(
                'Project not found.',
                'not_found',
                status.HTTP_404_NOT_FOUND,
            )

        if not is_project_manager(
            project=project,
            user=request.user,
        ):
            return api_error(
                'Only project managers can update a project.',
                'permission_denied',
                status.HTTP_403_FORBIDDEN,
            )

        serializer = ProjectSerializer(
            project,
            data=request.data,
            partial=True,
            context={'request': request},
        )

        serializer.is_valid(raise_exception=True)

        project = update_project(
            project=project,
            validated_data=serializer.validated_data,
        )

        response_serializer = ProjectSerializer(project, context={'request': request})

        return Response(response_serializer.data)


class ProjectArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, project_id):
        try:
            project = Project.objects.get(
                id=project_id,
                members__user=request.user,
                is_archived=False,
            )
        except Project.DoesNotExist:
            return api_error(
                'Project not found.',
                'not_found',
                status.HTTP_404_NOT_FOUND,
            )

        if not is_project_manager(
            project=project,
            user=request.user,
        ):
            return api_error(
                'Only project managers can archive a project.',
                'permission_denied',
                status.HTTP_403_FORBIDDEN,
            )

        archive_project(project=project)

        return Response(
            {
                'message': 'Project archived successfully.',
            },
            status=status.HTTP_200_OK,
        )


def _get_member_project(project_id, user):
    return get_object_or_404(
        Project.objects.filter(
            id=project_id,
            members__user=user,
            is_archived=False,
        ).distinct()
    )


class ProjectMemberListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ProjectMemberSerializer(many=True))
    def get(self, request, project_id):
        project = _get_member_project(project_id, request.user)

        members = (
            ProjectMember.objects
            .filter(project=project)
            .select_related('user')
            .order_by('created_at', 'id')
        )

        return Response(
            ProjectMemberSerializer(members, many=True).data
        )

    @extend_schema(request=AddProjectMemberSerializer, responses={201: ProjectMemberSerializer})
    def post(self, request, project_id):
        project = _get_member_project(project_id, request.user)

        if not is_project_manager(project=project, user=request.user):
            return api_error(
                'Only project managers can add members.',
                'permission_denied',
                status.HTTP_403_FORBIDDEN,
            )

        serializer = AddProjectMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            membership = add_project_member(
                project=project,
                user_id=serializer.validated_data['user_id'],
                role=serializer.validated_data['role'],
            )
        except ValueError as exc:
            return api_error(
                str(exc),
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            ProjectMemberSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )


class ProjectMemberDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_membership(self, project, member_id):
        return get_object_or_404(
            ProjectMember.objects.select_related('user', 'project'),
            id=member_id,
            project=project,
        )

    @extend_schema(request=UpdateProjectMemberRoleSerializer, responses=ProjectMemberSerializer)
    def patch(self, request, project_id, member_id):
        project = _get_member_project(project_id, request.user)

        if not is_project_manager(project=project, user=request.user):
            return api_error(
                'Only project managers can change roles.',
                'permission_denied',
                status.HTTP_403_FORBIDDEN,
            )

        membership = self.get_membership(project, member_id)

        serializer = UpdateProjectMemberRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            membership = change_member_role(
                membership=membership,
                role=serializer.validated_data['role'],
            )
        except ValueError as exc:
            return api_error(
                str(exc),
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        return Response(ProjectMemberSerializer(membership).data)

    @extend_schema(responses={204: None})
    def delete(self, request, project_id, member_id):
        project = _get_member_project(project_id, request.user)
        membership = self.get_membership(project, member_id)

        requester = get_project_membership(
            project=project,
            user=request.user,
        )
        is_self = membership.user_id == request.user.id
        is_manager = (
            requester.role == ProjectMember.Role.PROJECT_MANAGER
        )

        if not is_manager and not is_self:
            return api_error(
                'Only project managers can remove other members.',
                'permission_denied',
                status.HTTP_403_FORBIDDEN,
            )

        try:
            remove_project_member(membership=membership)
        except ValueError as exc:
            return api_error(
                str(exc),
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)
