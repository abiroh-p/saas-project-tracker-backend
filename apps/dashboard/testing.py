"""Shared fixtures for the dashboard tests."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.issues.models import Issue
from apps.projects.models import Project, ProjectMember

User = get_user_model()

# A fixed "today" keeps the date-dependent assertions deterministic.
TODAY = date(2026, 10, 11)
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


class DashboardTestCase(APITestCase):
    """``self.me`` is the user whose dashboard is under test."""

    def setUp(self):
        self.me = User.objects.create_user(
            username='me', password='TestPassword123',
        )
        self.other = User.objects.create_user(
            username='other', password='TestPassword123',
        )
        self.manager = User.objects.create_user(
            username='manager', password='TestPassword123',
        )

        self.project = self.make_project('ALPHA')
        self.add_member(self.manager, ProjectMember.Role.PROJECT_MANAGER)
        self.add_member(self.me, ProjectMember.Role.TEAM_MEMBER)
        self.add_member(self.other, ProjectMember.Role.TEAM_MEMBER)

        self._numbers = {}

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

    def make_issue(self, assignee='me', project=None, **extra):
        """Create an issue; ``assignee`` defaults to ``self.me``.

        Pass ``assignee=None`` for an unassigned issue.
        """
        project = project or self.project
        number = self._numbers.get(project.pk, 0) + 1
        self._numbers[project.pk] = number

        if assignee == 'me':
            assignee = self.me

        return Issue.objects.create(
            project=project,
            issue_number=number,
            title=f'Issue {project.key}-{number}',
            reporter=self.manager,
            assignee=assignee,
            **extra,
        )
