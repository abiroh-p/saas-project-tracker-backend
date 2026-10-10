from datetime import timedelta

from django.utils import timezone
from rest_framework import status

from .models import Activity
from .testing import ActivityAPITestCase


class ProjectActivityAPITests(ActivityAPITestCase):

    url = '/api/v1/projects/{}/activity/'

    def activity(self, *, user=None, action=Activity.Action.PROJECT_UPDATED,
                 entity_type=Activity.EntityType.PROJECT, entity_id=1):
        return Activity.objects.create(
            project=self.project,
            user=user or self.manager,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=f'{action} event',
            metadata={'action': action},
        )

    def get_url(self):
        return self.url.format(self.project.id)

    def test_member_can_list_project_activity(self):
        activity = self.activity()

        response = self.client.get(self.get_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], activity.id)
        self.assertEqual(
            response.data['results'][0]['user'],
            {'id': self.manager.id, 'username': self.manager.username},
        )

    def test_non_member_cannot_list_project_activity(self):
        self.client.force_authenticate(user=self.newcomer)

        response = self.client.get(self.get_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_filters_by_action_and_entity(self):
        self.activity(action=Activity.Action.PROJECT_UPDATED)
        matching = self.activity(
            action=Activity.Action.ISSUE_UPDATED,
            entity_type=Activity.EntityType.ISSUE,
            entity_id=42,
        )

        response = self.client.get(
            self.get_url(),
            {
                'action': Activity.Action.ISSUE_UPDATED,
                'entity_type': Activity.EntityType.ISSUE,
                'entity_id': 42,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], matching.id)

    def test_invalid_filter_is_rejected(self):
        response = self.client.get(
            self.get_url(),
            {'entity_id': 'not-an-integer'},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_results_are_paginated(self):
        for index in range(3):
            self.activity(entity_id=index + 1)

        response = self.client.get(
            self.get_url(),
            {'page_size': 2},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual(len(response.data['results']), 2)
        self.assertIsNotNone(response.data['next'])
