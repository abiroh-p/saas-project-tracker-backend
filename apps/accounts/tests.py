from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class UserSearchAPITestCase(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='alice', password='TestPassword123',
        )
        User.objects.create_user(
            username='alicia', password='TestPassword123',
        )
        User.objects.create_user(
            username='bob', password='TestPassword123',
        )
        User.objects.create_user(
            username='alina', password='TestPassword123', is_active=False,
        )

    def test_requires_authentication(self):
        response = self.client.get('/api/v1/accounts/users/?search=al')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_search_returns_matching_active_users(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get('/api/v1/accounts/users/?search=ali')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [u['username'] for u in response.data],
            ['alice', 'alicia'],
        )
        self.assertEqual(set(response.data[0].keys()), {'id', 'username'})

    def test_short_search_term_is_rejected(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get('/api/v1/accounts/users/?search=a')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
