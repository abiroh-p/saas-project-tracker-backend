from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status

from apps.reports.serializers import AssigneeWorkloadItemSerializer

from ..testing import TODAY, YESTERDAY, ReportsTestCase, Status


class AssigneeWorkloadTests(ReportsTestCase):

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
            f'/api/v1/projects/{project.pk}/reports/assignee-workload/',
        )

    def by_username(self, response):
        return {row['username']: row for row in response.data['results']}

    def test_counts_per_assignee(self):
        self.make_issue(assignee=self.member, status=Status.TODO)
        self.make_issue(assignee=self.member, status=Status.IN_PROGRESS)
        self.make_issue(assignee=self.member, status=Status.IN_REVIEW)
        self.make_issue(assignee=self.member, status=Status.DONE)
        self.make_issue(
            assignee=self.member, status=Status.TODO, due_date=YESTERDAY,
        )
        self.make_issue(assignee=self.member2, status=Status.DONE)

        response = self.get()
        rows = self.by_username(response)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(rows['member']['assigned_issues'], 5)
        self.assertEqual(rows['member']['open_issues'], 2)
        self.assertEqual(rows['member']['in_progress_issues'], 2)
        self.assertEqual(rows['member']['completed_issues'], 1)
        self.assertEqual(rows['member']['overdue_issues'], 1)
        self.assertEqual(rows['member2']['assigned_issues'], 1)
        self.assertEqual(rows['member2']['completed_issues'], 1)
        self.assertEqual(response.data['total_issues'], 6)

    def test_identifies_the_assignee(self):
        self.make_issue(assignee=self.member)

        row = self.get().data['results'][0]

        self.assertEqual(row['assignee_id'], self.member.pk)
        self.assertEqual(row['username'], 'member')
        self.assertEqual(row['full_name'], 'Tom Member')

    def test_unassigned_issues_form_one_explicit_group_listed_last(self):
        self.make_issue(assignee=None)
        self.make_issue(assignee=None, due_date=YESTERDAY)
        self.make_issue(assignee=self.member)

        results = self.get().data['results']

        self.assertEqual(results[-1]['assignee_id'], None)
        self.assertEqual(results[-1]['username'], None)
        self.assertEqual(results[-1]['full_name'], None)
        self.assertEqual(results[-1]['assigned_issues'], 2)
        self.assertEqual(results[-1]['overdue_issues'], 1)
        self.assertEqual(
            [r['assignee_id'] for r in results if r['assignee_id'] is None],
            [None],
        )

    def test_unassigned_group_is_absent_when_everything_is_assigned(self):
        self.make_issue(assignee=self.member)

        self.assertNotIn(
            None,
            [row['assignee_id'] for row in self.get().data['results']],
        )

    def test_empty_project_returns_an_empty_list(self):
        response = self.get()

        self.assertEqual(response.data['results'], [])
        self.assertEqual(response.data['total_issues'], 0)

    def test_busiest_assignee_first_then_by_username(self):
        self.make_issue(assignee=self.member2)
        self.make_issue(assignee=self.member2)
        self.make_issue(assignee=self.member)
        self.make_issue(assignee=self.manager)

        usernames = [r['username'] for r in self.get().data['results']]

        self.assertEqual(usernames, ['member2', 'manager', 'member'])

    def test_total_equals_the_sum_of_all_groups(self):
        self.make_issue(assignee=self.member)
        self.make_issue(assignee=None)
        self.make_issue(assignee=self.member, is_archived=True)

        data = self.get().data

        self.assertEqual(
            data['total_issues'],
            sum(row['assigned_issues'] for row in data['results']),
        )
        self.assertEqual(data['total_issues'], 2)

    def test_only_public_user_fields_are_exposed(self):
        self.make_issue(assignee=self.member)

        response = self.get()
        row = response.data['results'][0]

        self.assertEqual(
            set(row), set(AssigneeWorkloadItemSerializer().fields),
        )
        self.assertNotIn('email', row)
        self.assertNotIn('member@example.com', str(response.data))

    def test_other_projects_assignees_and_counts_do_not_leak(self):
        self.make_issue(assignee=self.member)
        self.make_issue(assignee=self.outsider, project=self.other_project)

        response = self.get()

        self.assertEqual(
            [r['username'] for r in response.data['results']], ['member'],
        )
        self.assertNotIn('outsider', str(response.data))

    def test_archived_issues_are_excluded(self):
        self.make_issue(assignee=self.member, is_archived=True)

        self.assertEqual(self.get().data['results'], [])

    def test_query_count_does_not_grow_with_the_number_of_assignees(self):
        self.make_issue(assignee=self.member)

        with CaptureQueriesContext(connection) as few:
            self.get()

        for user in (self.member2, self.manager, self.viewer, self.outsider):
            self.make_issue(assignee=user)

        with CaptureQueriesContext(connection) as many:
            self.get()

        self.assertEqual(len(few), len(many))
        self.assertEqual(len(many), 2)
