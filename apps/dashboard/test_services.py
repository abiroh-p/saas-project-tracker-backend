from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import connection
from django.utils import timezone
from django.test.utils import CaptureQueriesContext

from apps.issues.models import Issue
from apps.projects.models import ProjectMember

from .services.dashboard import (
    RECENT_ISSUES_LIMIT,
    get_assigned_issues,
    get_dashboard_summary,
    get_issues_by_status,
    get_overdue_count,
    get_projects_count,
    get_recent_issues,
)
from .testing import TODAY, TOMORROW, YESTERDAY, DashboardTestCase, User

Status = Issue.Status


class ProjectsCountTests(DashboardTestCase):

    def test_counts_every_non_archived_membership(self):
        second = self.make_project('BETA')
        self.add_member(self.me, project=second)

        self.assertEqual(get_projects_count(self.me), 2)

    def test_user_without_projects_gets_zero(self):
        loner = User.objects.create_user(
            username='loner', password='TestPassword123',
        )

        self.assertEqual(get_projects_count(loner), 0)

    def test_archived_projects_are_excluded(self):
        archived = self.make_project('OLD', is_archived=True)
        self.add_member(self.me, project=archived)

        self.assertEqual(get_projects_count(self.me), 1)

    def test_projects_without_membership_are_not_counted(self):
        self.make_project('SECRET')

        self.assertEqual(get_projects_count(self.me), 1)

    def test_other_members_do_not_inflate_the_count(self):
        for index in range(5):
            extra = User.objects.create_user(
                username=f'extra{index}', password='TestPassword123',
            )
            self.add_member(extra)

        self.assertEqual(get_projects_count(self.me), 1)

    def test_role_does_not_matter(self):
        viewer_project = self.make_project('VIEW')
        self.add_member(
            self.me, ProjectMember.Role.VIEWER, project=viewer_project,
        )
        manager_project = self.make_project('MGR')
        self.add_member(
            self.me, ProjectMember.Role.PROJECT_MANAGER,
            project=manager_project,
        )

        self.assertEqual(get_projects_count(self.me), 3)


class AssignedIssuesTests(DashboardTestCase):

    def ids(self, user=None):
        return set(
            get_assigned_issues(user or self.me).values_list('id', flat=True)
        )

    def test_only_issues_assigned_to_the_user(self):
        mine = self.make_issue()
        self.make_issue(assignee=self.other)
        self.make_issue(assignee=None)

        self.assertEqual(self.ids(), {mine.id})

    def test_archived_issues_are_excluded(self):
        mine = self.make_issue()
        self.make_issue(is_archived=True)

        self.assertEqual(self.ids(), {mine.id})

    def test_issues_of_an_archived_project_are_excluded(self):
        archived = self.make_project('OLD', is_archived=True)
        self.add_member(self.me, project=archived)
        self.make_issue(project=archived)
        mine = self.make_issue()

        self.assertEqual(self.ids(), {mine.id})

    def test_issues_are_excluded_once_the_user_is_no_longer_a_member(self):
        other_project = self.make_project('GONE')
        membership = self.add_member(self.me, project=other_project)
        self.make_issue(project=other_project)
        mine = self.make_issue()

        membership.delete()

        self.assertEqual(self.ids(), {mine.id})

    def test_a_crowded_project_does_not_duplicate_issues(self):
        for index in range(4):
            extra = User.objects.create_user(
                username=f'extra{index}', password='TestPassword123',
            )
            self.add_member(extra)

        issue = self.make_issue()

        rows = list(get_assigned_issues(self.me).values_list('id', flat=True))

        self.assertEqual(rows, [issue.id])


class IssuesByStatusTests(DashboardTestCase):

    def test_every_status_is_present_even_when_empty(self):
        counts = get_issues_by_status(get_assigned_issues(self.me))

        self.assertEqual(list(counts), list(Status.values))
        self.assertTrue(all(value == 0 for value in counts.values()))

    def test_counts_match_the_underlying_records(self):
        for status, amount in (
            (Status.TODO, 3),
            (Status.IN_PROGRESS, 2),
            (Status.DONE, 1),
        ):
            for _ in range(amount):
                self.make_issue(status=status)

        counts = get_issues_by_status(get_assigned_issues(self.me))

        self.assertEqual(
            counts,
            {
                Status.TODO: 3,
                Status.IN_PROGRESS: 2,
                Status.IN_REVIEW: 0,
                Status.DONE: 1,
            },
        )

    def test_other_users_and_archived_issues_are_not_counted(self):
        self.make_issue(status=Status.TODO)
        self.make_issue(status=Status.TODO, assignee=self.other)
        self.make_issue(status=Status.TODO, is_archived=True)

        counts = get_issues_by_status(get_assigned_issues(self.me))

        self.assertEqual(counts[Status.TODO], 1)

    def test_a_status_outside_the_choices_does_not_change_the_shape(self):
        issue = self.make_issue(status=Status.TODO)
        Issue.objects.filter(pk=issue.pk).update(status='LEGACY')

        counts = get_issues_by_status(get_assigned_issues(self.me))

        self.assertEqual(list(counts), list(Status.values))
        self.assertEqual(sum(counts.values()), 0)


class OverdueCountTests(DashboardTestCase):

    def overdue(self):
        return get_overdue_count(get_assigned_issues(self.me), TODAY)

    def test_past_due_incomplete_issue_is_overdue(self):
        self.make_issue(due_date=YESTERDAY, status=Status.TODO)

        self.assertEqual(self.overdue(), 1)

    def test_every_incomplete_status_can_be_overdue(self):
        for status in (Status.TODO, Status.IN_PROGRESS, Status.IN_REVIEW):
            self.make_issue(due_date=YESTERDAY, status=status)

        self.assertEqual(self.overdue(), 3)

    def test_due_today_is_not_overdue(self):
        self.make_issue(due_date=TODAY)

        self.assertEqual(self.overdue(), 0)

    def test_due_in_the_future_is_not_overdue(self):
        self.make_issue(due_date=TOMORROW)

        self.assertEqual(self.overdue(), 0)

    def test_issue_without_a_due_date_is_not_overdue(self):
        self.make_issue(due_date=None)

        self.assertEqual(self.overdue(), 0)

    def test_completed_issue_is_not_overdue(self):
        self.make_issue(due_date=YESTERDAY, status=Status.DONE)

        self.assertEqual(self.overdue(), 0)

    def test_archived_issue_is_not_overdue(self):
        self.make_issue(due_date=YESTERDAY, is_archived=True)

        self.assertEqual(self.overdue(), 0)

    def test_other_users_overdue_issues_are_not_counted(self):
        self.make_issue(due_date=YESTERDAY, assignee=self.other)

        self.assertEqual(self.overdue(), 0)

    def test_overdue_issues_of_an_archived_project_are_not_counted(self):
        archived = self.make_project('OLD', is_archived=True)
        self.add_member(self.me, project=archived)
        self.make_issue(project=archived, due_date=YESTERDAY)

        self.assertEqual(self.overdue(), 0)


class RecentIssuesTests(DashboardTestCase):

    def set_updated(self, issue, year, month=1, day=1):
        # updated_at is auto_now, so it can only be set through update().
        Issue.objects.filter(pk=issue.pk).update(
            updated_at=datetime(year, month, day, tzinfo=dt_timezone.utc),
        )

    def recent(self, limit=RECENT_ISSUES_LIMIT):
        return get_recent_issues(get_assigned_issues(self.me), limit)

    def test_newest_update_comes_first(self):
        oldest = self.make_issue()
        newest = self.make_issue()
        middle = self.make_issue()
        self.set_updated(oldest, 2026, 1, 1)
        self.set_updated(middle, 2026, 2, 1)
        self.set_updated(newest, 2026, 3, 1)

        self.assertEqual(
            [issue.id for issue in self.recent()],
            [newest.id, middle.id, oldest.id],
        )

    def test_equal_timestamps_fall_back_to_the_highest_id(self):
        issues = [self.make_issue() for _ in range(3)]
        for issue in issues:
            self.set_updated(issue, 2026, 5, 5)

        self.assertEqual(
            [issue.id for issue in self.recent()],
            [issue.id for issue in reversed(issues)],
        )

    def test_result_is_limited(self):
        for _ in range(RECENT_ISSUES_LIMIT + 3):
            self.make_issue()

        self.assertEqual(len(self.recent()), RECENT_ISSUES_LIMIT)
        self.assertEqual(len(self.recent(limit=2)), 2)

    def test_only_authorized_issues_are_returned(self):
        mine = self.make_issue()
        self.make_issue(assignee=self.other)
        self.make_issue(assignee=None)
        self.make_issue(is_archived=True)

        self.assertEqual([issue.id for issue in self.recent()], [mine.id])

    def test_completed_issues_are_included(self):
        done = self.make_issue(status=Status.DONE)

        self.assertEqual([issue.id for issue in self.recent()], [done.id])

    def test_no_issues_gives_an_empty_list(self):
        self.assertEqual(self.recent(), [])


class DashboardSummaryTests(DashboardTestCase):

    def test_empty_dashboard(self):
        data = get_dashboard_summary(self.me, today=TODAY)

        self.assertEqual(
            data['summary'],
            {
                'projects_count': 1,
                'assigned_issues_count': 0,
                'in_progress_count': 0,
                'completed_count': 0,
                'overdue_count': 0,
            },
        )
        self.assertEqual(data['recent_issues'], [])

    def test_summary_is_consistent_with_issues_by_status(self):
        self.make_issue(status=Status.TODO, due_date=YESTERDAY)
        self.make_issue(status=Status.IN_PROGRESS)
        self.make_issue(status=Status.IN_PROGRESS)
        self.make_issue(status=Status.DONE, due_date=YESTERDAY)

        data = get_dashboard_summary(self.me, today=TODAY)
        summary = data['summary']

        self.assertEqual(summary['assigned_issues_count'], 4)
        self.assertEqual(summary['in_progress_count'], 2)
        self.assertEqual(summary['completed_count'], 1)
        self.assertEqual(summary['overdue_count'], 1)
        self.assertEqual(
            summary['assigned_issues_count'],
            sum(data['issues_by_status'].values()),
        )

    def test_total_counts_an_issue_with_an_unrecognised_status(self):
        self.make_issue(status=Status.TODO)
        legacy = self.make_issue(status=Status.TODO)
        Issue.objects.filter(pk=legacy.pk).update(status='LEGACY')

        data = get_dashboard_summary(self.me, today=TODAY)

        # The total reflects every authorized record, while the breakdown
        # keeps its fixed shape and lists only the declared statuses.
        self.assertEqual(data['summary']['assigned_issues_count'], 2)
        self.assertEqual(
            data['issues_by_status'],
            {
                Status.TODO: 1,
                Status.IN_PROGRESS: 0,
                Status.IN_REVIEW: 0,
                Status.DONE: 0,
            },
        )
        self.assertEqual(len(data['recent_issues']), 2)

    def test_today_defaults_to_the_current_local_date(self):
        self.make_issue(due_date=timezone.localdate() - timedelta(days=1))
        self.make_issue(due_date=timezone.localdate())

        data = get_dashboard_summary(self.me)

        self.assertEqual(data['summary']['overdue_count'], 1)

    def test_query_count_does_not_grow_with_the_data(self):
        self.make_issue()

        with CaptureQueriesContext(connection) as small:
            get_dashboard_summary(self.me, today=TODAY)

        for _ in range(20):
            self.make_issue(due_date=YESTERDAY)

        with CaptureQueriesContext(connection) as large:
            get_dashboard_summary(self.me, today=TODAY)

        self.assertEqual(len(small), len(large))
        self.assertLessEqual(len(large), 4)
