from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from drf_spectacular.generators import SchemaGenerator
from rest_framework import status

from apps.issues.models import Issue
from apps.projects.models import ProjectMember

from .testing import TODAY, TOMORROW, YESTERDAY, DashboardTestCase, User

URL = '/api/v1/dashboard/'
Status = Issue.Status

SUMMARY_KEYS = {
    'projects_count',
    'assigned_issues_count',
    'in_progress_count',
    'completed_count',
    'overdue_count',
}
RECENT_ISSUE_KEYS = {
    'id',
    'issue_key',
    'title',
    'status',
    'priority',
    'project_id',
    'due_date',
    'updated_at',
}


class DashboardAPITestCase(DashboardTestCase):

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.me)

        # Freeze "today" so due-date assertions cannot flake at midnight.
        patcher = patch(
            'apps.dashboard.services.dashboard.timezone.localdate',
            return_value=TODAY,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, params=None):
        return self.client.get(URL, params or {})


class AuthenticationTests(DashboardAPITestCase):

    def test_unauthenticated_request_is_rejected(self):
        self.client.force_authenticate(user=None)

        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn('summary', response.data)

    def test_only_get_is_allowed(self):
        for method in ('post', 'put', 'patch', 'delete'):
            response = getattr(self.client, method)(URL, {}, format='json')

            self.assertEqual(
                response.status_code,
                status.HTTP_405_METHOD_NOT_ALLOWED,
                method,
            )

    def test_the_dashboard_belongs_to_the_authenticated_user(self):
        self.make_issue(status=Status.TODO)
        self.make_issue(assignee=self.other, status=Status.DONE)
        self.make_issue(assignee=self.other, status=Status.DONE)

        mine = self.get().data
        self.client.force_authenticate(user=self.other)
        theirs = self.get().data

        self.assertEqual(mine['summary']['assigned_issues_count'], 1)
        self.assertEqual(mine['summary']['completed_count'], 0)
        self.assertEqual(theirs['summary']['assigned_issues_count'], 2)
        self.assertEqual(theirs['summary']['completed_count'], 2)

    def test_a_client_supplied_user_id_is_ignored(self):
        self.make_issue(assignee=self.other)

        for params in (
            {'user': self.other.id},
            {'user_id': self.other.id},
            {'assignee': self.other.id},
        ):
            response = self.get(params)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.data['summary']['assigned_issues_count'], 0,
                params,
            )
            self.assertEqual(response.data['recent_issues'], [])


class ResponseContractTests(DashboardAPITestCase):

    def test_shape_for_an_empty_dashboard(self):
        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data),
            {'summary', 'issues_by_status', 'recent_issues'},
        )
        self.assertEqual(set(response.data['summary']), SUMMARY_KEYS)
        self.assertEqual(
            response.data['issues_by_status'],
            {value: 0 for value in Issue.Status.values},
        )
        self.assertEqual(response.data['recent_issues'], [])
        self.assertEqual(response.data['summary']['projects_count'], 1)

    def test_recent_issue_exposes_only_the_dashboard_fields(self):
        self.make_issue(
            description='Internal notes that must not leak',
            due_date=TOMORROW,
            priority=Issue.Priority.HIGH,
            status=Status.IN_PROGRESS,
        )

        item = self.get().data['recent_issues'][0]

        self.assertEqual(set(item), RECENT_ISSUE_KEYS)
        self.assertEqual(item['issue_key'], 'ALPHA-1')
        self.assertEqual(item['project_id'], self.project.id)
        self.assertEqual(item['status'], 'IN_PROGRESS')
        self.assertEqual(item['priority'], 'HIGH')
        self.assertEqual(item['due_date'], TOMORROW.isoformat())

    def test_no_private_user_data_is_returned(self):
        self.make_issue()

        body = str(self.get().data)

        self.assertNotIn('@', body)
        self.assertNotIn('reporter', body)
        self.assertNotIn('password', body)

    def test_openapi_schema_documents_the_endpoint(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)

        operation = schema['paths'][URL]['get']

        self.assertEqual(operation['operationId'], 'dashboard_retrieve')
        self.assertNotIn('post', schema['paths'][URL])
        self.assertIn('Dashboard', str(operation['responses']['200']))


class MetricsTests(DashboardAPITestCase):

    def test_full_scenario(self):
        second = self.make_project('BETA')
        self.add_member(self.me, project=second)

        self.make_issue(status=Status.TODO, due_date=YESTERDAY)
        self.make_issue(status=Status.IN_PROGRESS, due_date=TODAY)
        self.make_issue(status=Status.IN_PROGRESS, project=second)
        self.make_issue(status=Status.IN_REVIEW, due_date=YESTERDAY)
        self.make_issue(status=Status.DONE, due_date=YESTERDAY)
        # Noise that must not be counted.
        self.make_issue(assignee=self.other, due_date=YESTERDAY)
        self.make_issue(assignee=None, due_date=YESTERDAY)
        self.make_issue(is_archived=True, due_date=YESTERDAY)

        data = self.get().data

        self.assertEqual(
            data['summary'],
            {
                'projects_count': 2,
                'assigned_issues_count': 5,
                'in_progress_count': 2,
                'completed_count': 1,
                'overdue_count': 2,
            },
        )
        self.assertEqual(
            data['issues_by_status'],
            {'TODO': 1, 'IN_PROGRESS': 2, 'IN_REVIEW': 1, 'DONE': 1},
        )

    def test_projects_outside_the_users_membership_are_not_exposed(self):
        hidden = self.make_project('HIDDEN')
        self.add_member(self.other, project=hidden)
        self.make_issue(assignee=self.other, project=hidden)

        data = self.get().data

        self.assertEqual(data['summary']['projects_count'], 1)
        self.assertEqual(data['summary']['assigned_issues_count'], 0)

    def test_crowded_project_does_not_inflate_counts(self):
        for index in range(6):
            self.add_member(
                User.objects.create_user(
                    username=f'extra{index}', password='TestPassword123',
                )
            )
        self.make_issue(status=Status.TODO)

        data = self.get().data

        self.assertEqual(data['summary']['projects_count'], 1)
        self.assertEqual(data['summary']['assigned_issues_count'], 1)
        self.assertEqual(len(data['recent_issues']), 1)

    def test_due_date_cutoff_is_the_start_of_today(self):
        self.make_issue(due_date=YESTERDAY)
        self.make_issue(due_date=TODAY)
        self.make_issue(due_date=TOMORROW)

        self.assertEqual(self.get().data['summary']['overdue_count'], 1)


class RecentIssuesTests(DashboardAPITestCase):

    def test_limited_to_five_newest_first(self):
        issues = [self.make_issue() for _ in range(7)]

        results = self.get().data['recent_issues']

        self.assertEqual(
            [item['id'] for item in results],
            [issue.id for issue in reversed(issues)][:5],
        )

    def test_editing_an_issue_moves_it_to_the_top(self):
        oldest = self.make_issue()
        self.make_issue()
        self.make_issue()

        response = self.client.patch(
            f'/api/v1/issues/{oldest.id}/',
            {'title': 'Touched'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = self.get().data['recent_issues']

        self.assertEqual(results[0]['id'], oldest.id)
        self.assertEqual(results[0]['title'], 'Touched')

    def test_only_the_users_own_visible_issues_appear(self):
        mine = self.make_issue()
        self.make_issue(assignee=self.other)
        self.make_issue(is_archived=True)

        results = self.get().data['recent_issues']

        self.assertEqual([item['id'] for item in results], [mine.id])

    def test_query_count_is_independent_of_the_number_of_issues(self):
        self.make_issue()
        with CaptureQueriesContext(connection) as small:
            self.get()

        for _ in range(15):
            self.make_issue()
        with CaptureQueriesContext(connection) as large:
            self.get()

        self.assertEqual(len(small), len(large))


class ConsistencyWithOtherEndpointsTests(DashboardAPITestCase):
    """The dashboard follows what the rest of the API does to the data."""

    def test_archiving_an_issue_removes_it_from_the_dashboard(self):
        issue = self.make_issue(status=Status.TODO, due_date=YESTERDAY)
        self.client.force_authenticate(user=self.manager)
        response = self.client.post(f'/api/v1/issues/{issue.id}/archive/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(user=self.me)
        data = self.get().data

        self.assertEqual(data['summary']['assigned_issues_count'], 0)
        self.assertEqual(data['summary']['overdue_count'], 0)
        self.assertEqual(data['recent_issues'], [])

    def test_archiving_a_project_removes_it_and_its_issues(self):
        self.make_issue()
        self.client.force_authenticate(user=self.manager)
        response = self.client.post(
            f'/api/v1/projects/{self.project.id}/archive/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(user=self.me)
        data = self.get().data

        self.assertEqual(data['summary']['projects_count'], 0)
        self.assertEqual(data['summary']['assigned_issues_count'], 0)

    def test_transitioning_an_issue_moves_it_between_statuses(self):
        issue = self.make_issue(status=Status.TODO)
        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': 'IN_PROGRESS'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = self.get().data

        self.assertEqual(data['issues_by_status']['TODO'], 0)
        self.assertEqual(data['issues_by_status']['IN_PROGRESS'], 1)
        self.assertEqual(data['summary']['in_progress_count'], 1)

    def test_removing_the_user_from_a_project_clears_their_work_there(self):
        self.make_issue()
        membership = ProjectMember.objects.get(
            project=self.project, user=self.me,
        )
        self.client.force_authenticate(user=self.manager)
        response = self.client.delete(
            f'/api/v1/projects/{self.project.id}/members/{membership.id}/'
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.client.force_authenticate(user=self.me)
        data = self.get().data

        self.assertEqual(data['summary']['projects_count'], 0)
        self.assertEqual(data['summary']['assigned_issues_count'], 0)
        self.assertEqual(data['recent_issues'], [])
