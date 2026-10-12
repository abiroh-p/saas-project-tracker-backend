from datetime import date

from django.test import override_settings
from rest_framework import status

from apps.activity.models import Activity
from apps.issues.models import Issue
from apps.issues.services.issue import transition_issue
from apps.reports.serializers import TrendsSerializer
from apps.reports.services.trends import MAX_RANGE_DAYS

from ..testing import ReportsTestCase, Status, frozen_now, utc


class TrendsTestCase(ReportsTestCase):

    def get(self, project=None, **params):
        project = project or self.project
        return self.client.get(
            f'/api/v1/projects/{project.pk}/reports/trends/', params,
        )

    def points(self, response):
        return {
            row['period']: (row['created_count'], row['completed_count'])
            for row in response.data['results']
        }


class TrendsValidationTests(TrendsTestCase):

    def assert_bad_request(self, **params):
        response = self.get(**params)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'bad_request')

    def test_dates_are_required(self):
        self.assert_bad_request()
        self.assert_bad_request(date_from='2026-10-01')
        self.assert_bad_request(date_to='2026-10-01')
        self.assert_bad_request(date_from='', date_to='')

    def test_malformed_dates_are_rejected(self):
        for bad in ('2026-13-01', '2026-02-30', 'yesterday', '20261001',
                    '2026-1-1', '2026-10-01T00:00:00', '1-10-2026'):
            with self.subTest(value=bad):
                self.assert_bad_request(date_from=bad, date_to='2026-10-05')
                self.assert_bad_request(date_from='2026-10-01', date_to=bad)

    def test_reversed_range_is_rejected(self):
        self.assert_bad_request(date_from='2026-10-05', date_to='2026-10-01')

    def test_range_longer_than_the_maximum_is_rejected(self):
        self.assert_bad_request(date_from='2025-01-01', date_to='2026-12-31')

    def test_maximum_range_is_accepted_and_one_more_day_is_not(self):
        # 366 days inclusive, then 367.
        ok = self.get(date_from='2025-12-31', date_to='2026-12-31')
        too_long = self.get(date_from='2025-12-30', date_to='2026-12-31')

        self.assertEqual(MAX_RANGE_DAYS, 366)
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.assertEqual(len(ok.data['results']), 366)
        self.assertEqual(too_long.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_interval_is_rejected(self):
        self.assert_bad_request(
            date_from='2026-10-01', date_to='2026-10-05', interval='month',
        )

    def test_nul_characters_are_rejected_not_a_server_error(self):
        self.assert_bad_request(
            date_from='2026-10-01\x00', date_to='2026-10-05',
        )
        self.assert_bad_request(
            date_from='2026-10-01', date_to='2026-10-05', interval='day\x00',
        )


class TrendsTests(TrendsTestCase):

    def test_response_matches_the_documented_shape(self):
        response = self.get(date_from='2026-10-01', date_to='2026-10-02')

        self.assertEqual(set(response.data), set(TrendsSerializer().fields))
        self.assertEqual(response.data['interval'], 'day')
        self.assertEqual(response.data['date_from'], date(2026, 10, 1))
        self.assertEqual(response.data['date_to'], date(2026, 10, 2))

    def test_empty_range_is_stable_and_zero_filled(self):
        response = self.get(date_from='2026-10-01', date_to='2026-10-03')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [r['period'] for r in response.data['results']],
            [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)],
        )
        self.assertEqual(
            {(r['created_count'], r['completed_count'])
             for r in response.data['results']},
            {(0, 0)},
        )

    def test_single_day_range(self):
        self.set_created_at(self.make_issue(), utc(2026, 10, 5))

        response = self.get(date_from='2026-10-05', date_to='2026-10-05')

        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['created_count'], 1)

    def test_created_counts_per_day(self):
        self.set_created_at(self.make_issue(), utc(2026, 10, 1))
        self.set_created_at(self.make_issue(), utc(2026, 10, 1, 20))
        self.set_created_at(self.make_issue(), utc(2026, 10, 3))

        points = self.points(
            self.get(date_from='2026-10-01', date_to='2026-10-03'),
        )

        self.assertEqual(points[date(2026, 10, 1)], (2, 0))
        self.assertEqual(points[date(2026, 10, 2)], (0, 0))
        self.assertEqual(points[date(2026, 10, 3)], (1, 0))

    def test_date_boundaries_are_inclusive(self):
        self.set_created_at(self.make_issue(), utc(2026, 10, 1, 0, 0))
        self.set_created_at(self.make_issue(), utc(2026, 10, 3, 23, 59))
        self.set_created_at(self.make_issue(), utc(2026, 9, 30, 23, 59))
        self.set_created_at(self.make_issue(), utc(2026, 10, 4, 0, 0))

        points = self.points(
            self.get(date_from='2026-10-01', date_to='2026-10-03'),
        )

        self.assertEqual(sum(c for c, _ in points.values()), 2)
        self.assertEqual(points[date(2026, 10, 1)][0], 1)
        self.assertEqual(points[date(2026, 10, 3)][0], 1)

    def test_completed_counts_come_from_recorded_transitions(self):
        done_early = self.make_issue(assignee=self.member)
        done_late = self.make_issue(assignee=self.member)
        self.set_created_at(done_early, utc(2026, 10, 1))
        self.set_created_at(done_late, utc(2026, 10, 1))
        self.complete_issue(done_early, utc(2026, 10, 2))
        self.complete_issue(done_late, utc(2026, 10, 4))

        points = self.points(
            self.get(date_from='2026-10-01', date_to='2026-10-04'),
        )

        self.assertEqual(points[date(2026, 10, 1)], (2, 0))
        self.assertEqual(points[date(2026, 10, 2)], (0, 1))
        self.assertEqual(points[date(2026, 10, 4)], (0, 1))

    def test_intermediate_transitions_are_not_completions(self):
        issue = self.make_issue()

        with frozen_now(utc(2026, 10, 2)):
            for new_status in (Status.IN_PROGRESS, Status.IN_REVIEW):
                transition_issue(
                    issue=issue, user=self.manager, new_status=new_status,
                )

        points = self.points(
            self.get(date_from='2026-10-01', date_to='2026-10-03'),
        )

        self.assertEqual(sum(c for _, c in points.values()), 0)

    def test_status_done_without_a_recorded_transition_is_not_counted(self):
        # Completion dates are never guessed from updated_at.
        issue = self.make_issue(status=Status.DONE)
        Issue.objects.filter(pk=issue.pk).update(updated_at=utc(2026, 10, 2))

        points = self.points(
            self.get(date_from='2026-10-01', date_to='2026-10-03'),
        )

        self.assertEqual(sum(c for _, c in points.values()), 0)

    def test_later_edits_do_not_move_a_completion(self):
        issue = self.make_issue()
        self.complete_issue(issue, utc(2026, 10, 2))
        Issue.objects.filter(pk=issue.pk).update(updated_at=utc(2026, 10, 9))

        points = self.points(
            self.get(date_from='2026-10-01', date_to='2026-10-10'),
        )

        self.assertEqual(points[date(2026, 10, 2)][1], 1)
        self.assertEqual(points[date(2026, 10, 9)][1], 0)

    def test_archived_issues_are_excluded_from_both_series(self):
        archived = self.make_issue()
        self.set_created_at(archived, utc(2026, 10, 2))
        self.complete_issue(archived, utc(2026, 10, 3))
        Issue.objects.filter(pk=archived.pk).update(is_archived=True)

        points = self.points(
            self.get(date_from='2026-10-01', date_to='2026-10-05'),
        )

        self.assertEqual(set(points.values()), {(0, 0)})

    def test_other_projects_do_not_leak(self):
        other = self.make_issue(project=self.other_project)
        self.set_created_at(other, utc(2026, 10, 2))
        self.client.force_authenticate(user=self.outsider)
        other_response = self.get(
            project=self.other_project,
            date_from='2026-10-01', date_to='2026-10-03',
        )
        self.client.force_authenticate(user=self.manager)
        own_response = self.get(
            date_from='2026-10-01', date_to='2026-10-03',
        )

        self.assertEqual(self.points(other_response)[date(2026, 10, 2)], (1, 0))
        self.assertEqual(
            {v for v in self.points(own_response).values()}, {(0, 0)},
        )

    def test_week_interval_groups_by_monday(self):
        # 2026-10-05 is a Monday.
        self.set_created_at(self.make_issue(), utc(2026, 10, 5))
        self.set_created_at(self.make_issue(), utc(2026, 10, 11, 23))  # Sunday
        self.set_created_at(self.make_issue(), utc(2026, 10, 12))      # next Mon

        response = self.get(
            date_from='2026-10-05', date_to='2026-10-18', interval='week',
        )
        points = self.points(response)

        self.assertEqual(response.data['interval'], 'week')
        self.assertEqual(list(points), [date(2026, 10, 5), date(2026, 10, 12)])
        self.assertEqual(points[date(2026, 10, 5)], (2, 0))
        self.assertEqual(points[date(2026, 10, 12)], (1, 0))

    def test_first_week_is_labelled_by_its_monday_but_only_counts_the_range(
        self,
    ):
        # Range starts on Wednesday 2026-10-07; its week starts 2026-10-05.
        self.set_created_at(self.make_issue(), utc(2026, 10, 5))   # before range
        self.set_created_at(self.make_issue(), utc(2026, 10, 8))

        points = self.points(
            self.get(
                date_from='2026-10-07', date_to='2026-10-13',
                interval='week',
            )
        )

        self.assertEqual(list(points), [date(2026, 10, 5), date(2026, 10, 12)])
        self.assertEqual(points[date(2026, 10, 5)], (1, 0))

    def test_week_interval_counts_completions(self):
        issue = self.make_issue()
        # Pin creation to an earlier week: make_issue() stamps "now", which
        # lands inside the queried week once the real date reaches it.
        self.set_created_at(issue, utc(2026, 10, 1))
        self.complete_issue(issue, utc(2026, 10, 14))  # Wednesday

        points = self.points(
            self.get(
                date_from='2026-10-12', date_to='2026-10-18',
                interval='week',
            )
        )

        self.assertEqual(points, {date(2026, 10, 12): (0, 1)})

    @override_settings(TIME_ZONE='Asia/Kolkata')
    def test_dates_are_calendar_dates_in_the_configured_timezone(self):
        # 19:00 UTC on 30 Sep is 00:30 IST on 1 Oct.
        self.set_created_at(self.make_issue(), utc(2026, 9, 30, 19, 0))

        points = self.points(
            self.get(date_from='2026-09-30', date_to='2026-10-01'),
        )

        self.assertEqual(points[date(2026, 9, 30)], (0, 0))
        self.assertEqual(points[date(2026, 10, 1)], (1, 0))

    @override_settings(TIME_ZONE='Asia/Kolkata')
    def test_completions_use_the_configured_timezone_too(self):
        issue = self.make_issue()
        self.complete_issue(issue, utc(2026, 9, 30, 19, 0))

        points = self.points(
            self.get(date_from='2026-09-30', date_to='2026-10-01'),
        )

        self.assertEqual(points[date(2026, 10, 1)], (0, 1))

    def test_reading_trends_records_no_activity(self):
        before = Activity.objects.count()

        self.get(date_from='2026-10-01', date_to='2026-10-02')

        self.assertEqual(Activity.objects.count(), before)
