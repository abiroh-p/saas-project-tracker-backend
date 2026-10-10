"""Shared fixtures for the activity integration tests."""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.issues.models import Issue
from apps.projects.models import Project, ProjectMember

from .models import Activity

User = get_user_model()


class ActivityAPITestCase(APITestCase):
    """Projects and memberships are set up directly, so every Activity row
    seen in a test was written by the request under test."""

    def setUp(self):
        self.manager = User.objects.create_user(
            username='manager', password='TestPassword123',
        )
        self.member = User.objects.create_user(
            username='member', password='TestPassword123',
        )
        self.viewer = User.objects.create_user(
            username='viewer', password='TestPassword123',
        )
        self.newcomer = User.objects.create_user(
            username='newcomer', password='TestPassword123',
        )

        self.project = Project.objects.create(
            key='ACT',
            name='Activity project',
            description='Original description',
            created_by=self.manager,
        )
        self.manager_membership = self.add_member(
            self.manager, ProjectMember.Role.PROJECT_MANAGER,
        )
        self.member_membership = self.add_member(
            self.member, ProjectMember.Role.TEAM_MEMBER,
        )
        self.viewer_membership = self.add_member(
            self.viewer, ProjectMember.Role.VIEWER,
        )

        self.client.force_authenticate(user=self.manager)

    def add_member(self, user, role, project=None):
        return ProjectMember.objects.create(
            project=project or self.project, user=user, role=role,
        )

    def events(self, **filters):
        return Activity.objects.filter(**filters)

    def only_event(self):
        self.assertEqual(Activity.objects.count(), 1)
        return Activity.objects.get()

    def project_url(self, suffix=''):
        return f'/api/v1/projects/{self.project.id}/{suffix}'

    def make_issue(
        self, number, assignee=None, project=None, reporter=None, **extra,
    ):
        return Issue.objects.create(
            project=project or self.project,
            issue_number=number,
            title=f'Issue {number}',
            reporter=reporter or self.manager,
            assignee=assignee,
            **extra,
        )
