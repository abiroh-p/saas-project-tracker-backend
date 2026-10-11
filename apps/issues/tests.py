from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from apps.projects.models import Project, ProjectMember
from apps.issues.models import Comment, Issue
from .services.issue import (
    create_issue,
    update_issue,
    transition_issue,
)


User = get_user_model()


class IssueServiceTestCase(APITestCase):

    def setUp(self):
        self.manager = User.objects.create_user(
            username='manager',
            password='TestPassword123',
        )

        self.member = User.objects.create_user(
            username='member',
            password='TestPassword123',
        )

        self.viewer = User.objects.create_user(
            username='viewer',
            password='TestPassword123',
        )

        self.outsider = User.objects.create_user(
            username='outsider',
            password='TestPassword123',
        )

        self.project = Project.objects.create(
            key='DEMO',
            name='Demo Project',
            created_by=self.manager,
        )

        ProjectMember.objects.create(
            project=self.project,
            user=self.manager,
            role=ProjectMember.Role.PROJECT_MANAGER,
        )

        ProjectMember.objects.create(
            project=self.project,
            user=self.member,
            role=ProjectMember.Role.TEAM_MEMBER,
        )

        ProjectMember.objects.create(
            project=self.project,
            user=self.viewer,
            role=ProjectMember.Role.VIEWER,
        )

    def test_two_issues_get_sequential_numbers(self):
        issue_one = create_issue(
            project=self.project,
            validated_data={
                'title': 'First issue',
            },
            user=self.manager,
        )

        issue_two = create_issue(
            project=self.project,
            validated_data={
                'title': 'Second issue',
            },
            user=self.manager,
        )

        self.assertEqual(issue_one.issue_number, 1)
        self.assertEqual(issue_two.issue_number, 2)

        self.assertEqual(issue_one.issue_key, 'DEMO-1')
        self.assertEqual(issue_two.issue_key, 'DEMO-2')

    def test_each_project_starts_issue_number_at_one(self):
        second_project = Project.objects.create(
            key='TEST',
            name='Test Project',
            created_by=self.manager,
        )

        ProjectMember.objects.create(
            project=second_project,
            user=self.manager,
            role=ProjectMember.Role.PROJECT_MANAGER,
        )

        issue_one = create_issue(
            project=self.project,
            validated_data={
                'title': 'Project one issue',
            },
            user=self.manager,
        )

        issue_two = create_issue(
            project=second_project,
            validated_data={
                'title': 'Project two issue',
            },
            user=self.manager,
        )

        self.assertEqual(issue_one.issue_number, 1)
        self.assertEqual(issue_two.issue_number, 1)

    def test_duplicate_issue_number_raises_integrity_error(self):
        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Existing issue',
            reporter=self.manager,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Issue.objects.create(
                    project=self.project,
                    issue_number=1,
                    title='Duplicate issue',
                    reporter=self.manager,
                )

    def test_non_member_assignee_is_rejected(self):
        with self.assertRaisesMessage(
            ValueError,
            'Assignee must be a member of the project.',
        ):
            create_issue(
                project=self.project,
                validated_data={
                    'title': 'Invalid assignment',
                    'assignee': self.outsider,
                },
                user=self.manager,
            )

        self.project.refresh_from_db()

        self.assertEqual(
            self.project.issue_counter,
            0,
        )

        self.assertEqual(
            Issue.objects.count(),
            0,
        )

    def test_cannot_create_issue_assigned_to_viewer(self):
        with self.assertRaisesMessage(
            ValueError,
            'Viewers cannot be assigned issues.',
        ):
            create_issue(
                project=self.project,
                validated_data={
                    'title': 'For a viewer',
                    'assignee': self.viewer,
                },
                user=self.manager,
            )

        self.assertFalse(Issue.objects.exists())
        self.project.refresh_from_db()
        self.assertEqual(self.project.issue_counter, 0)

    def test_cannot_assign_existing_issue_to_viewer(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Original',
            reporter=self.manager,
            assignee=self.member,
        )

        with self.assertRaisesMessage(
            ValueError,
            'Viewers cannot be assigned issues.',
        ):
            update_issue(
                issue=issue,
                validated_data={'assignee': self.viewer},
                user=self.manager,
            )

        issue.refresh_from_db()
        self.assertEqual(issue.assignee, self.member)

    def test_manager_can_still_assign_and_unassign_members(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Original',
            reporter=self.manager,
        )

        update_issue(
            issue=issue,
            validated_data={'assignee': self.member},
            user=self.manager,
        )
        issue.refresh_from_db()
        self.assertEqual(issue.assignee, self.member)

        update_issue(
            issue=issue,
            validated_data={'assignee': None},
            user=self.manager,
        )
        issue.refresh_from_db()
        self.assertIsNone(issue.assignee)

    def test_existing_viewer_assignee_does_not_block_other_edits(self):
        # Data from before this rule: a viewer is already the assignee.
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Original',
            reporter=self.manager,
            assignee=self.viewer,
        )

        update_issue(
            issue=issue,
            validated_data={'title': 'Renamed'},
            user=self.manager,
        )
        update_issue(
            issue=issue,
            validated_data={'assignee': self.viewer},
            user=self.manager,
        )
        issue.refresh_from_db()

        self.assertEqual(issue.title, 'Renamed')
        self.assertEqual(issue.assignee, self.viewer)

        # ...and the manager can still clear it.
        update_issue(
            issue=issue,
            validated_data={'assignee': None},
            user=self.manager,
        )
        issue.refresh_from_db()
        self.assertIsNone(issue.assignee)

    def test_viewer_cannot_create_issue(self):
        # This rule is enforced at the API/service boundary.
        # The current create_issue service does not yet perform
        # role authorization, so this test will be implemented
        # when the API view is added.
        pass

    def test_reporter_can_edit_unassigned_issue(self):
        issue = create_issue(
            project=self.project,
            validated_data={
                'title': 'Original title',
            },
            user=self.member,
        )

        updated_issue = update_issue(
            issue=issue,
            validated_data={
                'title': 'Updated title',
            },
            user=self.member,
        )

        self.assertEqual(
            updated_issue.title,
            'Updated title',
        )

    def test_member_cannot_change_assignee(self):
        issue = create_issue(
            project=self.project,
            validated_data={
                'title': 'Issue',
            },
            user=self.member,
        )

        with self.assertRaisesMessage(
            PermissionError,
            'Only project managers can change the assignee.',
        ):
            update_issue(
                issue=issue,
                validated_data={
                    'assignee': self.manager,
                },
                user=self.member,
            )

    def test_failed_issue_insert_rolls_back_counter(self):
        self.project.issue_counter = 0
        self.project.save(
            update_fields=[
                'issue_counter',
                'updated_at',
            ]
        )

        original_create = Issue.objects.create

        def failing_create(*args, **kwargs):
            raise ValueError('Simulated insert failure.')

        Issue.objects.create = failing_create

        try:
            with self.assertRaisesMessage(
                ValueError,
                'Simulated insert failure.',
            ):
                create_issue(
                    project=self.project,
                    validated_data={
                        'title': 'Will fail',
                    },
                    user=self.manager,
                )
        finally:
            Issue.objects.create = original_create

        self.project.refresh_from_db()

        self.assertEqual(
            self.project.issue_counter,
            0,
        )

        self.assertEqual(
            Issue.objects.count(),
            0,
        )

    def test_manager_can_transition_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        issue = transition_issue(
            issue=issue,
            user=self.manager,
            new_status=Issue.Status.IN_PROGRESS,
        )

        issue.refresh_from_db()

        self.assertEqual(
            issue.status,
            Issue.Status.IN_PROGRESS,
        )


    def test_assigned_member_can_transition_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
            assignee=self.member,
        )

        issue = transition_issue(
            issue=issue,
            user=self.member,
            new_status=Issue.Status.IN_PROGRESS,
        )

        issue.refresh_from_db()

        self.assertEqual(
            issue.status,
            Issue.Status.IN_PROGRESS,
        )


    def test_unrelated_member_cannot_transition_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        with self.assertRaises(PermissionError):
            transition_issue(
                issue=issue,
                user=self.member,
                new_status=Issue.Status.IN_PROGRESS,
            )


    def test_reporter_who_is_not_assignee_cannot_transition_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.member,
        )

        with self.assertRaises(PermissionError):
            transition_issue(
                issue=issue,
                user=self.member,
                new_status=Issue.Status.IN_PROGRESS,
            )


    def test_viewer_cannot_transition_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        with self.assertRaises(PermissionError):
            transition_issue(
                issue=issue,
                user=self.viewer,
                new_status=Issue.Status.IN_PROGRESS,
            )


    def test_archived_issue_cannot_be_transitioned(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
            is_archived=True,
        )

        with self.assertRaises(ValueError) as context:
            transition_issue(
                issue=issue,
                user=self.manager,
                new_status=Issue.Status.IN_PROGRESS,
            )

        self.assertEqual(
            str(context.exception),
            'Archived issues cannot be transitioned.',
        )


    def test_issue_cannot_transition_to_same_status(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        with self.assertRaises(ValueError) as context:
            transition_issue(
                issue=issue,
                user=self.manager,
                new_status=Issue.Status.TODO,
            )

        self.assertEqual(
            str(context.exception),
            'Issue is already in this status.',
        )

    def test_viewer_cannot_update_issue_assigned_to_them(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Original',
            reporter=self.manager,
            assignee=self.viewer,
        )

        with self.assertRaisesMessage(
            PermissionError,
            'Viewers cannot edit issues.',
        ):
            update_issue(
                issue=issue,
                validated_data={'title': 'Changed'},
                user=self.viewer,
            )

        issue.refresh_from_db()
        self.assertEqual(issue.title, 'Original')

    def test_viewer_cannot_update_issue_they_reported(self):
        # E.g. a member who was later demoted to viewer.
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Original',
            reporter=self.viewer,
        )

        with self.assertRaises(PermissionError):
            update_issue(
                issue=issue,
                validated_data={'title': 'Changed'},
                user=self.viewer,
            )

        issue.refresh_from_db()
        self.assertEqual(issue.title, 'Original')

    def test_assigned_team_member_can_still_update_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Original',
            reporter=self.manager,
            assignee=self.member,
        )

        update_issue(
            issue=issue,
            validated_data={'title': 'Changed'},
            user=self.member,
        )

        issue.refresh_from_db()
        self.assertEqual(issue.title, 'Changed')


class IssueAPITestCase(APITestCase):

    def setUp(self):
        self.manager = User.objects.create_user(
            username='api_manager',
            password='TestPassword123',
        )

        self.member = User.objects.create_user(
            username='api_member',
            password='TestPassword123',
        )

        self.viewer = User.objects.create_user(
            username='api_viewer',
            password='TestPassword123',
        )

        self.outsider = User.objects.create_user(
            username='api_outsider',
            password='TestPassword123',
        )

        self.project = Project.objects.create(
            key='API',
            name='API Project',
            created_by=self.manager,
        )

        ProjectMember.objects.create(
            project=self.project,
            user=self.manager,
            role=ProjectMember.Role.PROJECT_MANAGER,
        )

        ProjectMember.objects.create(
            project=self.project,
            user=self.member,
            role=ProjectMember.Role.TEAM_MEMBER,
        )

        ProjectMember.objects.create(
            project=self.project,
            user=self.viewer,
            role=ProjectMember.Role.VIEWER,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_manager_can_create_issue(self):
        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/projects/{self.project.id}/issues/',
            {
                'title': 'Fix login bug',
                'description': 'Login currently fails.',
                'issue_type': 'BUG',
                'priority': 'HIGH',
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            201,
        )

        self.assertEqual(
            response.data['issue_key'],
            'API-1',
        )

        self.assertEqual(
            response.data['reporter'],
            self.manager.username,
        )

    def test_team_member_can_create_issue(self):
        self.authenticate(self.member)

        response = self.client.post(
            f'/api/v1/projects/{self.project.id}/issues/',
            {
                'title': 'Member issue',
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            201,
        )

        self.assertEqual(
            response.data['issue_key'],
            'API-1',
        )

    def test_cannot_create_issue_assigned_to_viewer(self):
        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/projects/{self.project.id}/issues/',
            {'title': 'For a viewer', 'assignee': self.viewer.id},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['detail'],
            'Viewers cannot be assigned issues.',
        )
        self.assertFalse(Issue.objects.exists())

    def test_cannot_assign_issue_to_viewer(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Original',
            reporter=self.manager,
        )
        self.authenticate(self.manager)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {'assignee': self.viewer.id},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['detail'],
            'Viewers cannot be assigned issues.',
        )
        issue.refresh_from_db()
        self.assertIsNone(issue.assignee)

    def test_manager_can_still_assign_issue_to_team_member(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Original',
            reporter=self.manager,
        )
        self.authenticate(self.manager)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {'assignee': self.member.id},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['assignee'], self.member.id)

    def test_viewer_cannot_create_issue(self):
        self.authenticate(self.viewer)

        response = self.client.post(
            f'/api/v1/projects/{self.project.id}/issues/',
            {
                'title': 'Viewer issue',
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertEqual(
            response.data['detail'],
            'Viewers cannot create issues.',
        )

    def test_non_member_cannot_view_project_issues(self):
        self.authenticate(self.outsider)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/',
        )

        self.assertEqual(
            response.status_code,
            404,
        )

    def test_member_can_list_project_issues(self):
        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='First issue',
            reporter=self.manager,
        )

        self.authenticate(self.member)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/',
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.data['count'],
            1,
        )

        self.assertEqual(
            response.data['results'][0]['issue_key'],
            'API-1',
        )

    def test_reporter_can_edit_unassigned_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Original title',
            reporter=self.member,
        )

        self.authenticate(self.member)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {
                'title': 'Updated title',
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        issue.refresh_from_db()

        self.assertEqual(
            issue.title,
            'Updated title',
        )

    def test_member_cannot_change_assignee(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.member,
        )

        self.authenticate(self.member)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {
                'assignee': self.manager.id,
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertEqual(
            response.data['detail'],
            'Only project managers can change the assignee.',
        )

    def test_manager_can_assign_issue_to_member(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.manager)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {
                'assignee': self.member.id,
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        issue.refresh_from_db()

        self.assertEqual(
            issue.assignee_id,
            self.member.id,
        )

    def test_manager_cannot_assign_issue_to_non_member(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.manager)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {
                'assignee': self.outsider.id,
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertEqual(
            response.data['detail'],
            'Assignee must be a member of the project.',
        )

    def test_reporter_is_read_only(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.member,
        )

        self.authenticate(self.member)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {
                'reporter': self.manager.id,
                'title': 'Updated',
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        issue.refresh_from_db()

        self.assertEqual(
            issue.reporter_id,
            self.member.id,
        )

    def test_issue_number_is_read_only(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.manager)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {
                'issue_number': 999,
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        issue.refresh_from_db()

        self.assertEqual(
            issue.issue_number,
            1,
        )

    def test_project_is_read_only(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.manager)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {
                'project': 999,
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        issue.refresh_from_db()

        self.assertEqual(
            issue.project_id,
            self.project.id,
        )

    def test_unrelated_team_member_cannot_edit_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.member)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {
                'title': 'Unauthorized update',
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertEqual(
            response.data['detail'],
            'Only the reporter or assignee can edit this issue.',
        )


    def test_manager_can_archive_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/archive/',
        )

        self.assertEqual(response.status_code, 200)

        issue.refresh_from_db()
        self.assertTrue(issue.is_archived)


    def test_team_member_cannot_archive_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.member)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/archive/',
        )

        self.assertEqual(response.status_code, 403)

        issue.refresh_from_db()
        self.assertFalse(issue.is_archived)


    def test_viewer_cannot_archive_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.viewer)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/archive/',
        )

        self.assertEqual(response.status_code, 403)

        issue.refresh_from_db()
        self.assertFalse(issue.is_archived)


    def test_archived_issue_cannot_be_edited(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
            is_archived=True,
        )

        self.authenticate(self.manager)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {'title': 'Updated title'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['detail'],
            'Archived issues cannot be edited.',
        )


    def test_manager_can_archive_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/archive/',
        )

        self.assertEqual(response.status_code, 200)

        issue.refresh_from_db()
        self.assertTrue(issue.is_archived)


    def test_team_member_cannot_archive_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.member)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/archive/',
        )

        self.assertEqual(response.status_code, 403)

        issue.refresh_from_db()
        self.assertFalse(issue.is_archived)


    def test_viewer_cannot_archive_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.viewer)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/archive/',
        )

        self.assertEqual(response.status_code, 403)

        issue.refresh_from_db()
        self.assertFalse(issue.is_archived)


    def test_archived_issue_cannot_be_edited(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
            is_archived=True,
        )

        self.authenticate(self.manager)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {'title': 'Updated title'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['detail'],
            'Archived issues cannot be edited.',
        )


    def test_archived_issue_is_hidden_from_list(self):
        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Active Issue',
            reporter=self.manager,
        )

        Issue.objects.create(
            project=self.project,
            issue_number=2,
            title='Archived Issue',
            reporter=self.manager,
            is_archived=True,
        )

        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(
            response.data['results'][0]['title'],
            'Active Issue',
        )

    def test_already_archived_issue_cannot_be_archived_again(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
            is_archived=True,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/archive/',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['detail'],
            'Issue is already archived.',
        )

    def test_manager_can_transition_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.IN_PROGRESS},
            format='json',
        )

        self.assertEqual(response.status_code, 200)

        issue.refresh_from_db()
        self.assertEqual(
            issue.status,
            Issue.Status.IN_PROGRESS,
        )


    def test_assigned_member_can_transition_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
            assignee=self.member,
        )

        self.authenticate(self.member)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.IN_PROGRESS},
            format='json',
        )

        self.assertEqual(response.status_code, 200)

        issue.refresh_from_db()
        self.assertEqual(
            issue.status,
            Issue.Status.IN_PROGRESS,
        )


    def test_reporter_cannot_transition_unassigned_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.member,
        )

        self.authenticate(self.member)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.IN_PROGRESS},
            format='json',
        )

        self.assertEqual(response.status_code, 403)

    def test_viewer_cannot_update_issue_assigned_to_them(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Original',
            reporter=self.manager,
            assignee=self.viewer,
        )
        self.authenticate(self.viewer)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {'title': 'Changed'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data['detail'],
            'Viewers cannot edit issues.',
        )

        issue.refresh_from_db()
        self.assertEqual(issue.title, 'Original')

    def test_assigned_team_member_can_update_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Original',
            reporter=self.manager,
            assignee=self.member,
        )
        self.authenticate(self.member)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {'title': 'Changed'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['title'], 'Changed')

    def test_viewer_cannot_transition_issue(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.viewer)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.IN_PROGRESS},
            format='json',
        )

        self.assertEqual(response.status_code, 403)


    def test_archived_issue_cannot_be_transitioned(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
            is_archived=True,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.IN_PROGRESS},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

        self.assertEqual(
            response.data['detail'],
            'Archived issues cannot be transitioned.',
        )


    def test_transition_to_same_status_returns_bad_request(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.TODO},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

        self.assertEqual(
            response.data['detail'],
            'Issue is already in this status.',
        )

    def test_status_cannot_be_changed_through_patch(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Issue',
            reporter=self.manager,
        )

        self.authenticate(self.manager)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {'status': Issue.Status.DONE},
            format='json',
        )

        self.assertEqual(response.status_code, 200)

        issue.refresh_from_db()

        self.assertEqual(
            issue.status,
            Issue.Status.TODO,
        )


    def test_filter_issues_by_status(self):
        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Todo Issue',
            reporter=self.manager,
            status=Issue.Status.TODO,
        )

        Issue.objects.create(
            project=self.project,
            issue_number=2,
            title='In Progress Issue',
            reporter=self.manager,
            status=Issue.Status.IN_PROGRESS,
        )

        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            f'?status=IN_PROGRESS'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(
            response.data['results'][0]['title'],
            'In Progress Issue',
        )


    def test_filter_issues_by_priority(self):
        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='High Priority',
            reporter=self.manager,
            priority=Issue.Priority.HIGH,
        )

        Issue.objects.create(
            project=self.project,
            issue_number=2,
            title='Low Priority',
            reporter=self.manager,
            priority=Issue.Priority.LOW,
        )

        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            f'?priority=HIGH'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(
            response.data['results'][0]['title'],
            'High Priority',
        )


    def test_filter_issues_by_type(self):
        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Bug Issue',
            reporter=self.manager,
            issue_type=Issue.IssueType.BUG,
        )

        Issue.objects.create(
            project=self.project,
            issue_number=2,
            title='Task Issue',
            reporter=self.manager,
            issue_type=Issue.IssueType.TASK,
        )

        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            f'?issue_type=BUG'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(
            response.data['results'][0]['title'],
            'Bug Issue',
        )


    def test_filter_issues_by_assignee(self):
        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Assigned Issue',
            reporter=self.manager,
            assignee=self.member,
        )

        Issue.objects.create(
            project=self.project,
            issue_number=2,
            title='Unassigned Issue',
            reporter=self.manager,
        )

        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            f'?assignee={self.member.id}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(
            response.data['results'][0]['title'],
            'Assigned Issue',
        )

    def test_filter_by_invalid_assignee(self):
        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            '?assignee=abc'
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['detail'],
            'Invalid assignee filter.',
        )


    def test_multiple_issue_filters_can_be_combined(self):
        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Matching Issue',
            reporter=self.manager,
            status=Issue.Status.IN_PROGRESS,
            priority=Issue.Priority.HIGH,
        )

        Issue.objects.create(
            project=self.project,
            issue_number=2,
            title='Wrong Status',
            reporter=self.manager,
            status=Issue.Status.TODO,
            priority=Issue.Priority.HIGH,
        )

        Issue.objects.create(
            project=self.project,
            issue_number=3,
            title='Wrong Priority',
            reporter=self.manager,
            status=Issue.Status.IN_PROGRESS,
            priority=Issue.Priority.LOW,
        )

        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            f'?status=IN_PROGRESS&priority=HIGH'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(
            response.data['results'][0]['title'],
            'Matching Issue',
        )

    def test_invalid_status_filter_returns_bad_request(self):
        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            '?status=INVALID'
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['detail'],
            'Invalid status filter.',
        )


    def test_invalid_priority_filter_returns_bad_request(self):
        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            '?priority=INVALID'
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['detail'],
            'Invalid priority filter.',
        )


    def test_invalid_issue_type_filter_returns_bad_request(self):
        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            '?issue_type=INVALID'
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['detail'],
            'Invalid issue type filter.',
        )

    def test_issue_list_pagination(self):
        for issue_number in range(1, 26):
            Issue.objects.create(
                project=self.project,
                issue_number=issue_number,
                title=f'Issue {issue_number}',
                reporter=self.manager,
            )

        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            '?page=1&page_size=10'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 25)
        self.assertEqual(len(response.data['results']), 10)
        self.assertIsNone(response.data['previous'])
        self.assertIsNotNone(response.data['next'])


    def test_issue_list_second_page(self):
        for issue_number in range(1, 26):
            Issue.objects.create(
                project=self.project,
                issue_number=issue_number,
                title=f'Issue {issue_number}',
                reporter=self.manager,
            )

        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            '?page=2&page_size=10'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 25)
        self.assertEqual(len(response.data['results']), 10)
        self.assertIsNotNone(response.data['previous'])
        self.assertIsNotNone(response.data['next'])


    def test_issue_list_page_size_is_limited(self):
        for issue_number in range(1, 26):
            Issue.objects.create(
                project=self.project,
                issue_number=issue_number,
                title=f'Issue {issue_number}',
                reporter=self.manager,
            )

        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
            '?page=1&page_size=200'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 25)
        self.assertEqual(len(response.data['results']), 25)

    def test_todo_can_transition_to_in_progress(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Test issue',
            reporter=self.manager,
            status=Issue.Status.TODO,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.IN_PROGRESS},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['status'],
            Issue.Status.IN_PROGRESS,
        )


    def test_in_progress_can_transition_to_in_review(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Test issue',
            reporter=self.manager,
            status=Issue.Status.IN_PROGRESS,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.IN_REVIEW},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['status'],
            Issue.Status.IN_REVIEW,
        )


    def test_in_review_can_transition_to_done(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Test issue',
            reporter=self.manager,
            status=Issue.Status.IN_REVIEW,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.DONE},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['status'],
            Issue.Status.DONE,
        )


    def test_todo_cannot_skip_to_done(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Test issue',
            reporter=self.manager,
            status=Issue.Status.TODO,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.DONE},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(issue.status, Issue.Status.TODO)


    def test_in_progress_cannot_skip_to_done(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Test issue',
            reporter=self.manager,
            status=Issue.Status.IN_PROGRESS,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.DONE},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(issue.status, Issue.Status.IN_PROGRESS)


    def test_done_cannot_transition_to_another_status(self):
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Test issue',
            reporter=self.manager,
            status=Issue.Status.DONE,
        )

        self.authenticate(self.manager)

        response = self.client.post(
            f'/api/v1/issues/{issue.id}/transition/',
            {'status': Issue.Status.TODO},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(issue.status, Issue.Status.DONE)


    def test_issue_list_ordered_newest_first(self):
        first_issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='First issue',
            reporter=self.manager,
        )

        second_issue = Issue.objects.create(
            project=self.project,
            issue_number=2,
            title='Second issue',
            reporter=self.manager,
        )

        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/'
        )

        self.assertEqual(response.status_code, 200)

        results = response.data['results']

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['id'], second_issue.id)
        self.assertEqual(results[1]['id'], first_issue.id)

    def dated_project(self):
        self.project.start_date = '2026-01-01'
        self.project.end_date = '2026-12-31'
        self.project.save()

    def create_with_due_date(self, due_date):
        return self.client.post(
            f'/api/v1/projects/{self.project.id}/issues/',
            {'title': 'Dated issue', 'due_date': due_date},
            format='json',
        )

    def test_create_rejects_due_date_before_project_start(self):
        self.dated_project()
        self.authenticate(self.manager)

        response = self.create_with_due_date('2025-12-31')

        self.assertEqual(response.status_code, 400)
        self.assertIn('due_date', response.data['errors'])
        self.assertFalse(Issue.objects.exists())

    def test_create_rejects_due_date_after_project_end(self):
        self.dated_project()
        self.authenticate(self.manager)

        response = self.create_with_due_date('2027-01-01')

        self.assertEqual(response.status_code, 400)
        self.assertIn('due_date', response.data['errors'])
        self.assertFalse(Issue.objects.exists())

        # A rejected request must not use up an issue number.
        self.project.refresh_from_db()
        self.assertEqual(self.project.issue_counter, 0)

    def test_create_accepts_due_dates_inside_the_project_range(self):
        self.dated_project()
        self.authenticate(self.manager)

        for due_date in ('2026-01-01', '2026-06-15', '2026-12-31'):
            response = self.create_with_due_date(due_date)

            self.assertEqual(response.status_code, 201, due_date)
            self.assertEqual(response.data['due_date'], due_date)

    def test_create_accepts_any_due_date_when_project_has_no_dates(self):
        self.authenticate(self.manager)

        response = self.create_with_due_date('2030-05-05')

        self.assertEqual(response.status_code, 201)

    def test_update_rejects_due_date_outside_the_project_range(self):
        self.dated_project()
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Existing',
            reporter=self.manager,
        )
        self.authenticate(self.manager)

        for due_date in ('2025-12-31', '2027-01-01'):
            response = self.client.patch(
                f'/api/v1/issues/{issue.id}/',
                {'due_date': due_date},
                format='json',
            )

            self.assertEqual(response.status_code, 400, due_date)
            self.assertIn('due_date', response.data['errors'])

        issue.refresh_from_db()
        self.assertIsNone(issue.due_date)

    def test_update_accepts_due_date_inside_the_project_range(self):
        self.dated_project()
        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Existing',
            reporter=self.manager,
        )
        self.authenticate(self.manager)

        response = self.client.patch(
            f'/api/v1/issues/{issue.id}/',
            {'due_date': '2026-06-15'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['due_date'], '2026-06-15')

    def test_issue_search_matches_title_and_description_case_insensitively(self):
        title_match = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Fix LOGIN flow',
            reporter=self.manager,
        )
        description_match = Issue.objects.create(
            project=self.project,
            issue_number=2,
            title='Credential flow',
            description='The login token expires too soon.',
            reporter=self.manager,
        )
        Issue.objects.create(
            project=self.project,
            issue_number=3,
            title='Unrelated work',
            reporter=self.manager,
        )
        self.authenticate(self.member)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/',
            {'search': 'login'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(
            {item['id'] for item in response.data['results']},
            {title_match.id, description_match.id},
        )

    def test_issue_search_matches_exact_issue_key(self):
        target = Issue.objects.create(
            project=self.project,
            issue_number=12,
            title='Unrelated title',
            reporter=self.manager,
        )
        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Another unrelated title',
            reporter=self.manager,
        )
        self.authenticate(self.member)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/',
            {'search': 'api-12'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], target.id)

    def test_issue_search_combines_with_existing_filters(self):
        match = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Login failure',
            reporter=self.manager,
            assignee=self.member,
            status=Issue.Status.IN_PROGRESS,
            priority=Issue.Priority.HIGH,
            issue_type=Issue.IssueType.BUG,
        )
        Issue.objects.create(
            project=self.project,
            issue_number=2,
            title='Login follow-up',
            reporter=self.manager,
            assignee=self.member,
            status=Issue.Status.TODO,
            priority=Issue.Priority.HIGH,
            issue_type=Issue.IssueType.BUG,
        )
        Issue.objects.create(
            project=self.project,
            issue_number=3,
            title='Login settings',
            reporter=self.manager,
            assignee=self.manager,
            status=Issue.Status.IN_PROGRESS,
            priority=Issue.Priority.HIGH,
            issue_type=Issue.IssueType.BUG,
        )
        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/',
            {
                'search': 'login',
                'status': Issue.Status.IN_PROGRESS,
                'priority': Issue.Priority.HIGH,
                'issue_type': Issue.IssueType.BUG,
                'assignee': self.member.id,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], match.id)

    def test_issue_search_paginates_filtered_results_and_stays_in_project(self):
        matching_ids = set()
        for issue_number in range(1, 4):
            issue = Issue.objects.create(
                project=self.project,
                issue_number=issue_number,
                title=f'Login task {issue_number}',
                reporter=self.manager,
            )
            matching_ids.add(issue.id)

        other_project = Project.objects.create(
            key='OTHER',
            name='Other project',
            created_by=self.manager,
        )
        ProjectMember.objects.create(
            project=other_project,
            user=self.manager,
            role=ProjectMember.Role.PROJECT_MANAGER,
        )
        Issue.objects.create(
            project=other_project,
            issue_number=1,
            title='Login elsewhere',
            reporter=self.manager,
        )
        self.authenticate(self.member)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/',
            {'search': 'login', 'page': 1, 'page_size': 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual(len(response.data['results']), 2)
        self.assertTrue(
            {item['id'] for item in response.data['results']}
            <= matching_ids
        )

    def test_non_matching_issue_search_returns_empty_results(self):
        self.authenticate(self.member)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/',
            {'search': 'no such issue'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])

    def test_assignee_filter_rejects_non_positive_ids(self):
        self.authenticate(self.manager)

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/issues/',
            {'assignee': 0},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], 'Invalid assignee filter.')


class IssueCommentAPITestCase(APITestCase):

    def setUp(self):
        self.manager = User.objects.create_user(
            username='comment_manager',
            password='TestPassword123',
        )
        self.member = User.objects.create_user(
            username='comment_member',
            password='TestPassword123',
        )
        self.viewer = User.objects.create_user(
            username='comment_viewer',
            password='TestPassword123',
        )
        self.outsider = User.objects.create_user(
            username='comment_outsider',
            password='TestPassword123',
        )

        self.project = Project.objects.create(
            key='CMT',
            name='Comment project',
            created_by=self.manager,
        )
        for user, role in (
            (self.manager, ProjectMember.Role.PROJECT_MANAGER),
            (self.member, ProjectMember.Role.TEAM_MEMBER),
            (self.viewer, ProjectMember.Role.VIEWER),
        ):
            ProjectMember.objects.create(
                project=self.project,
                user=user,
                role=role,
            )

        self.issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Commented issue',
            reporter=self.manager,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def comments_url(self):
        return f'/api/v1/issues/{self.issue.id}/comments/'

    def test_member_can_create_comment_with_authenticated_author(self):
        self.authenticate(self.member)

        response = self.client.post(
            self.comments_url(),
            {
                'body': 'Please review this.',
                'author': self.manager.id,
                'issue': 999,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['issue'], self.issue.id)
        self.assertEqual(
            response.data['author'],
            {'id': self.member.id, 'username': self.member.username},
        )
        self.assertEqual(Comment.objects.get().author, self.member)

    def test_empty_comment_is_rejected(self):
        self.authenticate(self.member)

        response = self.client.post(
            self.comments_url(),
            {'body': '   '},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('body', response.data['errors'])
        self.assertFalse(Comment.objects.exists())

    def test_viewer_can_read_but_cannot_add_comments(self):
        Comment.objects.create(
            issue=self.issue,
            author=self.manager,
            body='Existing comment',
        )
        self.authenticate(self.viewer)

        listed = self.client.get(self.comments_url())
        created = self.client.post(
            self.comments_url(),
            {'body': 'New comment'},
            format='json',
        )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data['count'], 1)
        self.assertEqual(created.status_code, 403)
        self.assertEqual(Comment.objects.count(), 1)

    def test_non_member_cannot_read_comments(self):
        self.authenticate(self.outsider)

        response = self.client.get(self.comments_url())

        self.assertEqual(response.status_code, 404)

    def test_author_can_edit_own_comment(self):
        comment = Comment.objects.create(
            issue=self.issue,
            author=self.member,
            body='Original text',
        )
        created_at = comment.created_at
        self.authenticate(self.member)

        response = self.client.patch(
            f'{self.comments_url()}{comment.id}/',
            {'body': 'Corrected text'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['body'], 'Corrected text')
        comment.refresh_from_db()
        self.assertEqual(comment.body, 'Corrected text')
        self.assertEqual(comment.created_at, created_at)
        self.assertGreaterEqual(comment.updated_at, created_at)

    def test_other_member_cannot_edit_or_delete_comment(self):
        comment = Comment.objects.create(
            issue=self.issue,
            author=self.member,
            body='Member comment',
        )
        self.authenticate(self.manager)
        comment_url = f'{self.comments_url()}{comment.id}/'

        edited = self.client.patch(
            comment_url,
            {'body': 'Changed by manager'},
            format='json',
        )
        deleted = self.client.delete(comment_url)

        self.assertEqual(edited.status_code, 403)
        self.assertEqual(deleted.status_code, 403)
        comment.refresh_from_db()
        self.assertEqual(comment.body, 'Member comment')
        self.assertFalse(comment.is_deleted)

    def test_delete_soft_deletes_comment(self):
        comment = Comment.objects.create(
            issue=self.issue,
            author=self.member,
            body='Remove this comment',
        )
        self.authenticate(self.member)

        response = self.client.delete(
            f'{self.comments_url()}{comment.id}/'
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['body'])
        self.assertTrue(response.data['is_deleted'])
        self.assertIsNotNone(response.data['deleted_at'])
        comment.refresh_from_db()
        self.assertTrue(comment.is_deleted)
        self.assertIsNone(comment.body)

    def test_comments_are_ordered_and_paginated(self):
        comments = [
            Comment.objects.create(
                issue=self.issue,
                author=self.manager,
                body=f'Comment {number}',
            )
            for number in range(3)
        ]
        self.authenticate(self.member)

        first_page = self.client.get(
            self.comments_url(),
            {'page': 1, 'page_size': 2},
        )
        second_page = self.client.get(
            self.comments_url(),
            {'page': 2, 'page_size': 2},
        )

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.data['count'], 3)
        self.assertEqual(
            [item['id'] for item in first_page.data['results']],
            [comments[0].id, comments[1].id],
        )
        self.assertEqual(
            [item['id'] for item in second_page.data['results']],
            [comments[2].id],
        )

    def test_mentions_must_be_project_members(self):
        self.authenticate(self.member)

        accepted = self.client.post(
            self.comments_url(),
            {'body': f'@{self.manager.username} please review.'},
            format='json',
        )
        rejected = self.client.post(
            self.comments_url(),
            {'body': '@comment_outsider please review.'},
            format='json',
        )

        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(Comment.objects.count(), 1)
