from unittest import mock

from rest_framework import status

from apps.issues.models import Issue

from .exceptions import ActivityError
from .models import Activity
from .services import activity as activity_service
from .testing import ActivityAPITestCase

ISSUE_WRITER = 'apps.issues.services.issue.record_activity'


class IssueEventTestCase(ActivityAPITestCase):

    def issues_url(self):
        return f'/api/v1/projects/{self.project.id}/issues/'

    def issue_url(self, issue, suffix=''):
        return f'/api/v1/issues/{issue.id}/{suffix}'

    def issue_events(self, issue):
        return Activity.objects.filter(
            entity_type='ISSUE', entity_id=issue.id,
        )

    def ref(self, user):
        return {'id': user.id, 'username': user.username}

    def fail_on(self, action):
        """A writer that works until it is asked to record `action`."""
        def writer(**kwargs):
            if kwargs['action'] == action:
                raise ActivityError('boom')
            return activity_service.record_activity(**kwargs)

        return mock.patch(ISSUE_WRITER, side_effect=writer)


class IssueCreatedEventTests(IssueEventTestCase):

    def create(self, **data):
        payload = {'title': 'Fix login', 'issue_type': 'BUG', 'priority': 'HIGH'}
        payload.update(data)

        return self.client.post(self.issues_url(), payload, format='json')

    def test_create_records_one_event(self):
        self.client.force_authenticate(user=self.member)

        response = self.create()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        issue = Issue.objects.get()

        event = self.only_event()
        self.assertEqual(event.action, 'ISSUE_CREATED')
        self.assertEqual(event.project, self.project)
        self.assertEqual(event.user, self.member)
        self.assertEqual(event.entity_type, 'ISSUE')
        self.assertEqual(event.entity_id, issue.id)
        self.assertEqual(event.description, 'member created ACT-1: Fix login')
        self.assertEqual(
            event.metadata,
            {
                'issue_key': 'ACT-1',
                'title': 'Fix login',
                'issue_type': 'BUG',
                'priority': 'HIGH',
                'assignee': None,
            },
        )

    def test_creating_with_an_assignee_is_still_a_single_event(self):
        response = self.create(assignee=self.member.id)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        event = self.only_event()
        self.assertEqual(event.action, 'ISSUE_CREATED')
        self.assertEqual(event.metadata['assignee'], self.ref(self.member))

    def test_rejected_creates_record_nothing(self):
        cases = [
            (self.manager, {'assignee': self.newcomer.id}, 400),
            (self.manager, {'assignee': self.viewer.id}, 400),
            (self.manager, {'title': ''}, 400),
            (self.viewer, {}, 403),
        ]

        for user, data, expected in cases:
            self.client.force_authenticate(user=user)

            response = self.create(**data)

            self.assertEqual(response.status_code, expected, data)

        self.assertFalse(Issue.objects.exists())
        self.assertFalse(Activity.objects.exists())

    def test_logging_failure_rolls_back_the_issue_and_its_number(self):
        self.client.raise_request_exception = False

        with mock.patch(ISSUE_WRITER, side_effect=ActivityError('boom')):
            response = self.create()

        self.assertEqual(response.status_code, 500)
        self.assertFalse(Issue.objects.exists())
        self.project.refresh_from_db()
        self.assertEqual(self.project.issue_counter, 0)
        self.assertFalse(Activity.objects.exists())


class IssueUpdatedEventTests(IssueEventTestCase):

    def setUp(self):
        super().setUp()
        self.issue = self.make_issue(
            1, priority='MEDIUM', description='Original text',
        )

    def patch(self, data, issue=None):
        return self.client.patch(
            self.issue_url(issue or self.issue), data, format='json',
        )

    def test_records_old_and_new_raw_values(self):
        response = self.patch({'priority': 'HIGH', 'title': 'Renamed'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = self.only_event()
        self.assertEqual(event.action, 'ISSUE_UPDATED')
        self.assertEqual(event.project, self.project)
        self.assertEqual(event.user, self.manager)
        self.assertEqual(event.entity_type, 'ISSUE')
        self.assertEqual(event.entity_id, self.issue.id)
        self.assertEqual(
            event.metadata,
            {
                'changes': {
                    'priority': {'from': 'MEDIUM', 'to': 'HIGH'},
                    'title': {'from': 'Issue 1', 'to': 'Renamed'},
                },
            },
        )
        self.assertIn('manager updated ACT-1', event.description)

    def test_description_text_is_not_stored_and_dates_are_iso(self):
        self.patch({'description': 'Secret new text', 'due_date': '2026-03-01'})

        event = self.only_event()
        self.assertEqual(
            event.metadata['changes'],
            {
                'description': {'changed': True},
                'due_date': {'from': None, 'to': '2026-03-01'},
            },
        )
        self.assertNotIn('Secret', str(event.metadata))
        self.assertNotIn('Secret', event.description)

    def test_noop_patches_record_nothing(self):
        for data in (
            {},
            {'priority': 'MEDIUM'},
            {'title': 'Issue 1', 'description': 'Original text'},
        ):
            self.assertEqual(self.patch(data).status_code, 200)

        self.assertFalse(Activity.objects.exists())

    def test_status_cannot_be_changed_through_patch(self):
        response = self.patch({'status': 'DONE'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, 'TODO')
        self.assertFalse(Activity.objects.exists())

    def test_assigning_records_only_an_assigned_event(self):
        response = self.patch({'assignee': self.member.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = self.only_event()
        self.assertEqual(event.action, 'ISSUE_ASSIGNED')
        self.assertEqual(event.entity_id, self.issue.id)
        self.assertEqual(event.user, self.manager)
        self.assertEqual(
            event.metadata, {'from': None, 'to': self.ref(self.member)},
        )
        self.assertEqual(
            event.description, 'manager assigned ACT-1 to member',
        )

    def test_reassigning_records_the_previous_assignee(self):
        self.add_member(self.newcomer, 'TEAM_MEMBER')
        self.issue.assignee = self.member
        self.issue.save()

        self.patch({'assignee': self.newcomer.id})

        event = self.only_event()
        self.assertEqual(event.action, 'ISSUE_ASSIGNED')
        self.assertEqual(
            event.metadata,
            {'from': self.ref(self.member), 'to': self.ref(self.newcomer)},
        )
        self.assertEqual(
            event.description,
            'manager reassigned ACT-1 from member to newcomer',
        )

    def test_clearing_the_assignee_records_an_unassigned_event(self):
        self.issue.assignee = self.member
        self.issue.save()

        response = self.patch({'assignee': None})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = self.only_event()
        self.assertEqual(event.action, 'ISSUE_UNASSIGNED')
        self.assertEqual(
            event.metadata, {'from': self.ref(self.member), 'to': None},
        )
        self.assertEqual(
            event.description, 'manager unassigned ACT-1 (was member)',
        )

    def test_unchanged_assignee_records_nothing(self):
        self.issue.assignee = self.member
        self.issue.save()

        self.patch({'assignee': self.member.id})
        unassigned = self.make_issue(2)
        self.patch({'assignee': None}, issue=unassigned)

        self.assertFalse(Activity.objects.exists())

    def test_assignment_and_field_changes_make_two_separate_events(self):
        response = self.patch({'priority': 'URGENT', 'assignee': self.member.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Activity.objects.count(), 2)

        updated = self.events(action='ISSUE_UPDATED').get()
        assigned = self.events(action='ISSUE_ASSIGNED').get()

        # Each event carries only its own change.
        self.assertEqual(
            updated.metadata,
            {'changes': {'priority': {'from': 'MEDIUM', 'to': 'URGENT'}}},
        )
        self.assertEqual(
            assigned.metadata, {'from': None, 'to': self.ref(self.member)},
        )

    def test_rejected_updates_record_nothing(self):
        archived = self.make_issue(2, is_archived=True)
        by_member = self.make_issue(3, reporter=self.member)

        cases = [
            # Assignee must belong to the project...
            (self.manager, self.issue, {'assignee': self.newcomer.id}, 400),
            # ...and cannot be a viewer.
            (self.manager, self.issue, {'assignee': self.viewer.id}, 400),
            # Archived issues are read-only.
            (self.manager, archived, {'priority': 'LOW'}, 400),
            # Only the reporter or assignee may edit.
            (self.member, self.issue, {'priority': 'LOW'}, 403),
            # Only managers may change the assignee.
            (self.member, by_member, {'assignee': self.viewer.id}, 403),
            (self.viewer, self.issue, {'priority': 'LOW'}, 403),
        ]

        for user, issue, data, expected in cases:
            self.client.force_authenticate(user=user)

            response = self.patch(data, issue=issue)

            self.assertEqual(response.status_code, expected, (user, data))

        self.assertFalse(Activity.objects.exists())

    def test_reporter_can_edit_and_is_the_recorded_actor(self):
        own = self.make_issue(2, reporter=self.member)
        self.client.force_authenticate(user=self.member)

        self.patch({'priority': 'LOW', 'user': self.manager.id}, issue=own)

        self.assertEqual(self.only_event().user, self.member)

    def test_logging_failure_rolls_back_the_update(self):
        self.client.raise_request_exception = False

        with mock.patch(ISSUE_WRITER, side_effect=ActivityError('boom')):
            response = self.patch({'priority': 'HIGH'})

        self.assertEqual(response.status_code, 500)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.priority, 'MEDIUM')
        self.assertFalse(Activity.objects.exists())

    def test_failure_on_the_second_event_rolls_back_the_first(self):
        self.client.raise_request_exception = False

        with self.fail_on(Activity.Action.ISSUE_ASSIGNED):
            response = self.patch(
                {'priority': 'URGENT', 'assignee': self.member.id},
            )

        self.assertEqual(response.status_code, 500)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.priority, 'MEDIUM')
        self.assertIsNone(self.issue.assignee)
        self.assertFalse(Activity.objects.exists())


class IssueStatusChangedEventTests(IssueEventTestCase):

    def setUp(self):
        super().setUp()
        self.issue = self.make_issue(1, assignee=self.member)

    def transition(self, new_status, issue=None):
        return self.client.post(
            self.issue_url(issue or self.issue, 'transition/'),
            {'status': new_status},
            format='json',
        )

    def test_transition_records_a_single_status_event(self):
        response = self.transition('IN_PROGRESS')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = self.only_event()
        self.assertEqual(event.action, 'ISSUE_STATUS_CHANGED')
        self.assertEqual(event.project, self.project)
        self.assertEqual(event.user, self.manager)
        self.assertEqual(event.entity_type, 'ISSUE')
        self.assertEqual(event.entity_id, self.issue.id)
        self.assertEqual(
            event.metadata, {'from': 'TODO', 'to': 'IN_PROGRESS'},
        )
        self.assertEqual(
            event.description,
            'manager moved ACT-1 from To Do to In Progress',
        )

    def test_assignee_can_transition_and_is_the_actor(self):
        self.client.force_authenticate(user=self.member)

        self.transition('IN_PROGRESS')

        self.assertEqual(self.only_event().user, self.member)

    def test_full_workflow_is_recorded_in_order(self):
        for new_status in ('IN_PROGRESS', 'IN_REVIEW', 'DONE'):
            self.assertEqual(self.transition(new_status).status_code, 200)

        events = list(self.issue_events(self.issue))

        # Newest first.
        self.assertEqual(
            [(e.metadata['from'], e.metadata['to']) for e in events],
            [
                ('IN_REVIEW', 'DONE'),
                ('IN_PROGRESS', 'IN_REVIEW'),
                ('TODO', 'IN_PROGRESS'),
            ],
        )

    def test_rejected_transitions_record_nothing(self):
        archived = self.make_issue(2, is_archived=True)
        in_progress = self.make_issue(
            3, assignee=self.member, status='IN_PROGRESS',
        )
        # A team member who is not the assignee.
        self.add_member(self.newcomer, 'TEAM_MEMBER')

        cases = [
            (self.manager, self.issue, 'DONE', 400),        # skips a step
            (self.manager, self.issue, 'TODO', 400),        # same status
            (self.manager, in_progress, 'TODO', 400),       # backwards
            (self.manager, archived, 'IN_PROGRESS', 400),   # archived
            (self.viewer, self.issue, 'IN_PROGRESS', 403),  # viewer
            (self.newcomer, self.issue, 'IN_PROGRESS', 403),  # not the assignee
        ]

        for user, issue, new_status, expected in cases:
            self.client.force_authenticate(user=user)

            response = self.transition(new_status, issue=issue)

            self.assertEqual(response.status_code, expected, (user, new_status))

        self.assertFalse(Activity.objects.exists())

    def test_logging_failure_rolls_back_the_transition(self):
        self.client.raise_request_exception = False

        with mock.patch(ISSUE_WRITER, side_effect=ActivityError('boom')):
            response = self.transition('IN_PROGRESS')

        self.assertEqual(response.status_code, 500)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, 'TODO')
        self.assertFalse(Activity.objects.exists())


class IssueArchivedEventTests(IssueEventTestCase):

    def setUp(self):
        super().setUp()
        self.issue = self.make_issue(1)

    def archive(self, issue=None):
        return self.client.post(
            self.issue_url(issue or self.issue, 'archive/'),
        )

    def test_archive_records_an_event(self):
        response = self.archive()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = self.only_event()
        self.assertEqual(event.action, 'ISSUE_ARCHIVED')
        self.assertEqual(event.project, self.project)
        self.assertEqual(event.user, self.manager)
        self.assertEqual(event.entity_type, 'ISSUE')
        self.assertEqual(event.entity_id, self.issue.id)
        self.assertEqual(event.description, 'manager archived ACT-1')
        self.assertEqual(event.metadata, {'issue_key': 'ACT-1'})

    def test_archiving_twice_records_one_event(self):
        self.archive()
        response = self.archive()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Activity.objects.count(), 1)

    def test_non_managers_cannot_archive(self):
        for user in (self.member, self.viewer):
            self.client.force_authenticate(user=user)

            self.assertEqual(self.archive().status_code, 403)

        self.issue.refresh_from_db()
        self.assertFalse(self.issue.is_archived)
        self.assertFalse(Activity.objects.exists())

    def test_logging_failure_rolls_back_the_archive(self):
        self.client.raise_request_exception = False

        with mock.patch(ISSUE_WRITER, side_effect=ActivityError('boom')):
            response = self.archive()

        self.assertEqual(response.status_code, 500)
        self.issue.refresh_from_db()
        self.assertFalse(self.issue.is_archived)
        self.assertFalse(Activity.objects.exists())


class IssueLifecycleTests(IssueEventTestCase):

    def test_the_whole_life_of_an_issue_reads_back_newest_first(self):
        created = self.client.post(
            self.issues_url(), {'title': 'Ship it'}, format='json',
        )
        issue = Issue.objects.get(pk=created.data['id'])

        self.client.patch(
            self.issue_url(issue),
            {'assignee': self.member.id, 'priority': 'HIGH'},
            format='json',
        )
        self.client.post(
            self.issue_url(issue, 'transition/'),
            {'status': 'IN_PROGRESS'},
            format='json',
        )
        self.client.post(self.issue_url(issue, 'archive/'))

        actions = [e.action for e in self.issue_events(issue)]

        self.assertEqual(
            actions,
            [
                'ISSUE_ARCHIVED',
                'ISSUE_STATUS_CHANGED',
                'ISSUE_ASSIGNED',
                'ISSUE_UPDATED',
                'ISSUE_CREATED',
            ],
        )
        self.assertEqual(
            Activity.objects.exclude(project=self.project).count(), 0,
        )
