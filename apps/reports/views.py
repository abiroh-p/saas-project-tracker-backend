from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from config.query_params import QueryParamError
from config.responses import api_error

from .params import MAX_REPORT_DATE, MIN_REPORT_DATE, get_trend_params
from .serializers import (
    AssigneeWorkloadSerializer,
    PriorityDistributionSerializer,
    ProjectOverviewSerializer,
    ReportErrorSerializer,
    StatusDistributionSerializer,
    TrendsSerializer,
)
from .services.access import get_reportable_project
from .services.reports import (
    get_assignee_workload,
    get_priority_distribution,
    get_project_overview,
    get_status_distribution,
)
from .services.trends import MAX_RANGE_DAYS, get_trends

_POPULATION = (
    'Counts non-archived issues of the project. Available to any member of a '
    'non-archived project (viewers included). Responds 401 when the request '
    'is not authenticated and 404 with code `not_found` when the project does '
    'not exist, is archived, or the caller is not a member (the cases are '
    'deliberately indistinguishable). Read-only: no activity is recorded.'
)

_ERRORS = {
    401: ReportErrorSerializer,
    404: ReportErrorSerializer,
}


class ProjectReportView(APIView):
    """Shared behaviour of every report: authentication and project access.

    Subclasses implement ``build_report``; the project is resolved from the
    path and the authenticated user only, never from client-supplied identity.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, project_id):
        project = get_reportable_project(project_id, request.user)

        if project is None:
            return api_error(
                'Project not found.',
                'not_found',
                status.HTTP_404_NOT_FOUND,
            )

        return self.build_report(request, project)

    def build_report(self, request, project):
        raise NotImplementedError


@extend_schema_view(
    get=extend_schema(
        operation_id='project_report_overview',
        description=(
            'Progress metrics for one project. `open_issues` counts TODO, '
            '`in_progress_issues` counts IN_PROGRESS and IN_REVIEW, and '
            '`completed_issues` counts DONE. Overdue means not DONE with a '
            'due date before today (server timezone). '
            f'{_POPULATION}'
        ),
        responses={200: ProjectOverviewSerializer, **_ERRORS},
    ),
)
class ProjectOverviewReportView(ProjectReportView):

    def build_report(self, request, project):
        return Response(get_project_overview(project))


@extend_schema_view(
    get=extend_schema(
        operation_id='project_report_status_distribution',
        description=(
            'Issue count per status, in the order of the status choices. '
            'Every declared status is present, with 0 when unused; '
            f'`other_count` holds any undeclared legacy value. {_POPULATION}'
        ),
        responses={200: StatusDistributionSerializer, **_ERRORS},
    ),
)
class StatusDistributionReportView(ProjectReportView):

    def build_report(self, request, project):
        return Response(get_status_distribution(project))


@extend_schema_view(
    get=extend_schema(
        operation_id='project_report_priority_distribution',
        description=(
            'Issue count per priority, from lowest to highest priority. '
            'Every declared priority is present, with 0 when unused; '
            f'`other_count` holds any undeclared legacy value. {_POPULATION}'
        ),
        responses={200: PriorityDistributionSerializer, **_ERRORS},
    ),
)
class PriorityDistributionReportView(ProjectReportView):

    def build_report(self, request, project):
        return Response(get_priority_distribution(project))


@extend_schema_view(
    get=extend_schema(
        operation_id='project_report_assignee_workload',
        description=(
            'Issue counts per assignee, busiest first. Only `assignee_id`, '
            '`username` and `full_name` are exposed for each user. Issues '
            'with no assignee form one group with `assignee_id` null, listed '
            f'last and present only when such issues exist. {_POPULATION}'
        ),
        responses={200: AssigneeWorkloadSerializer, **_ERRORS},
    ),
)
class AssigneeWorkloadReportView(ProjectReportView):

    def build_report(self, request, project):
        return Response(get_assignee_workload(project))


@extend_schema_view(
    get=extend_schema(
        operation_id='project_report_trends',
        description=(
            'Issues created and completed per day or week. Dates are '
            'inclusive calendar dates in the server timezone. '
            '`created_count` uses the issue creation time; `completed_count` '
            'counts the recorded transitions to DONE (never `updated_at`). '
            'Every period in the range is present, with zeros when empty; '
            'weeks start on Monday and are labelled by that Monday. '
            'An invalid or missing parameter returns 400 with code '
            f'`bad_request`. {_POPULATION}'
        ),
        parameters=[
            OpenApiParameter(
                name='date_from',
                type=str,
                required=True,
                description=(
                    'First day, `YYYY-MM-DD`, inclusive. Between '
                    f'{MIN_REPORT_DATE.isoformat()} and '
                    f'{MAX_REPORT_DATE.isoformat()}.'
                ),
            ),
            OpenApiParameter(
                name='date_to',
                type=str,
                required=True,
                description=(
                    'Last day, `YYYY-MM-DD`, inclusive. Must not be before '
                    f'`date_from`; the range is at most {MAX_RANGE_DAYS} '
                    f'days. Between {MIN_REPORT_DATE.isoformat()} and '
                    f'{MAX_REPORT_DATE.isoformat()}.'
                ),
            ),
            OpenApiParameter(
                name='interval',
                type=str,
                required=False,
                enum=['day', 'week'],
                default='day',
                description='Size of each period.',
            ),
        ],
        responses={
            200: TrendsSerializer,
            400: ReportErrorSerializer,
            **_ERRORS,
        },
    ),
)
class TrendsReportView(ProjectReportView):

    def build_report(self, request, project):
        try:
            params = get_trend_params(request.query_params)
        except QueryParamError as exc:
            return api_error(
                str(exc),
                'bad_request',
                status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            get_trends(
                project,
                date_from=params.date_from,
                date_to=params.date_to,
                interval=params.interval,
            )
        )
