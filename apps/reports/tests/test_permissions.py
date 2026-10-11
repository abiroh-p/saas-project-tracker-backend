from rest_framework import status

from apps.activity.models import Activity
from apps.issues.models import Issue

from ..testing import ReportsTestCase

ENDPOINTS = [
    'overview',
    'status-distribution',
    'priority-distribution',
    'assignee-workload',
    # Valid parameters, so a 200 proves access rather than a 400 hiding it.
    'trends/?date_from=2026-10-01&date_to=2026-10-07',
]


class ReportPermissionTests(ReportsTestCase):

    def url(self, endpoint, project=None):
        project = project or self.project
        path = endpoint if '/' in endpoint else f'{endpoint}/'
        return f'/api/v1/projects/{project.pk}/reports/{path}'

    def test_unauthenticated_request_is_rejected_everywhere(self):
        self.client.force_authenticate(user=None)

        for endpoint in ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(self.url(endpoint))

                self.assertEqual(
                    response.status_code, status.HTTP_401_UNAUTHORIZED,
                )

    def test_every_role_can_read(self):
        for user in (self.manager, self.member, self.viewer):
            self.client.force_authenticate(user=user)

            for endpoint in ENDPOINTS:
                with self.subTest(user=user.username, endpoint=endpoint):
                    response = self.client.get(self.url(endpoint))

                    self.assertEqual(
                        response.status_code, status.HTTP_200_OK,
                    )

    def test_non_member_gets_not_found(self):
        self.client.force_authenticate(user=self.outsider)

        for endpoint in ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(self.url(endpoint))

                self.assertEqual(
                    response.status_code, status.HTTP_404_NOT_FOUND,
                )
                self.assertEqual(response.data['code'], 'not_found')

    def test_missing_project_is_indistinguishable_from_forbidden(self):
        self.client.force_authenticate(user=self.outsider)
        forbidden = self.client.get(self.url('overview'))

        missing = self.client.get('/api/v1/projects/999999/reports/overview/')

        self.assertEqual(missing.status_code, forbidden.status_code)
        self.assertEqual(missing.data, forbidden.data)

    def test_archived_project_has_no_reports(self):
        self.project.is_archived = True
        self.project.save()

        for endpoint in ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(self.url(endpoint))

                self.assertEqual(
                    response.status_code, status.HTTP_404_NOT_FOUND,
                )

    def test_former_member_loses_access(self):
        self.member.project_memberships.all().delete()
        self.client.force_authenticate(user=self.member)

        response = self.client.get(self.url('overview'))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_membership_of_another_project_grants_nothing(self):
        self.make_issue(assignee=self.member)
        self.client.force_authenticate(user=self.outsider)

        response = self.client.get(self.url('assignee-workload'))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn('member', str(response.data))

    def test_other_projects_report_contains_nothing_from_this_one(self):
        self.make_issue(assignee=self.member)
        self.client.force_authenticate(user=self.outsider)

        response = self.client.get(
            self.url('assignee-workload', project=self.other_project),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['results'], [])
        self.assertEqual(response.data['total_issues'], 0)

    def test_only_get_is_allowed(self):
        for endpoint in ENDPOINTS:
            for method in ('post', 'put', 'patch', 'delete'):
                with self.subTest(endpoint=endpoint, method=method):
                    response = getattr(self.client, method)(
                        self.url(endpoint),
                    )

                    self.assertEqual(
                        response.status_code,
                        status.HTTP_405_METHOD_NOT_ALLOWED,
                    )

    def test_reports_are_read_only_and_write_no_activity(self):
        self.make_issue(assignee=self.member)
        issues_before = list(Issue.objects.values_list('pk', 'updated_at'))
        activities_before = Activity.objects.count()

        for endpoint in ENDPOINTS:
            self.client.get(self.url(endpoint))

        self.assertEqual(Activity.objects.count(), activities_before)
        self.assertEqual(
            list(Issue.objects.values_list('pk', 'updated_at')),
            issues_before,
        )

    def test_client_supplied_user_id_is_ignored(self):
        self.client.force_authenticate(user=self.outsider)

        response = self.client.get(
            self.url('overview'),
            {'user_id': self.manager.pk, 'user': self.manager.pk},
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
