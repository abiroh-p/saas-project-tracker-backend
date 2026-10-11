from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import DashboardIssueSerializer, DashboardSerializer
from .services.dashboard import get_dashboard_summary


class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id='dashboard_retrieve',
        description=(
            'Summary of the authenticated user\'s projects and assigned '
            'work. The owner is always the authenticated user; the endpoint '
            'takes no parameters.\n\n'
            'Archived issues, archived projects and projects the user is no '
            'longer a member of are excluded everywhere. An issue is overdue '
            'when it is not DONE and its due date is before today (server '
            'timezone); an issue due today is not overdue. `recent_issues` '
            'holds up to 5 of the user\'s assigned issues, most recently '
            'updated first.\n\n'
            'Responds 401 when the request is not authenticated.'
        ),
        responses=DashboardSerializer,
    )
    def get(self, request):
        data = get_dashboard_summary(request.user)

        data['recent_issues'] = DashboardIssueSerializer(
            data['recent_issues'],
            many=True,
        ).data

        return Response(data)
