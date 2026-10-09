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


class RegistrationAPITestCase(APITestCase):
    url = '/api/v1/accounts/register/'

    def payload(self, **overrides):
        data = {
            'full_name': 'Jane Doe',
            'email': 'jane.doe@example.com',
            'password': 'TestPassword123',
        }
        data.update(overrides)
        return data

    def test_register_generates_username_from_email(self):
        response = self.client.post(self.url, self.payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data['user'],
            {
                'id': response.data['user']['id'],
                'username': 'jane.doe',
                'email': 'jane.doe@example.com',
                'full_name': 'Jane Doe',
                'role': 'TEAM_MEMBER',
            },
        )
        user = User.objects.get(username='jane.doe')
        self.assertTrue(user.check_password('TestPassword123'))

    def test_password_confirm_is_optional(self):
        response = self.client.post(self.url, self.payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_matching_password_confirm_is_accepted(self):
        response = self.client.post(
            self.url,
            self.payload(password_confirm='TestPassword123'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_mismatched_password_confirm_is_rejected(self):
        response = self.client.post(
            self.url,
            self.payload(password_confirm='Different123'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'validation_error')
        self.assertIn('password_confirm', response.data['errors'])
        self.assertFalse(User.objects.exists())

    def test_username_collision_gets_numeric_suffix(self):
        User.objects.create_user(username='jane.doe', password='x')
        User.objects.create_user(username='Jane.Doe2', password='x')

        response = self.client.post(self.url, self.payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['user']['username'], 'jane.doe3')

    def test_username_sent_by_client_is_ignored(self):
        response = self.client.post(
            self.url,
            self.payload(username='chosen'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['user']['username'], 'jane.doe')

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.client.post(self.url, self.payload(), format='json')

        response = self.client.post(
            self.url,
            self.payload(email='JANE.DOE@Example.com', full_name='Other'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'validation_error')
        self.assertIn('email', response.data['errors'])
        self.assertEqual(User.objects.count(), 1)

    def test_required_fields(self):
        response = self.client.post(self.url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            set(response.data['errors']),
            {'full_name', 'email', 'password'},
        )

    def test_blank_full_name_is_rejected(self):
        response = self.client.post(
            self.url,
            self.payload(full_name='   '),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('full_name', response.data['errors'])

    def test_short_password_is_rejected(self):
        response = self.client.post(
            self.url,
            self.payload(password='short'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data['errors'])

    def test_email_is_stored_lowercase(self):
        response = self.client.post(
            self.url,
            self.payload(email='Jane.Doe@Example.COM'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data['user']['email'], 'jane.doe@example.com',
        )


class UsernameGenerationTestCase(APITestCase):

    def test_username_base_strips_unsafe_characters(self):
        from apps.accounts.services.registration import (
            username_base_from_email,
        )

        self.assertEqual(
            username_base_from_email('John.Smith+news@x.com'), 'john.smithnews',
        )
        self.assertEqual(username_base_from_email('..__@x.com'), 'user')
        self.assertEqual(username_base_from_email('émile@x.com'), 'mile')

    def test_username_base_is_length_limited(self):
        from apps.accounts.services.registration import (
            USERNAME_MAX_LENGTH,
            username_base_from_email,
        )

        base = username_base_from_email(f"{'a' * 300}@x.com")

        self.assertLess(len(base), USERNAME_MAX_LENGTH)


class LoginAPITestCase(APITestCase):
    url = '/api/v1/accounts/login/'

    def setUp(self):
        self.user = User.objects.create_user(
            username='jane',
            email='jane@example.com',
            password='TestPassword123',
            full_name='Jane Doe',
        )

    def login(self, **data):
        return self.client.post(self.url, data, format='json')

    def assert_logged_in(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['user']['id'], self.user.id)
        self.assertEqual(response.data['user']['full_name'], 'Jane Doe')

    def test_login_with_username(self):
        self.assert_logged_in(
            self.login(identifier='jane', password='TestPassword123'),
        )

    def test_login_with_email(self):
        self.assert_logged_in(
            self.login(identifier='jane@example.com', password='TestPassword123'),
        )

    def test_email_login_is_case_insensitive(self):
        self.assert_logged_in(
            self.login(identifier='Jane@EXAMPLE.com', password='TestPassword123'),
        )

    def test_legacy_username_field_still_works(self):
        self.assert_logged_in(
            self.login(username='jane', password='TestPassword123'),
        )

    def test_wrong_password_is_rejected(self):
        for identifier in ('jane', 'jane@example.com'):
            response = self.login(identifier=identifier, password='nope')

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data['code'], 'validation_error')
            self.assertEqual(
                response.data['errors']['non_field_errors'],
                ['Invalid email/username or password.'],
            )

    def test_unknown_identifier_gets_the_same_error(self):
        response = self.login(identifier='ghost@example.com', password='x')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data['errors']['non_field_errors'],
            ['Invalid email/username or password.'],
        )

    def test_missing_identifier_is_a_field_error(self):
        response = self.login(password='TestPassword123')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('identifier', response.data['errors'])

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()

        response = self.login(
            identifier='jane@example.com', password='TestPassword123',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registered_user_can_log_in_with_email(self):
        self.client.post(
            '/api/v1/accounts/register/',
            {
                'full_name': 'New Person',
                'email': 'new.person@example.com',
                'password': 'TestPassword123',
            },
            format='json',
        )

        response = self.login(
            identifier='new.person@example.com', password='TestPassword123',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['username'], 'new.person')


class ProfileAPITestCase(APITestCase):
    url = '/api/v1/accounts/profile/'

    def setUp(self):
        self.user = User.objects.create_user(
            username='jane',
            email='jane@example.com',
            password='TestPassword123',
            full_name='Jane Doe',
        )
        User.objects.create_user(
            username='bob', email='bob@example.com', password='x',
        )
        self.client.force_authenticate(user=self.user)

    def test_me_and_profile_include_full_name(self):
        for url in ('/api/v1/accounts/me/', self.url):
            response = self.client.get(url)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.data,
                {
                    'id': self.user.id,
                    'username': 'jane',
                    'email': 'jane@example.com',
                    'full_name': 'Jane Doe',
                    'role': 'TEAM_MEMBER',
                },
            )

    def test_patch_full_name(self):
        response = self.client.patch(
            self.url, {'full_name': 'Jane Q. Doe'}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, 'Jane Q. Doe')

    def test_username_and_role_are_read_only(self):
        self.client.patch(
            self.url, {'username': 'hacker', 'role': 'ADMIN'}, format='json',
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'jane')
        self.assertEqual(self.user.role, 'TEAM_MEMBER')

    def test_cannot_take_another_users_email(self):
        response = self.client.patch(
            self.url, {'email': 'BOB@example.com'}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data['errors'])

    def test_can_resubmit_own_email(self):
        response = self.client.patch(
            self.url, {'email': 'Jane@Example.com'}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'jane@example.com')

    def test_blank_full_name_is_rejected(self):
        response = self.client.patch(
            self.url, {'full_name': ''}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
