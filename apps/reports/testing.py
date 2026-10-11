"""Shared fixtures for the reports tests."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.issues.models import Issue
from apps.issues.services.issue import transition_issue
from apps.projects.models import Project, ProjectMember

User = get_user_model()

# A fixed "today" keeps the date-dependent assertions deterministic.
TODAY = date(2026, 10, 11)
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)

Status = Issue.Status
Priority = Issue.Priority


def utc(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=dt_timezone.utc)


@contextmanager
def frozen_now(moment):
    """Make ``auto_now`` / ``auto_now_add`` fields record ``moment``."""
    with patch('django.utils.timezone.now', return_value=moment):
        yield


class ReportsTestCase(APITestCase):
    """Project ALPHA with one user per role, plus an unrelated project BETA.

    ``self.client`` is authenticated as the manager by default.
    """

    def setUp(self):
        self.manager = self.make_user('manager', 'Mia Manager')
        self.member = self.make_user('member', 'Tom Member')
        self.member2 = self.make_user('member2', 'Zed Member')
        self.viewer = self.make_user('viewer', 'Vic Viewer')
        self.outsider = self.make_user('outsider', 'Olga Outsider')

        self.project = self.make_project('ALPHA')
        self.add_member(self.manager, ProjectMember.Role.PROJECT_MANAGER)
        self.add_member(self.member)
        self.add_member(self.member2)
        self.add_member(self.viewer, ProjectMember.Role.VIEWER)

        # An unrelated project the outsider belongs to.
        self.other_project = self.make_project('BETA')
        self.add_member(
            self.outsider,
            ProjectMember.Role.PROJECT_MANAGER,
            project=self.other_project,
        )

        self._numbers = {}
        self.client.force_authenticate(user=self.manager)

    def make_user(self, username, full_name=''):
        return User.objects.create_user(
            username=username,
            password='TestPassword123',
            email=f'{username}@example.com',
            full_name=full_name,
        )

    def make_project(self, key, **extra):
        return Project.objects.create(
            key=key,
            name=f'{key} project',
            created_by=self.manager,
            **extra,
        )

    def add_member(
        self, user, role=ProjectMember.Role.TEAM_MEMBER, project=None,
    ):
        return ProjectMember.objects.create(
            project=project or self.project, user=user, role=role,
        )

    def make_issue(self, assignee=None, project=None, **extra):
        """Create an issue directly (no activity is recorded)."""
        project = project or self.project
        number = self._numbers.get(project.pk, 0) + 1
        self._numbers[project.pk] = number

        return Issue.objects.create(
            project=project,
            issue_number=number,
            title=f'Issue {project.key}-{number}',
            reporter=self.manager,
            assignee=assignee,
            **extra,
        )

    def complete_issue(self, issue, when):
        """Walk ``issue`` to DONE through the real service, at ``when``.

        This records the activity events a real completion would, which is
        what the trends report relies on.
        """
        with frozen_now(when):
            for new_status in (
                Status.IN_PROGRESS, Status.IN_REVIEW, Status.DONE,
            ):
                transition_issue(
                    issue=issue, user=self.manager, new_status=new_status,
                )

    def set_created_at(self, issue, when):
        Issue.objects.filter(pk=issue.pk).update(created_at=when)
        return issue
