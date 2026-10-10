from datetime import date
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.projects.models import Project, ProjectMember

User = get_user_model()


class ProjectAPITestCase(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='TestPassword123',
        )

        response = self.client.post(
            '/api/v1/accounts/login/',
            {
                'username': 'testuser',
                'password': 'TestPassword123',
            },
            format='json',
        )

        self.access_token = response.data['access']

        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.access_token}'
        )

    def test_create_project(self):
        response = self.client.post(
            '/api/v1/projects/',
            {
                'key': 'TEST',
                'name': 'Test Project',
                'description': 'Project created in automated test',
                'start_date': '2026-10-01',
                'end_date': '2026-12-31',
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertEqual(
            response.data['key'],
            'TEST',
        )

        self.assertEqual(
            response.data['name'],
            'Test Project',
        )

        self.assertEqual(
            response.data['created_by'],
            'testuser',
        )

        self.assertFalse(
            response.data['is_archived'],
        )


    def test_list_projects(self):
        self.client.post(
            '/api/v1/projects/',
            {
                'key': 'TEST',
                'name': 'Test Project',
                'description': 'Test project',
            },
            format='json',
        )

        response = self.client.get(
            '/api/v1/projects/'
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            len(response.data['results']),
            1,
        )

        self.assertEqual(
            response.data['results'][0]['key'],
            'TEST',
        )

    def test_project_detail_and_update(self):
        create_response = self.client.post(
            '/api/v1/projects/',
            {
                'key': 'TEST',
                'name': 'Test Project',
                'description': 'Original description',
            },
            format='json',
        )

        project_id = create_response.data['id']

        response = self.client.get(
            f'/api/v1/projects/{project_id}/'
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data['key'],
            'TEST',
        )

        update_response = self.client.patch(
            f'/api/v1/projects/{project_id}/',
            {
                'name': 'Updated Test Project',
                'description': 'Updated description',
            },
            format='json',
        )

        self.assertEqual(
            update_response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            update_response.data['name'],
            'Updated Test Project',
        )

        self.assertEqual(
            update_response.data['description'],
            'Updated description',
        )

    def test_create_project_rejects_invalid_dates(self):
        response = self.client.post(
            '/api/v1/projects/',
            {
                'key': 'BAD',
                'name': 'Invalid Project',
                'description': 'Invalid date test',
                'start_date': '2026-12-31',
                'end_date': '2026-10-01',
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertIn(
            'end_date',
            response.data['errors'],
        )

    def test_archive_project(self):
        create_response = self.client.post(
            '/api/v1/projects/',
            {
                'key': 'ARCH',
                'name': 'Archive Test Project',
                'description': 'Project to be archived',
            },
            format='json',
        )

        project_id = create_response.data['id']

        archive_response = self.client.post(
            f'/api/v1/projects/{project_id}/archive/'
        )

        self.assertEqual(
            archive_response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            archive_response.data['message'],
            'Project archived successfully.',
        )

        list_response = self.client.get(
            '/api/v1/projects/'
        )

        self.assertEqual(
            list_response.status_code,
            status.HTTP_200_OK,
        )

        project_ids = [
            project['id']
            for project in list_response.data['results']
        ]

        self.assertNotIn(
            project_id,
            project_ids,
        )

        detail_response = self.client.get(
            f'/api/v1/projects/{project_id}/'
        )

        self.assertEqual(
            detail_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_project_creation_creates_manager_membership(self):
        response = self.client.post(
            '/api/v1/projects/',
            {
                'key': 'TEST',
                'name': 'Test Project',
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        project = Project.objects.get(
            key='TEST'
        )

        membership = ProjectMember.objects.get(
            project=project,
            user=self.user,
        )

        self.assertEqual(
            membership.role,
            ProjectMember.Role.PROJECT_MANAGER,
        )

    def test_non_member_cannot_view_project(self):
        project = Project.objects.create(
            key='PRIVATE',
            name='Private Project',
            created_by=self.user,
        )

        other_user = User.objects.create_user(
            username='otheruser',
            password='TestPassword123',
        )

        response = self.client.post(
            '/api/v1/accounts/login/',
            {
                'username': 'otheruser',
                'password': 'TestPassword123',
            },
            format='json',
        )

        other_access_token = response.data['access']

        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {other_access_token}'
        )

        response = self.client.get(
            f'/api/v1/projects/{project.id}/'
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_project_key_cannot_be_changed(self):
        project = Project.objects.create(
            key='IMMUT',
            name='Immutable Project',
            created_by=self.user,
        )

        ProjectMember.objects.create(
            project=project,
            user=self.user,
            role=ProjectMember.Role.PROJECT_MANAGER,
        )

        response = self.client.patch(
            f'/api/v1/projects/{project.id}/',
            {
                'key': 'CHANGED',
            },
            format='json',
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertIn(
            'key',
            response.data['errors'],
        )

        project.refresh_from_db()

        self.assertEqual(
            project.key,
            'IMMUT',
        )

    def test_last_project_manager_cannot_be_removed_or_demoted(self):
        project = Project.objects.create(
            key='MANAGER',
            name='Manager Test Project',
            created_by=self.user,
        )

        membership = ProjectMember.objects.create(
            project=project,
            user=self.user,
            role=ProjectMember.Role.PROJECT_MANAGER,
        )

        from apps.projects.services.membership import (
            ensure_not_last_project_manager,
        )

        with self.assertRaisesMessage(
            ValueError,
            'A project must have at least one project manager.',
        ):
            ensure_not_last_project_manager(
                membership=membership
            )

class ProjectMembershipAPITestCase(APITestCase):

    def setUp(self):
        self.manager = User.objects.create_user(
            username='manager', password='TestPassword123',
        )
        self.member = User.objects.create_user(
            username='member', password='TestPassword123',
        )
        self.outsider = User.objects.create_user(
            username='outsider', password='TestPassword123',
        )

        self.project = Project.objects.create(
            key='MEM', name='Members', created_by=self.manager,
        )
        self.manager_membership = ProjectMember.objects.create(
            project=self.project,
            user=self.manager,
            role=ProjectMember.Role.PROJECT_MANAGER,
        )
        self.member_membership = ProjectMember.objects.create(
            project=self.project,
            user=self.member,
            role=ProjectMember.Role.TEAM_MEMBER,
        )

        self.members_url = f'/api/v1/projects/{self.project.id}/members/'

    def login(self, user):
        self.client.force_authenticate(user=user)

    def test_project_includes_my_role(self):
        self.login(self.member)

        response = self.client.get(f'/api/v1/projects/{self.project.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['my_role'], 'TEAM_MEMBER')

        response = self.client.get('/api/v1/projects/')
        self.assertEqual(response.data['results'][0]['my_role'], 'TEAM_MEMBER')

    def test_validation_error_shape(self):
        self.login(self.manager)

        response = self.client.post('/api/v1/projects/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Validation failed.')
        self.assertEqual(response.data['code'], 'validation_error')
        self.assertIn('key', response.data['errors'])

    def test_not_found_error_shape(self):
        self.login(self.manager)

        response = self.client.get('/api/v1/projects/99999/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('detail', response.data)
        self.assertIn('code', response.data)

    def test_unauthenticated_error_shape(self):
        response = self.client.get('/api/v1/projects/')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('detail', response.data)
        self.assertIn('code', response.data)

    def test_member_can_list_members(self):
        self.login(self.member)

        response = self.client.get(self.members_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]['username'], 'manager')

    def test_outsider_cannot_list_members(self):
        self.login(self.outsider)

        response = self.client.get(self.members_url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_manager_can_add_member(self):
        self.login(self.manager)

        response = self.client.post(
            self.members_url,
            {'user_id': self.outsider.id, 'role': 'VIEWER'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['role'], 'VIEWER')
        self.assertTrue(
            ProjectMember.objects.filter(
                project=self.project, user=self.outsider,
            ).exists()
        )

    def test_member_cannot_add_member(self):
        self.login(self.member)

        response = self.client.post(
            self.members_url,
            {'user_id': self.outsider.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_add_duplicate_member(self):
        self.login(self.manager)

        response = self.client.post(
            self.members_url,
            {'user_id': self.member.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_add_unknown_user(self):
        self.login(self.manager)

        response = self.client.post(
            self.members_url, {'user_id': 99999}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_manager_can_change_role(self):
        self.login(self.manager)

        response = self.client.patch(
            f'{self.members_url}{self.member_membership.id}/',
            {'role': 'VIEWER'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, 'VIEWER')

    def test_cannot_demote_last_manager(self):
        self.login(self.manager)

        response = self.client.patch(
            f'{self.members_url}{self.manager_membership.id}/',
            {'role': 'TEAM_MEMBER'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_make_member_a_viewer_while_issues_are_assigned(self):
        from apps.issues.models import Issue

        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Open work',
            reporter=self.manager,
            assignee=self.member,
        )
        self.login(self.manager)

        response = self.client.patch(
            f'{self.members_url}{self.member_membership.id}/',
            {'role': 'VIEWER'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, 'TEAM_MEMBER')

    def test_archived_issues_do_not_block_making_a_member_a_viewer(self):
        from apps.issues.models import Issue

        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Old work',
            reporter=self.manager,
            assignee=self.member,
            is_archived=True,
        )
        self.login(self.manager)

        response = self.client.patch(
            f'{self.members_url}{self.member_membership.id}/',
            {'role': 'VIEWER'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, 'VIEWER')

    def test_issues_assigned_to_others_do_not_block_the_change(self):
        from apps.issues.models import Issue

        Issue.objects.create(
            project=self.project,
            issue_number=1,
            title="Manager's work",
            reporter=self.manager,
            assignee=self.manager,
        )
        self.login(self.manager)

        response = self.client.patch(
            f'{self.members_url}{self.member_membership.id}/',
            {'role': 'VIEWER'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_manager_can_remove_member_and_unassigns_issues(self):
        from apps.issues.models import Issue

        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Assigned',
            reporter=self.manager,
            assignee=self.member,
        )

        self.login(self.manager)

        response = self.client.delete(
            f'{self.members_url}{self.member_membership.id}/'
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        issue.refresh_from_db()
        self.assertIsNone(issue.assignee)

    def test_member_can_leave_but_not_remove_others(self):
        self.login(self.member)

        response = self.client.delete(
            f'{self.members_url}{self.manager_membership.id}/'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.delete(
            f'{self.members_url}{self.member_membership.id}/'
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_cannot_remove_last_manager(self):
        self.login(self.manager)

        response = self.client.delete(
            f'{self.members_url}{self.manager_membership.id}/'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_issue_includes_user_details(self):
        from apps.issues.models import Issue

        issue = Issue.objects.create(
            project=self.project,
            issue_number=1,
            title='Detail',
            reporter=self.manager,
            assignee=self.member,
        )

        self.login(self.manager)

        response = self.client.get(f'/api/v1/issues/{issue.id}/')

        self.assertEqual(
            response.data['assignee_detail'],
            {'id': self.member.id, 'username': 'member'},
        )
        self.assertEqual(
            response.data['reporter_detail'],
            {'id': self.manager.id, 'username': 'manager'},
        )
        self.assertEqual(response.data['reporter'], 'manager')
        self.assertEqual(response.data['assignee'], self.member.id)
