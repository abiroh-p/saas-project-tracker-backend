from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework import status

from apps.projects.models import Project, ProjectMember

from .exceptions import ActivityError
from .models import Activity
from .testing import ActivityAPITestCase

User = get_user_model()

PROJECT_WRITER = 'apps.projects.services.project.record_activity'
MEMBERSHIP_WRITER = 'apps.projects.services.membership.record_activity'


class ProjectCreatedEventTests(ActivityAPITestCase):

    def test_create_project_records_one_event(self):
        response = self.client.post(
            '/api/v1/projects/',
            {'key': 'NEW', 'name': 'Brand new'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        project = Project.objects.get(key='NEW')

        # Only PROJECT_CREATED: the creator's manager membership is part of it.
        event = self.only_event()
        self.assertEqual(event.action, 'PROJECT_CREATED')
        self.assertEqual(event.project, project)
        self.assertEqual(event.user, self.manager)
        self.assertEqual(event.entity_type, 'PROJECT')
        self.assertEqual(event.entity_id, project.id)
        self.assertEqual(event.description, 'manager created project NEW')
        self.assertEqual(event.metadata, {'key': 'NEW', 'name': 'Brand new'})

    def test_invalid_create_records_nothing(self):
        response = self.client.post(
            '/api/v1/projects/',
            {
                'key': 'BAD',
                'name': 'Bad dates',
                'start_date': '2026-05-01',
                'end_date': '2026-01-01',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Activity.objects.exists())

    def test_logging_failure_rolls_back_project_creation(self):
        self.client.raise_request_exception = False

        with mock.patch(PROJECT_WRITER, side_effect=ActivityError('boom')):
            response = self.client.post(
                '/api/v1/projects/',
                {'key': 'NEW', 'name': 'Brand new'},
                format='json',
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(Project.objects.filter(key='NEW').exists())
        self.assertFalse(
            ProjectMember.objects.filter(project__key='NEW').exists()
        )
        self.assertFalse(Activity.objects.exists())


class ProjectUpdatedEventTests(ActivityAPITestCase):

    def patch(self, data):
        return self.client.patch(self.project_url(), data, format='json')

    def test_records_only_the_fields_that_changed(self):
        response = self.patch({
            'name': 'Renamed',
            'start_date': '2026-01-01',
            'end_date': '2026-12-31',
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = self.only_event()
        self.assertEqual(event.action, 'PROJECT_UPDATED')
        self.assertEqual(event.project, self.project)
        self.assertEqual(event.user, self.manager)
        self.assertEqual(event.entity_type, 'PROJECT')
        self.assertEqual(event.entity_id, self.project.id)
        self.assertEqual(
            event.metadata,
            {
                'changes': {
                    'name': {'from': 'Activity project', 'to': 'Renamed'},
                    'start_date': {'from': None, 'to': '2026-01-01'},
                    'end_date': {'from': None, 'to': '2026-12-31'},
                },
            },
        )
        self.assertIn('manager updated project ACT', event.description)
        self.assertIn('name', event.description)

    def test_unchanged_fields_in_the_same_request_are_left_out(self):
        self.patch({'name': 'Activity project', 'description': 'Changed'})

        event = self.only_event()
        self.assertEqual(list(event.metadata['changes']), ['description'])

    def test_description_text_is_not_stored(self):
        self.patch({'description': 'A very long private description'})

        event = self.only_event()
        self.assertEqual(
            event.metadata,
            {'changes': {'description': {'changed': True}}},
        )
        self.assertNotIn('private', str(event.metadata))
        self.assertNotIn('private', event.description)

    def test_date_changes_store_iso_strings_for_both_sides(self):
        self.project.start_date = date(2026, 1, 1)
        self.project.save()

        self.patch({'start_date': '2026-02-01'})

        self.assertEqual(
            self.only_event().metadata['changes']['start_date'],
            {'from': '2026-01-01', 'to': '2026-02-01'},
        )

    def test_noop_patches_record_nothing(self):
        for data in (
            {},
            {'name': 'Activity project'},
            {'name': 'Activity project', 'description': 'Original description'},
        ):
            response = self.patch(data)

            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertFalse(Activity.objects.exists())

    def test_invalid_update_records_nothing(self):
        response = self.patch({'start_date': '2026-05-01', 'end_date': '2026-01-01'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Activity.objects.exists())

    def test_changing_the_key_is_rejected_and_not_recorded(self):
        response = self.patch({'key': 'OTHER'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.project.refresh_from_db()
        self.assertEqual(self.project.key, 'ACT')
        self.assertFalse(Activity.objects.exists())

    def test_non_managers_cannot_update_and_leave_no_trace(self):
        for user in (self.member, self.viewer):
            self.client.force_authenticate(user=user)

            response = self.patch({'name': 'Hijacked'})

            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.project.refresh_from_db()
        self.assertEqual(self.project.name, 'Activity project')
        self.assertFalse(Activity.objects.exists())

    def test_actor_is_the_authenticated_user_not_the_payload(self):
        self.client.force_authenticate(user=self.manager)

        self.patch({'name': 'Renamed', 'user': self.member.id, 'user_id': self.member.id})

        self.assertEqual(self.only_event().user, self.manager)

    def test_logging_failure_rolls_back_the_update(self):
        self.client.raise_request_exception = False

        with mock.patch(PROJECT_WRITER, side_effect=ActivityError('boom')):
            response = self.patch({'name': 'Renamed'})

        self.assertEqual(response.status_code, 500)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, 'Activity project')
        self.assertFalse(Activity.objects.exists())


class ProjectArchivedEventTests(ActivityAPITestCase):

    def test_archive_records_an_event(self):
        response = self.client.post(self.project_url('archive/'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = self.only_event()
        self.assertEqual(event.action, 'PROJECT_ARCHIVED')
        self.assertEqual(event.project, self.project)
        self.assertEqual(event.user, self.manager)
        self.assertEqual(event.entity_type, 'PROJECT')
        self.assertEqual(event.entity_id, self.project.id)
        self.assertEqual(event.description, 'manager archived project ACT')
        self.assertEqual(event.metadata, {'key': 'ACT'})

    def test_archiving_twice_records_one_event(self):
        self.client.post(self.project_url('archive/'))
        response = self.client.post(self.project_url('archive/'))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Activity.objects.count(), 1)

    def test_non_managers_cannot_archive(self):
        self.client.force_authenticate(user=self.member)

        response = self.client.post(self.project_url('archive/'))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_archived)
        self.assertFalse(Activity.objects.exists())

    def test_logging_failure_rolls_back_the_archive(self):
        self.client.raise_request_exception = False

        with mock.patch(PROJECT_WRITER, side_effect=ActivityError('boom')):
            response = self.client.post(self.project_url('archive/'))

        self.assertEqual(response.status_code, 500)
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_archived)
        self.assertFalse(Activity.objects.exists())


class MemberAddedEventTests(ActivityAPITestCase):

    def add(self, user, role='VIEWER'):
        return self.client.post(
            self.project_url('members/'),
            {'user_id': user.id, 'role': role},
            format='json',
        )

    def test_add_member_records_an_event_for_the_membership(self):
        response = self.add(self.newcomer, 'VIEWER')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        membership = ProjectMember.objects.get(user=self.newcomer)

        event = self.only_event()
        self.assertEqual(event.action, 'MEMBER_ADDED')
        self.assertEqual(event.project, self.project)
        self.assertEqual(event.user, self.manager)
        self.assertEqual(event.entity_type, 'MEMBERSHIP')
        self.assertEqual(event.entity_id, membership.id)
        self.assertEqual(
            event.description,
            'manager added newcomer to project ACT as Viewer',
        )
        self.assertEqual(
            event.metadata,
            {
                'member': {'id': self.newcomer.id, 'username': 'newcomer'},
                'role': 'VIEWER',
            },
        )

    def test_duplicate_member_records_nothing(self):
        response = self.add(self.member)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Activity.objects.exists())

    def test_non_managers_cannot_add_members(self):
        self.client.force_authenticate(user=self.member)

        response = self.add(self.newcomer)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            ProjectMember.objects.filter(user=self.newcomer).exists()
        )
        self.assertFalse(Activity.objects.exists())

    def test_logging_failure_rolls_back_the_new_membership(self):
        self.client.raise_request_exception = False

        with mock.patch(MEMBERSHIP_WRITER, side_effect=ActivityError('boom')):
            response = self.add(self.newcomer)

        self.assertEqual(response.status_code, 500)
        self.assertFalse(
            ProjectMember.objects.filter(user=self.newcomer).exists()
        )
        self.assertFalse(Activity.objects.exists())


class RoleChangedEventTests(ActivityAPITestCase):

    def change(self, membership, role):
        return self.client.patch(
            self.project_url(f'members/{membership.id}/'),
            {'role': role},
            format='json',
        )

    def test_role_change_records_old_and_new_role(self):
        response = self.change(self.member_membership, 'VIEWER')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = self.only_event()
        self.assertEqual(event.action, 'ROLE_CHANGED')
        self.assertEqual(event.project, self.project)
        self.assertEqual(event.user, self.manager)
        self.assertEqual(event.entity_type, 'MEMBERSHIP')
        self.assertEqual(event.entity_id, self.member_membership.id)
        self.assertEqual(
            event.description,
            "manager changed member's role in project ACT "
            'from Team Member to Viewer',
        )
        self.assertEqual(
            event.metadata,
            {
                'member': {'id': self.member.id, 'username': 'member'},
                'from': 'TEAM_MEMBER',
                'to': 'VIEWER',
            },
        )

    def test_same_role_records_nothing(self):
        response = self.change(self.member_membership, 'TEAM_MEMBER')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Activity.objects.exists())

    def test_demoting_the_last_manager_is_rejected_and_not_recorded(self):
        response = self.change(self.manager_membership, 'VIEWER')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.manager_membership.refresh_from_db()
        self.assertEqual(self.manager_membership.role, 'PROJECT_MANAGER')
        self.assertFalse(Activity.objects.exists())

    def test_demoting_a_member_with_open_issues_is_rejected_and_not_recorded(self):
        self.make_issue(1, assignee=self.member)

        response = self.change(self.member_membership, 'VIEWER')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, 'TEAM_MEMBER')
        self.assertFalse(Activity.objects.exists())

    def test_non_managers_cannot_change_roles(self):
        self.client.force_authenticate(user=self.member)

        response = self.change(self.viewer_membership, 'PROJECT_MANAGER')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Activity.objects.exists())

    def test_logging_failure_rolls_back_the_role_change(self):
        self.client.raise_request_exception = False

        with mock.patch(MEMBERSHIP_WRITER, side_effect=ActivityError('boom')):
            response = self.change(self.member_membership, 'VIEWER')

        self.assertEqual(response.status_code, 500)
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, 'TEAM_MEMBER')
        self.assertFalse(Activity.objects.exists())


class MemberRemovedEventTests(ActivityAPITestCase):

    def remove(self, membership):
        return self.client.delete(
            self.project_url(f'members/{membership.id}/'),
        )

    def test_removal_records_a_snapshot_of_the_deleted_membership(self):
        membership_id = self.member_membership.id

        response = self.remove(self.member_membership)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            ProjectMember.objects.filter(pk=membership_id).exists()
        )

        event = self.only_event()
        self.assertEqual(event.action, 'MEMBER_REMOVED')
        self.assertEqual(event.project, self.project)
        self.assertEqual(event.user, self.manager)
        self.assertEqual(event.entity_type, 'MEMBERSHIP')
        self.assertEqual(event.entity_id, membership_id)
        self.assertEqual(
            event.description, 'manager removed member from project ACT',
        )
        self.assertEqual(
            event.metadata,
            {
                'member': {'id': self.member.id, 'username': 'member'},
                'role': 'TEAM_MEMBER',
                'self_removed': False,
            },
        )

    def test_leaving_a_project_is_flagged_as_self_removal(self):
        self.client.force_authenticate(user=self.viewer)

        response = self.remove(self.viewer_membership)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        event = self.only_event()
        self.assertEqual(event.action, 'MEMBER_REMOVED')
        self.assertEqual(event.user, self.viewer)
        self.assertEqual(event.description, 'viewer left project ACT')
        self.assertTrue(event.metadata['self_removed'])

    def test_removing_the_last_manager_is_rejected_and_not_recorded(self):
        response = self.remove(self.manager_membership)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(
            ProjectMember.objects.filter(pk=self.manager_membership.pk).exists()
        )
        self.assertFalse(Activity.objects.exists())

    def test_non_managers_cannot_remove_others(self):
        self.client.force_authenticate(user=self.member)

        response = self.remove(self.viewer_membership)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Activity.objects.exists())

    def test_removal_records_each_issue_it_unassigns(self):
        first = self.make_issue(1, assignee=self.member)
        archived = self.make_issue(2, assignee=self.member, is_archived=True)
        kept = self.make_issue(3, assignee=self.manager)

        other_project = Project.objects.create(
            key='OTH', name='Other', created_by=self.manager,
        )
        self.add_member(
            self.manager, ProjectMember.Role.PROJECT_MANAGER, other_project,
        )
        self.add_member(
            self.member, ProjectMember.Role.TEAM_MEMBER, other_project,
        )
        elsewhere = self.make_issue(1, assignee=self.member, project=other_project)

        self.remove(self.member_membership)

        for issue in (first, archived):
            issue.refresh_from_db()
            self.assertIsNone(issue.assignee)

        kept.refresh_from_db()
        elsewhere.refresh_from_db()
        self.assertEqual(kept.assignee, self.manager)
        self.assertEqual(elsewhere.assignee, self.member)

        unassigned = self.events(action='ISSUE_UNASSIGNED')
        self.assertEqual(
            {event.entity_id for event in unassigned},
            {first.id, archived.id},
        )

        member_ref = {'id': self.member.id, 'username': 'member'}
        for event in unassigned:
            self.assertEqual(event.project, self.project)
            self.assertEqual(event.user, self.manager)
            self.assertEqual(event.entity_type, 'ISSUE')
            self.assertEqual(
                event.metadata,
                {'from': member_ref, 'to': None, 'reason': 'member_removed'},
            )

        self.assertTrue(
            self.events(action='ISSUE_UNASSIGNED', entity_id=first.id)
            .get()
            .description.startswith('manager unassigned ACT-1')
        )

        # The removal itself is recorded last, so it heads the newest-first feed.
        newest = Activity.objects.first()
        self.assertEqual(newest.action, 'MEMBER_REMOVED')
        self.assertEqual(Activity.objects.count(), 3)

    def test_removing_a_member_without_issues_adds_no_unassign_events(self):
        self.make_issue(1, assignee=self.manager)

        self.remove(self.member_membership)

        self.assertFalse(self.events(action='ISSUE_UNASSIGNED').exists())

    def test_logging_failure_rolls_back_removal_and_unassignment(self):
        issue = self.make_issue(1, assignee=self.member)
        self.client.raise_request_exception = False

        with mock.patch(MEMBERSHIP_WRITER, side_effect=ActivityError('boom')):
            response = self.remove(self.member_membership)

        self.assertEqual(response.status_code, 500)
        self.assertTrue(
            ProjectMember.objects.filter(pk=self.member_membership.pk).exists()
        )
        issue.refresh_from_db()
        self.assertEqual(issue.assignee, self.member)
        self.assertFalse(Activity.objects.exists())

    def test_failure_on_the_final_event_still_restores_the_assignments(self):
        issue = self.make_issue(1, assignee=self.member)
        self.client.raise_request_exception = False

        real_writer = __import__(
            'apps.activity.services.activity', fromlist=['record_activity'],
        ).record_activity

        def fail_on_removal(**kwargs):
            if kwargs['action'] == Activity.Action.MEMBER_REMOVED:
                raise ActivityError('boom')
            return real_writer(**kwargs)

        with mock.patch(MEMBERSHIP_WRITER, side_effect=fail_on_removal):
            response = self.remove(self.member_membership)

        self.assertEqual(response.status_code, 500)
        issue.refresh_from_db()
        self.assertEqual(issue.assignee, self.member)
        self.assertTrue(
            ProjectMember.objects.filter(pk=self.member_membership.pk).exists()
        )
        # The earlier ISSUE_UNASSIGNED insert was rolled back with the rest.
        self.assertFalse(Activity.objects.exists())
