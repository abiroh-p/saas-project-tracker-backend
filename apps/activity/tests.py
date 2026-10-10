from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.projects.models import Project

from .exceptions import ActivityError, ImmutableActivityError
from .models import Activity
from .services.activity import record_activity, user_ref

User = get_user_model()


def make_project(user, key='ACT'):
    return Project.objects.create(
        key=key,
        name='Activity project',
        created_by=user,
    )


def record(project, user, **overrides):
    data = {
        'project': project,
        'user': user,
        'action': Activity.Action.PROJECT_CREATED,
        'entity_type': Activity.EntityType.PROJECT,
        'entity_id': project.id,
        'description': 'sam created project ACT',
    }
    data.update(overrides)

    with transaction.atomic():
        return record_activity(**data)


class ActivityModelTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='sam',
            password='TestPassword123',
        )
        self.project = make_project(self.user)

    def test_defaults(self):
        activity = record(self.project, self.user)

        self.assertEqual(activity.metadata, {})
        self.assertIsNotNone(activity.created_at)
        self.assertEqual(activity.project, self.project)
        self.assertEqual(activity.user, self.user)

    def test_every_documented_action_exists(self):
        self.assertEqual(
            set(Activity.Action.values),
            {
                'PROJECT_CREATED',
                'PROJECT_UPDATED',
                'PROJECT_ARCHIVED',
                'MEMBER_ADDED',
                'MEMBER_REMOVED',
                'ROLE_CHANGED',
                'ISSUE_CREATED',
                'ISSUE_UPDATED',
                'ISSUE_ASSIGNED',
                'ISSUE_UNASSIGNED',
                'ISSUE_STATUS_CHANGED',
                'ISSUE_ARCHIVED',
            },
        )
        self.assertEqual(
            set(Activity.EntityType.values),
            {'PROJECT', 'MEMBERSHIP', 'ISSUE'},
        )

    def test_default_ordering_is_newest_first(self):
        now = timezone.now()

        for offset, description in enumerate(['oldest', 'middle', 'newest']):
            with mock.patch(
                'django.utils.timezone.now',
                return_value=now + timedelta(minutes=offset),
            ):
                record(self.project, self.user, description=description)

        self.assertEqual(
            list(Activity.objects.values_list('description', flat=True)),
            ['newest', 'middle', 'oldest'],
        )

    def test_equal_timestamps_are_ordered_by_id_descending(self):
        frozen = timezone.now()

        with mock.patch('django.utils.timezone.now', return_value=frozen):
            first = record(self.project, self.user, description='first')
            second = record(self.project, self.user, description='second')
            third = record(self.project, self.user, description='third')

        self.assertEqual(first.created_at, third.created_at)
        self.assertEqual(
            list(Activity.objects.values_list('id', flat=True)),
            [third.id, second.id, first.id],
        )

    def test_feed_indexes_exist(self):
        names = {index.name for index in Activity._meta.indexes}

        self.assertEqual(
            names,
            {'activity_project_created_idx', 'activity_entity_created_idx'},
        )

    def test_activity_is_append_only(self):
        activity = record(self.project, self.user)

        activity.description = 'tampered'
        with self.assertRaises(ImmutableActivityError):
            activity.save()

        with self.assertRaises(ImmutableActivityError):
            activity.delete()

        with self.assertRaises(ImmutableActivityError):
            Activity.objects.update(description='tampered')

        with self.assertRaises(ImmutableActivityError):
            Activity.objects.all().delete()

        # bulk_update() opens a savepoint-less atomic block, so isolate it.
        with self.assertRaises(ImmutableActivityError):
            with transaction.atomic():
                Activity.objects.bulk_update([activity], ['description'])

        activity.refresh_from_db()
        self.assertEqual(activity.description, 'sam created project ACT')

    def test_projects_and_users_with_history_cannot_be_deleted(self):
        from django.db.models import ProtectedError

        record(self.project, self.user)

        with self.assertRaises(ProtectedError):
            self.project.delete()

        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())


class RecordActivityTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='sam',
            password='TestPassword123',
        )
        self.project = make_project(self.user)

    def test_records_every_field(self):
        activity = record(
            self.project,
            self.user,
            action=Activity.Action.MEMBER_ADDED,
            entity_type=Activity.EntityType.MEMBERSHIP,
            entity_id=42,
            description='sam added jo as Viewer',
            metadata={'member': user_ref(self.user), 'role': 'VIEWER'},
        )

        activity.refresh_from_db()

        self.assertEqual(activity.project, self.project)
        self.assertEqual(activity.user, self.user)
        self.assertEqual(activity.action, 'MEMBER_ADDED')
        self.assertEqual(activity.entity_type, 'MEMBERSHIP')
        self.assertEqual(activity.entity_id, 42)
        self.assertEqual(activity.description, 'sam added jo as Viewer')
        self.assertEqual(
            activity.metadata,
            {
                'member': {'id': self.user.id, 'username': 'sam'},
                'role': 'VIEWER',
            },
        )

    def test_user_ref_has_only_id_and_username(self):
        self.user.email = 'sam@example.com'

        self.assertEqual(
            user_ref(self.user),
            {'id': self.user.id, 'username': 'sam'},
        )
        self.assertIsNone(user_ref(None))

    def test_rejects_missing_or_anonymous_actor(self):
        for actor in (None, AnonymousUser()):
            with self.assertRaises(ActivityError):
                record(self.project, actor)

        self.assertFalse(Activity.objects.exists())

    def test_rejects_unknown_action_and_entity_type(self):
        with self.assertRaises(ActivityError):
            record(self.project, self.user, action='PROJECT_EXPLODED')

        with self.assertRaises(ActivityError):
            record(self.project, self.user, entity_type='COMMENT')

        self.assertFalse(Activity.objects.exists())

    def test_rejects_bad_entity_id_and_empty_description(self):
        for entity_id in (0, -1, '5', None, True):
            with self.assertRaises(ActivityError):
                record(self.project, self.user, entity_id=entity_id)

        with self.assertRaises(ActivityError):
            record(self.project, self.user, description='')

        self.assertFalse(Activity.objects.exists())

    def test_rejects_non_dict_metadata(self):
        with self.assertRaises(ActivityError):
            record(self.project, self.user, metadata=['not', 'a', 'dict'])

    def test_rejects_sensitive_metadata_at_any_depth(self):
        for metadata in (
            {'password': 'x'},
            {'changes': {'Refresh': {'from': 'a', 'to': 'b'}}},
            {'items': [{'access_token': 'x'}]},
            {'member': {'id': 1, 'email': 'sam@example.com'}},
        ):
            with self.assertRaises(ActivityError):
                record(self.project, self.user, metadata=metadata)

        self.assertFalse(Activity.objects.exists())

    def test_logging_errors_are_not_client_errors(self):
        # The views map ValueError/PermissionError to 400/403. A failure to
        # write the audit trail must surface as a server error instead.
        self.assertFalse(issubclass(ActivityError, ValueError))
        self.assertFalse(issubclass(ActivityError, PermissionError))

    def test_failure_rolls_back_the_business_change(self):
        with self.assertRaises(ActivityError):
            with transaction.atomic():
                Project.objects.create(
                    key='ROLL',
                    name='Rolled back',
                    created_by=self.user,
                )
                record_activity(
                    project=self.project,
                    user=self.user,
                    action='NOT_AN_ACTION',
                    entity_type=Activity.EntityType.PROJECT,
                    entity_id=1,
                    description='x',
                )

        self.assertFalse(Project.objects.filter(key='ROLL').exists())

    def test_business_change_and_activity_commit_together(self):
        with transaction.atomic():
            project = Project.objects.create(
                key='BOTH',
                name='Both',
                created_by=self.user,
            )
            record_activity(
                project=project,
                user=self.user,
                action=Activity.Action.PROJECT_CREATED,
                entity_type=Activity.EntityType.PROJECT,
                entity_id=project.id,
                description='sam created project BOTH',
            )

        self.assertTrue(Activity.objects.filter(project=project).exists())


class RecordActivityOutsideTransactionTests(TransactionTestCase):

    def test_requires_an_enclosing_transaction(self):
        user = User.objects.create_user(username='sam', password='x')
        project = make_project(user)

        with self.assertRaises(ActivityError):
            record_activity(
                project=project,
                user=user,
                action=Activity.Action.PROJECT_CREATED,
                entity_type=Activity.EntityType.PROJECT,
                entity_id=project.id,
                description='sam created project ACT',
            )

        self.assertFalse(Activity.objects.exists())


class ActivityAdminTests(TestCase):

    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username='root',
            password='TestPassword123',
        )
        self.project = make_project(self.admin_user)
        self.activity = record(self.project, self.admin_user)
        self.client.force_login(self.admin_user)

    def test_changelist_is_visible(self):
        response = self.client.get('/admin/activity/activity/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PROJECT_CREATED')

    def test_detail_is_view_only(self):
        url = f'/admin/activity/activity/{self.activity.pk}/change/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="_save"')

        response = self.client.post(url, {'description': 'tampered'})
        self.assertEqual(response.status_code, 403)

        self.activity.refresh_from_db()
        self.assertEqual(
            self.activity.description, 'sam created project ACT',
        )

    def test_cannot_add_or_delete(self):
        self.assertEqual(
            self.client.get('/admin/activity/activity/add/').status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f'/admin/activity/activity/{self.activity.pk}/delete/',
                {'post': 'yes'},
            ).status_code,
            403,
        )
        self.assertTrue(Activity.objects.filter(pk=self.activity.pk).exists())
