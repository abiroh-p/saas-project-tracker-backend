from datetime import timedelta
from unittest import mock

from django.utils import timezone
from rest_framework import status

from apps.projects.models import Project, ProjectMember

from .models import Activity
from .testing import ActivityAPITestCase

FIELDS = {
    'id',
    'user',
    'action',
    'entity_type',
    'entity_id',
    'description',
    'metadata',
    'created_at',
}


class FeedTestCase(ActivityAPITestCase):

    def activity(
        self,
        *,
        project=None,
        user=None,
        action=Activity.Action.PROJECT_UPDATED,
        entity_type=Activity.EntityType.PROJECT,
        entity_id=1,
        metadata=None,
    ):
        return Activity.objects.create(
            project=project or self.project,
            user=user or self.manager,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=f'{action} event',
            metadata={'action': action} if metadata is None else metadata,
        )

    def ids(self, response):
        return [item['id'] for item in response.data['results']]

    def error_fields(self, response):
        return set(response.data['errors'])


class ProjectActivityAPITests(FeedTestCase):

    def url(self, project=None):
        return f'/api/v1/projects/{(project or self.project).id}/activity/'

    def get(self, params=None, project=None):
        return self.client.get(self.url(project), params or {})

    # -- access ---------------------------------------------------------

    def test_member_can_list_project_activity(self):
        activity = self.activity()

        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], activity.id)
        self.assertEqual(
            response.data['results'][0]['user'],
            {'id': self.manager.id, 'username': self.manager.username},
        )

    def test_every_role_can_read(self):
        self.activity()

        for user in (self.manager, self.member, self.viewer):
            self.client.force_authenticate(user=user)

            response = self.get()

            self.assertEqual(response.status_code, 200, user.username)
            self.assertEqual(response.data['count'], 1)

    def test_unauthenticated_requests_are_rejected(self):
        self.client.force_authenticate(user=None)

        self.assertEqual(self.get().status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_member_gets_the_same_404_as_a_missing_project(self):
        self.activity()
        self.client.force_authenticate(user=self.newcomer)

        hidden = self.get()
        missing = self.client.get('/api/v1/projects/999999/activity/')

        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(hidden.data, missing.data)

    def test_removed_members_lose_access(self):
        self.activity()
        self.viewer_membership.delete()
        self.client.force_authenticate(user=self.viewer)

        self.assertEqual(self.get().status_code, status.HTTP_404_NOT_FOUND)

    def test_members_added_later_can_read_older_events(self):
        old = self.activity()
        self.client.force_authenticate(user=self.newcomer)
        self.assertEqual(self.get().status_code, 404)

        self.add_member(self.newcomer, ProjectMember.Role.VIEWER)

        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.ids(response), [old.id])

    def test_archived_projects_stay_readable(self):
        self.activity(action=Activity.Action.PROJECT_ARCHIVED)
        self.project.is_archived = True
        self.project.save()

        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_only_this_projects_activity_is_returned(self):
        other = Project.objects.create(
            key='OTH', name='Other', created_by=self.manager,
        )
        self.add_member(
            self.manager, ProjectMember.Role.PROJECT_MANAGER, other,
        )
        mine = self.activity()
        self.activity(project=other)

        response = self.get()

        self.assertEqual(self.ids(response), [mine.id])

    def test_membership_in_another_project_grants_nothing(self):
        other = Project.objects.create(
            key='OTH', name='Other', created_by=self.newcomer,
        )
        self.add_member(
            self.newcomer, ProjectMember.Role.PROJECT_MANAGER, other,
        )
        self.activity()
        self.client.force_authenticate(user=self.newcomer)

        self.assertEqual(self.get().status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.get(project=other).status_code, 200)

    # -- shape ----------------------------------------------------------

    def test_response_shape(self):
        self.activity(metadata={'changes': {'name': {'from': 'A', 'to': 'B'}}})

        item = self.get().data['results'][0]

        self.assertEqual(set(item), FIELDS)
        self.assertEqual(set(item['user']), {'id', 'username'})
        self.assertEqual(
            item['metadata'], {'changes': {'name': {'from': 'A', 'to': 'B'}}},
        )

    def test_empty_history(self):
        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])

    # -- ordering and pagination ----------------------------------------

    def test_newest_first(self):
        now = timezone.now()
        created = []

        for offset in range(3):
            with mock.patch(
                'django.utils.timezone.now',
                return_value=now + timedelta(minutes=offset),
            ):
                created.append(self.activity(entity_id=offset + 1))

        self.assertEqual(
            self.ids(self.get()), [a.id for a in reversed(created)],
        )

    def test_equal_timestamps_are_ordered_by_id_descending(self):
        frozen = timezone.now()

        with mock.patch('django.utils.timezone.now', return_value=frozen):
            created = [self.activity(entity_id=i + 1) for i in range(4)]

        self.assertEqual(
            self.ids(self.get()), [a.id for a in reversed(created)],
        )

    def test_results_are_paginated(self):
        for index in range(3):
            self.activity(entity_id=index + 1)

        response = self.get({'page_size': 2})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual(len(response.data['results']), 2)
        self.assertIsNotNone(response.data['next'])
        self.assertIsNone(response.data['previous'])

    def test_pages_do_not_overlap_and_cover_everything(self):
        created = [self.activity(entity_id=i + 1) for i in range(5)]

        first = self.get({'page_size': 2, 'page': 1})
        second = self.get({'page_size': 2, 'page': 2})
        third = self.get({'page_size': 2, 'page': 3})

        self.assertEqual(
            self.ids(first) + self.ids(second) + self.ids(third),
            [a.id for a in reversed(created)],
        )
        self.assertIsNone(third.data['next'])
        self.assertIsNotNone(third.data['previous'])

    def test_default_page_size_is_twenty(self):
        Activity.objects.bulk_create([
            Activity(
                project=self.project,
                user=self.manager,
                action=Activity.Action.PROJECT_UPDATED,
                entity_type=Activity.EntityType.PROJECT,
                entity_id=1,
                description='x',
            )
            for _ in range(25)
        ])

        response = self.get()

        self.assertEqual(response.data['count'], 25)
        self.assertEqual(len(response.data['results']), 20)

    def test_page_size_is_capped_at_one_hundred(self):
        Activity.objects.bulk_create([
            Activity(
                project=self.project,
                user=self.manager,
                action=Activity.Action.PROJECT_UPDATED,
                entity_type=Activity.EntityType.PROJECT,
                entity_id=1,
                description='x',
            )
            for _ in range(105)
        ])

        response = self.get({'page_size': 1000})

        self.assertEqual(len(response.data['results']), 100)

    def test_page_beyond_the_end_is_not_found(self):
        self.activity()

        self.assertEqual(self.get({'page': 5}).status_code, 404)

    # -- filters --------------------------------------------------------

    def test_filters_by_action(self):
        self.activity(action=Activity.Action.PROJECT_UPDATED)
        wanted = self.activity(action=Activity.Action.MEMBER_ADDED)

        response = self.get({'action': 'MEMBER_ADDED'})

        self.assertEqual(self.ids(response), [wanted.id])

    def test_filters_by_entity_type(self):
        self.activity(entity_type=Activity.EntityType.PROJECT)
        wanted = self.activity(
            action=Activity.Action.MEMBER_REMOVED,
            entity_type=Activity.EntityType.MEMBERSHIP,
        )

        response = self.get({'entity_type': 'MEMBERSHIP'})

        self.assertEqual(self.ids(response), [wanted.id])

    def test_filters_by_user(self):
        self.activity(user=self.manager)
        wanted = self.activity(user=self.member)

        response = self.get({'user': self.member.id})

        self.assertEqual(self.ids(response), [wanted.id])

    def test_filtering_by_an_unknown_user_returns_nothing(self):
        self.activity()

        response = self.get({'user': 999999})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

    def test_filters_by_action_and_entity(self):
        self.activity(action=Activity.Action.PROJECT_UPDATED)
        matching = self.activity(
            action=Activity.Action.ISSUE_UPDATED,
            entity_type=Activity.EntityType.ISSUE,
            entity_id=42,
        )

        response = self.get({
            'action': Activity.Action.ISSUE_UPDATED,
            'entity_type': Activity.EntityType.ISSUE,
            'entity_id': 42,
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], matching.id)

    def test_entity_ids_of_different_types_do_not_mix(self):
        issue_event = self.activity(
            action=Activity.Action.ISSUE_UPDATED,
            entity_type=Activity.EntityType.ISSUE,
            entity_id=7,
        )
        self.activity(
            action=Activity.Action.ROLE_CHANGED,
            entity_type=Activity.EntityType.MEMBERSHIP,
            entity_id=7,
        )

        response = self.get({'entity_type': 'ISSUE', 'entity_id': 7})

        self.assertEqual(self.ids(response), [issue_event.id])

    def test_filters_combine_with_pagination(self):
        for index in range(3):
            self.activity(action=Activity.Action.MEMBER_ADDED, entity_id=index + 1)
        self.activity(action=Activity.Action.PROJECT_UPDATED)

        response = self.get({'action': 'MEMBER_ADDED', 'page_size': 2})

        self.assertEqual(response.data['count'], 3)
        self.assertEqual(len(response.data['results']), 2)

    def test_invalid_filters_are_rejected_in_the_standard_error_format(self):
        cases = {
            'action': 'NOT_AN_ACTION',
            'entity_type': 'COMMENT',
            'entity_id': 'not-an-integer',
            'user': 'abc',
        }

        for name, value in cases.items():
            response = self.get({name: value})

            self.assertEqual(
                response.status_code, status.HTTP_400_BAD_REQUEST, name,
            )
            self.assertEqual(response.data['code'], 'validation_error')
            self.assertIn(name, self.error_fields(response))

    def test_ids_must_be_positive(self):
        for name in ('entity_id', 'user'):
            for value in (0, -1):
                params = {name: value}
                if name == 'entity_id':
                    params['entity_type'] = 'ISSUE'

                self.assertEqual(self.get(params).status_code, 400, params)

    def test_entity_id_requires_entity_type(self):
        response = self.get({'entity_id': 5})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('entity_type', self.error_fields(response))

    def test_invalid_filters_do_not_reveal_a_project_to_non_members(self):
        self.client.force_authenticate(user=self.newcomer)

        response = self.get({'action': 'NOT_AN_ACTION'})

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -- read-only ------------------------------------------------------

    def test_feed_is_read_only(self):
        activity = self.activity()
        payload = {
            'action': 'PROJECT_CREATED',
            'entity_type': 'PROJECT',
            'entity_id': 1,
            'description': 'forged',
        }

        for method in ('post', 'put', 'patch', 'delete'):
            response = getattr(self.client, method)(
                self.url(), payload, format='json',
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_405_METHOD_NOT_ALLOWED,
                method,
            )

        self.assertEqual(Activity.objects.count(), 1)
        activity.refresh_from_db()
        self.assertEqual(activity.description, 'PROJECT_UPDATED event')


class IssueActivityAPITests(FeedTestCase):

    def setUp(self):
        super().setUp()
        self.issue = self.make_issue(1)
        self.other_issue = self.make_issue(2)

    def url(self, issue=None):
        return f'/api/v1/issues/{(issue or self.issue).id}/activity/'

    def get(self, params=None, issue=None):
        return self.client.get(self.url(issue), params or {})

    def issue_event(self, issue=None, **kwargs):
        issue = issue or self.issue
        kwargs.setdefault('action', Activity.Action.ISSUE_UPDATED)

        return self.activity(
            entity_type=Activity.EntityType.ISSUE,
            entity_id=issue.id,
            **kwargs,
        )

    # -- access ---------------------------------------------------------

    def test_member_can_list_issue_activity(self):
        event = self.issue_event()

        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.ids(response), [event.id])
        self.assertEqual(set(response.data['results'][0]), FIELDS)
        self.assertEqual(
            response.data['results'][0]['user'],
            {'id': self.manager.id, 'username': 'manager'},
        )

    def test_every_role_can_read(self):
        self.issue_event()

        for user in (self.manager, self.member, self.viewer):
            self.client.force_authenticate(user=user)

            response = self.get()

            self.assertEqual(response.status_code, 200, user.username)
            self.assertEqual(response.data['count'], 1)

    def test_unauthenticated_requests_are_rejected(self):
        self.client.force_authenticate(user=None)

        self.assertEqual(self.get().status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_member_gets_the_same_404_as_a_missing_issue(self):
        self.issue_event()
        self.client.force_authenticate(user=self.newcomer)

        hidden = self.get()
        missing = self.client.get('/api/v1/issues/999999/activity/')

        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(hidden.data, missing.data)

    def test_membership_in_another_project_grants_nothing(self):
        other = Project.objects.create(
            key='OTH', name='Other', created_by=self.newcomer,
        )
        self.add_member(
            self.newcomer, ProjectMember.Role.PROJECT_MANAGER, other,
        )
        self.issue_event()
        self.client.force_authenticate(user=self.newcomer)

        self.assertEqual(self.get().status_code, status.HTTP_404_NOT_FOUND)

    def test_members_added_later_can_read_older_events(self):
        old = self.issue_event()
        self.client.force_authenticate(user=self.newcomer)
        self.assertEqual(self.get().status_code, 404)

        self.add_member(self.newcomer, ProjectMember.Role.VIEWER)

        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.ids(response), [old.id])

    def test_archived_issues_and_projects_stay_readable(self):
        self.issue_event(action=Activity.Action.ISSUE_ARCHIVED)
        self.issue.is_archived = True
        self.issue.save()

        self.assertEqual(self.get().status_code, status.HTTP_200_OK)

        self.project.is_archived = True
        self.project.save()

        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    # -- scoping --------------------------------------------------------

    def test_only_this_issues_events_are_returned(self):
        mine = self.issue_event()
        self.issue_event(issue=self.other_issue)

        response = self.get()

        self.assertEqual(self.ids(response), [mine.id])

    def test_project_and_membership_events_with_the_same_id_are_excluded(self):
        mine = self.issue_event()
        # Same numeric id, different entity type.
        self.activity(
            action=Activity.Action.ROLE_CHANGED,
            entity_type=Activity.EntityType.MEMBERSHIP,
            entity_id=self.issue.id,
        )
        self.activity(
            action=Activity.Action.PROJECT_UPDATED,
            entity_type=Activity.EntityType.PROJECT,
            entity_id=self.issue.id,
        )

        response = self.get()

        self.assertEqual(self.ids(response), [mine.id])

    # -- ordering, pagination, filters ----------------------------------

    def test_newest_first_with_stable_ties(self):
        frozen = timezone.now()

        with mock.patch('django.utils.timezone.now', return_value=frozen):
            created = [self.issue_event() for _ in range(4)]

        self.assertEqual(
            self.ids(self.get()), [e.id for e in reversed(created)],
        )

    def test_results_are_paginated(self):
        created = [self.issue_event() for _ in range(5)]

        first = self.get({'page_size': 2, 'page': 1})
        third = self.get({'page_size': 2, 'page': 3})

        self.assertEqual(first.data['count'], 5)
        self.assertEqual(len(first.data['results']), 2)
        self.assertIsNotNone(first.data['next'])
        self.assertEqual(self.ids(third), [created[0].id])
        self.assertIsNone(third.data['next'])

    def test_filters_by_action(self):
        self.issue_event(action=Activity.Action.ISSUE_UPDATED)
        wanted = self.issue_event(action=Activity.Action.ISSUE_STATUS_CHANGED)

        response = self.get({'action': 'ISSUE_STATUS_CHANGED'})

        self.assertEqual(self.ids(response), [wanted.id])

    def test_filters_by_user(self):
        self.issue_event(user=self.manager)
        wanted = self.issue_event(user=self.member)

        response = self.get({'user': self.member.id})

        self.assertEqual(self.ids(response), [wanted.id])

    def test_invalid_filters_are_rejected_in_the_standard_error_format(self):
        for name, value in (('action', 'NOPE'), ('user', 'abc'), ('user', 0)):
            response = self.get({name: value})

            self.assertEqual(response.status_code, 400, (name, value))
            self.assertEqual(response.data['code'], 'validation_error')
            self.assertIn(name, self.error_fields(response))

    def test_invalid_filters_do_not_reveal_an_issue_to_non_members(self):
        self.client.force_authenticate(user=self.newcomer)

        self.assertEqual(
            self.get({'action': 'NOPE'}).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_feed_is_read_only(self):
        event = self.issue_event()

        for method in ('post', 'put', 'patch', 'delete'):
            response = getattr(self.client, method)(
                self.url(), {'description': 'forged'}, format='json',
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_405_METHOD_NOT_ALLOWED,
                method,
            )

        self.assertEqual(Activity.objects.count(), 1)
        event.refresh_from_db()
        self.assertEqual(event.description, 'ISSUE_UPDATED event')


class ActivityFeedEndToEndTests(FeedTestCase):
    """Events written by real requests show up in both feeds."""

    def test_an_issues_life_appears_in_the_issue_and_project_feeds(self):
        created = self.client.post(
            f'/api/v1/projects/{self.project.id}/issues/',
            {'title': 'Ship it'},
            format='json',
        )
        issue_id = created.data['id']

        self.client.patch(
            f'/api/v1/issues/{issue_id}/',
            {'assignee': self.member.id, 'priority': 'HIGH'},
            format='json',
        )
        self.client.post(
            f'/api/v1/issues/{issue_id}/transition/',
            {'status': 'IN_PROGRESS'},
            format='json',
        )

        # A viewer can read the history.
        self.client.force_authenticate(user=self.viewer)

        issue_feed = self.client.get(f'/api/v1/issues/{issue_id}/activity/')
        project_feed = self.client.get(
            f'/api/v1/projects/{self.project.id}/activity/',
        )

        expected = [
            'ISSUE_STATUS_CHANGED',
            'ISSUE_ASSIGNED',
            'ISSUE_UPDATED',
            'ISSUE_CREATED',
        ]
        self.assertEqual(
            [item['action'] for item in issue_feed.data['results']], expected,
        )
        self.assertEqual(
            [item['action'] for item in project_feed.data['results']],
            expected,
        )

    def test_project_feed_records_changes_made_through_the_api(self):
        self.client.patch(
            f'/api/v1/projects/{self.project.id}/',
            {'name': 'Renamed'},
            format='json',
        )
        self.client.post(
            f'/api/v1/projects/{self.project.id}/members/',
            {'user_id': self.newcomer.id, 'role': 'VIEWER'},
            format='json',
        )

        response = self.client.get(
            f'/api/v1/projects/{self.project.id}/activity/',
            {'user': self.manager.id},
        )

        self.assertEqual(
            [item['action'] for item in response.data['results']],
            ['MEMBER_ADDED', 'PROJECT_UPDATED'],
        )
