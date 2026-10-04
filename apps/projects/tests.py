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
            len(response.data),
            1,
        )

        self.assertEqual(
            response.data[0]['key'],
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
            response.data,
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
            for project in list_response.data
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
            response.data,
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