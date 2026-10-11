from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status

from apps.issues.models import Issue
from apps.reports.serializers import ProjectOverviewSerializer
from apps.reports.services.reports import (
    COMPLETED_STATUSES,
    IN_PROGRESS_STATUSES,
    OPEN_STATUSES,
    completion_rate,
)

from ..testing import (
    TODAY,
    TOMORROW,
    YESTERDAY,
    ReportsTestCase,
    Status,
)


class OverviewTests(ReportsTestCase):

    def setUp(self):
        super().setUp()
        patcher = patch(
            'apps.reports.services.reports.timezone.localdate',
            return_value=TODAY,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, project=None):
        project = project or self.project
        return self.client.get(
            f'/api/v1/projects/{project.pk}/reports/overview/',
        )

    def test_response_matches_the_documented_shape(self):
        response = self.get()

        self.assertEqual(
            set(response.data), set(ProjectOverviewSerializer().fields),
        )

    def test_identifies_the_project(self):
        response = self.get()

        self.assertEqual(response.data['project_id'], self.project.pk)
        self.assertEqual(response.data['project_key'], 'ALPHA')

    def test_counts_a_mixture_of_statuses(self):
        for _ in range(2):
            self.make_issue(status=Status.TODO)
        self.make_issue(status=Status.IN_PROGRESS)
        self.make_issue(status=Status.IN_REVIEW)
        for _ in range(3):
            self.make_issue(status=Status.DONE)

        data = self.get().data

        self.assertEqual(data['total_issues'], 7)
        self.assertEqual(data['open_issues'], 2)
        self.assertEqual(data['in_progress_issues'], 2)
        self.assertEqual(data['completed_issues'], 3)

    def test_categories_add_up_to_the_total(self):
        for status_value in Status.values:
            self.make_issue(status=status_value)

        data = self.get().data

        self.assertEqual(
            data['open_issues']
            + data['in_progress_issues']
            + data['completed_issues'],
            data['total_issues'],
        )

    def test_every_declared_status_belongs_to_exactly_one_category(self):
        # Fails when a status is added to the model without deciding which
        # report category it belongs to.
        categories = [OPEN_STATUSES, IN_PROGRESS_STATUSES, COMPLETED_STATUSES]
        categorised = [value for group in categories for value in group]

        self.assertCountEqual(categorised, Status.values)

    def test_archived_issues_are_excluded(self):
        self.make_issue()
        self.make_issue(is_archived=True)
        self.make_issue(is_archived=True, status=Status.DONE)

        data = self.get().data

        self.assertEqual(data['total_issues'], 1)
        self.assertEqual(data['completed_issues'], 0)

    def test_unassigned_issues_are_counted(self):
        self.make_issue(assignee=None)
        self.make_issue(assignee=None)
        self.make_issue(assignee=self.member)

        self.assertEqual(self.get().data['unassigned_issues'], 2)

    def test_overdue_uses_local_date_and_ignores_completed_work(self):
        self.make_issue(due_date=YESTERDAY)                       # overdue
        self.make_issue(due_date=YESTERDAY, status=Status.IN_REVIEW)  # overdue
        self.make_issue(due_date=YESTERDAY, status=Status.DONE)   # completed
        self.make_issue(due_date=TODAY)                           # due today
        self.make_issue(due_date=TOMORROW)                        # future
        self.make_issue(due_date=None)                            # no date

        self.assertEqual(self.get().data['overdue_issues'], 2)

    def test_completion_rate_is_a_percentage_with_one_decimal(self):
        self.make_issue(status=Status.DONE)
        self.make_issue()
        self.make_issue()

        self.assertEqual(self.get().data['completion_rate'], 33.3)

    def test_completion_rate_rounds_half_up(self):
        self.assertEqual(completion_rate(1, 16), 6.3)    # 6.25
        self.assertEqual(completion_rate(1, 8), 12.5)
        self.assertEqual(completion_rate(2, 3), 66.7)
        self.assertEqual(completion_rate(3, 3), 100.0)

    def test_empty_project_is_all_zero_without_division_error(self):
        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in (
            'total_issues',
            'open_issues',
            'in_progress_issues',
            'completed_issues',
            'overdue_issues',
            'unassigned_issues',
        ):
            self.assertEqual(response.data[key], 0, key)
        self.assertEqual(response.data['completion_rate'], 0.0)

    def test_other_projects_issues_do_not_count(self):
        self.make_issue()
        self.make_issue(project=self.other_project)
        self.make_issue(project=self.other_project, status=Status.DONE)

        data = self.get().data

        self.assertEqual(data['total_issues'], 1)
        self.assertEqual(data['completed_issues'], 0)

    def test_a_legacy_status_counts_in_the_total_only(self):
        issue = self.make_issue()
        Issue.objects.filter(pk=issue.pk).update(status='LEGACY')

        data = self.get().data

        self.assertEqual(data['total_issues'], 1)
        self.assertEqual(
            data['open_issues']
            + data['in_progress_issues']
            + data['completed_issues'],
            0,
        )

    def test_uses_a_constant_number_of_queries(self):
        for _ in range(10):
            self.make_issue(assignee=self.member)

        with CaptureQueriesContext(connection) as queries:
            self.get()

        # Project access check + one aggregate, whatever the issue count.
        self.assertEqual(len(queries), 2)

