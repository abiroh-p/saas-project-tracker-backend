from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Project
from .serializers import ProjectSerializer
from .services.project import (
    archive_project,
    create_project,
    update_project,
)


class ProjectListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        projects = Project.objects.filter(
            is_archived=False
        ).order_by('-created_at')

        serializer = ProjectSerializer(
            projects,
            many=True,
        )

        return Response(serializer.data)

    def post(self, request):
        serializer = ProjectSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        project = create_project(
            validated_data=serializer.validated_data,
            user=request.user,
        )

        response_serializer = ProjectSerializer(project)

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )


class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, project_id):
        return Project.objects.get(
            id=project_id,
            is_archived=False,
        )

    def get(self, request, project_id):
        try:
            project = self.get_object(project_id)
        except Project.DoesNotExist:
            return Response(
                {'detail': 'Project not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ProjectSerializer(project)

        return Response(serializer.data)

    def patch(self, request, project_id):
        try:
            project = self.get_object(project_id)
        except Project.DoesNotExist:
            return Response(
                {'detail': 'Project not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ProjectSerializer(
            project,
            data=request.data,
            partial=True,
        )

        serializer.is_valid(raise_exception=True)

        project = update_project(
            project=project,
            validated_data=serializer.validated_data,
        )

        response_serializer = ProjectSerializer(project)

        return Response(response_serializer.data)



class ProjectArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, project_id):
        try:
            project = Project.objects.get(
                id=project_id,
                is_archived=False,
            )
        except Project.DoesNotExist:
            return Response(
                {'detail': 'Project not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        archive_project(project=project)

        return Response(
            {
                'message': 'Project archived successfully.',
            },
            status=status.HTTP_200_OK,
        )