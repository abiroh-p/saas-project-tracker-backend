from rest_framework import status

from apps.issues.models import Issue
from apps.reports.serializers import (
    PriorityDistributionSerializer,
    StatusDistributionSerializer,
)

from ..testing import ReportsTestCase, Priority, Status


class DistributionTestCase(ReportsTestCase):
    endpoint = None
    field = None
    choices = None

    def get(self, project=None):
        project = project or self.project
        return self.client.get(
            f'/api/v1/projects/{project.pk}/reports/{self.endpoint}/',
        )

    def counts(self, response):
        return {row[self.field]: row['count'] for row in response.data['results']}

    def force_value(self, issue, value):
        """Store a value outside the declared choices (legacy data)."""
        Issue.objects.filter(pk=issue.pk).update(**{self.field: value})


class StatusDistributionTests(DistributionTestCase):
    endpoint = 'status-distribution'
    field = 'status'

    def test_every_declared_status_is_present_in_choice_order(self):
        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row['status'] for row in response.data['results']],
            [value for value, _ in Issue.Status.choices],
        )
        self.assertEqual(
            [row['label'] for row in response.data['results']],
            [label for _, label in Issue.Status.choices],
        )

    def test_empty_project_is_zero_filled(self):
        response = self.get()

        self.assertEqual(set(self.counts(response).values()), {0})
        self.assertEqual(response.data['total_issues'], 0)
        self.assertEqual(response.data['other_count'], 0)

    def test_counts_per_status(self):
        self.make_issue(status=Status.TODO)
        self.make_issue(status=Status.TODO)
        self.make_issue(status=Status.IN_REVIEW)
        self.make_issue(status=Status.DONE)

        response = self.get()

        self.assertEqual(
            self.counts(response),
            {'TODO': 2, 'IN_PROGRESS': 0, 'IN_REVIEW': 1, 'DONE': 1},
        )
        self.assertEqual(response.data['total_issues'], 4)

    def test_total_matches_the_sum_of_the_results(self):
        for status_value in Status.values:
            self.make_issue(status=status_value)
        self.make_issue(is_archived=True)

        response = self.get()

        self.assertEqual(
            sum(self.counts(response).values()) + response.data['other_count'],
            response.data['total_issues'],
        )
        self.assertEqual(response.data['total_issues'], len(Status.values))

    def test_archived_issues_and_other_projects_are_excluded(self):
        self.make_issue(is_archived=True)
        self.make_issue(project=self.other_project)

        self.assertEqual(self.get().data['total_issues'], 0)

    def test_a_legacy_status_goes_to_other_count_not_the_results(self):
        self.make_issue(status=Status.TODO)
        self.force_value(self.make_issue(), 'LEGACY')

        response = self.get()

        self.assertEqual(response.data['other_count'], 1)
        self.assertEqual(response.data['total_issues'], 2)
        self.assertNotIn('LEGACY', self.counts(response))
        self.assertEqual(len(response.data['results']), len(Status.values))

    def test_response_matches_the_documented_shape(self):
        response = self.get()

        self.assertEqual(
            set(response.data), set(StatusDistributionSerializer().fields),
        )


class PriorityDistributionTests(DistributionTestCase):
    endpoint = 'priority-distribution'
    field = 'priority'

    def test_every_declared_priority_is_present_lowest_first(self):
        response = self.get()

        self.assertEqual(
            [row['priority'] for row in response.data['results']],
            ['LOW', 'MEDIUM', 'HIGH', 'URGENT'],
        )

    def test_order_is_the_choice_order_not_alphabetical(self):
        response = self.get()
        order = [row['priority'] for row in response.data['results']]

        self.assertEqual(order, [v for v, _ in Issue.Priority.choices])
        self.assertNotEqual(order, sorted(order))

    def test_counts_per_priority(self):
        self.make_issue(priority=Priority.LOW)
        self.make_issue(priority=Priority.HIGH)
        self.make_issue(priority=Priority.HIGH)
        self.make_issue()  # default MEDIUM

        response = self.get()

        self.assertEqual(
            self.counts(response),
            {'LOW': 1, 'MEDIUM': 1, 'HIGH': 2, 'URGENT': 0},
        )
        self.assertEqual(response.data['total_issues'], 4)

    def test_empty_project_is_zero_filled(self):
        response = self.get()

        self.assertEqual(set(self.counts(response).values()), {0})
        self.assertEqual(response.data['total_issues'], 0)

    def test_archived_issues_and_other_projects_are_excluded(self):
        self.make_issue(is_archived=True, priority=Priority.URGENT)
        self.make_issue(project=self.other_project, priority=Priority.URGENT)

        self.assertEqual(self.counts(self.get())['URGENT'], 0)

    def test_a_legacy_priority_goes_to_other_count(self):
        self.force_value(self.make_issue(), 'CRITICAL')

        response = self.get()

        self.assertEqual(response.data['other_count'], 1)
        self.assertEqual(response.data['total_issues'], 1)
        self.assertNotIn('CRITICAL', self.counts(response))

    def test_response_matches_the_documented_shape(self):
        response = self.get()

        self.assertEqual(
            set(response.data), set(PriorityDistributionSerializer().fields),
        )
