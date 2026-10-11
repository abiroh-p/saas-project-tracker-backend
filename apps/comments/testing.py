"""Shared fixtures for the comments tests."""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.issues.models import Issue
from apps.projects.models import Project, ProjectMember

from .models import Comment

User = get_user_model()


class CommentAPITestCase(APITestCase):
    """A project with a manager, a team member and a viewer, one issue, and
    the manager authenticated. `newcomer` is not a member of anything."""

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
            key='COM', name='Comments project', created_by=self.manager,
        )
        self.add_member(self.manager, ProjectMember.Role.PROJECT_MANAGER)
        self.add_member(self.member, ProjectMember.Role.TEAM_MEMBER)
        self.add_member(self.viewer, ProjectMember.Role.VIEWER)

        self.issue = self.make_issue(1)

        self.client.force_authenticate(user=self.manager)

    def add_member(self, user, role, project=None):
        return ProjectMember.objects.create(
            project=project or self.project, user=user, role=role,
        )

    def make_issue(self, number, project=None, **extra):
        return Issue.objects.create(
            project=project or self.project,
            issue_number=number,
            title=f'Issue {number}',
            reporter=self.manager,
            **extra,
        )

    def make_comment(self, author=None, body='A comment', issue=None, **extra):
        return Comment.objects.create(
            issue=issue or self.issue,
            author=author or self.manager,
            body=body,
            **extra,
        )
