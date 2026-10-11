from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status

from apps.projects.models import Project, ProjectMember

from .models import MAX_COMMENT_LENGTH, Comment
from .testing import CommentAPITestCase

COMMENT_FIELDS = {
    'id',
    'issue',
    'author',
    'body',
    'created_at',
    'updated_at',
    'edited_at',
    'is_deleted',
    'deleted_at',
}


class CommentEndpointTestCase(CommentAPITestCase):

    def list_url(self, issue=None):
        return f'/api/v1/issues/{(issue or self.issue).id}/comments/'

    def detail_url(self, comment, issue=None):
        return f'{self.list_url(issue)}{comment.id}/'

    def post(self, body='A comment', issue=None, **extra):
        return self.client.post(
            self.list_url(issue), {'body': body, **extra}, format='json',
        )

    def ids(self, response):
        return [item['id'] for item in response.data['results']]

    def archive_project(self):
        self.project.is_archived = True
        self.project.save()


class AddCommentTests(CommentEndpointTestCase):

    def test_member_can_add_a_comment(self):
        self.client.force_authenticate(user=self.member)

        response = self.post('The login endpoint returns 401.')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        comment = Comment.objects.get()
        self.assertEqual(
            response.data,
            {
                'id': comment.id,
                'issue': self.issue.id,
                'author': {'id': self.member.id, 'username': 'member'},
                'body': 'The login endpoint returns 401.',
                'created_at': response.data['created_at'],
                'updated_at': response.data['updated_at'],
                'edited_at': None,
                'is_deleted': False,
                'deleted_at': None,
            },
        )

    def test_manager_can_add_a_comment(self):
        self.assertEqual(self.post().status_code, status.HTTP_201_CREATED)

    def test_author_and_issue_come_from_the_request_not_the_payload(self):
        other_issue = self.make_issue(2)
        self.client.force_authenticate(user=self.member)

        response = self.client.post(
            self.list_url(),
            {
                'body': 'A comment',
                'author': self.manager.id,
                'author_id': self.manager.id,
                'issue': other_issue.id,
                'id': 9999,
                'created_at': '2001-01-01T00:00:00Z',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        comment = Comment.objects.get()
        self.assertEqual(comment.author, self.member)
        self.assertEqual(comment.issue, self.issue)
        self.assertNotEqual(comment.id, 9999)
        self.assertGreater(comment.created_at.year, 2020)

    def test_comment_is_attached_to_the_issue_in_the_url(self):
        other_issue = self.make_issue(2)

        self.post('On the second issue', issue=other_issue)

        self.assertEqual(Comment.objects.get().issue, other_issue)
        self.assertFalse(self.issue.comments.exists())

    def test_text_is_trimmed_and_multiline_text_is_kept(self):
        response = self.post('  first line\n\nsecond line  ')

        self.assertEqual(response.data['body'], 'first line\n\nsecond line')

    def test_text_is_stored_verbatim_not_as_html(self):
        # The API returns plain text. Escaping is the frontend's job.
        markup = '<script>alert(1)</script> & <b>bold</b>'

        response = self.post(markup)

        self.assertEqual(response.data['body'], markup)
        self.assertEqual(Comment.objects.get().body, markup)

    def test_empty_missing_and_whitespace_only_text_is_rejected(self):
        for payload in ({}, {'body': ''}, {'body': '   \n\t '}, {'body': None}):
            response = self.client.post(
                self.list_url(), payload, format='json',
            )

            self.assertEqual(
                response.status_code, status.HTTP_400_BAD_REQUEST, payload,
            )
            self.assertEqual(response.data['code'], 'validation_error')
            self.assertIn('body', response.data['errors'])

        self.assertFalse(Comment.objects.exists())

    def test_length_limit(self):
        too_long = self.post('x' * (MAX_COMMENT_LENGTH + 1))

        self.assertEqual(too_long.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('body', too_long.data['errors'])
        self.assertFalse(Comment.objects.exists())

        at_limit = self.post('x' * MAX_COMMENT_LENGTH)

        self.assertEqual(at_limit.status_code, status.HTTP_201_CREATED)

    def test_viewers_cannot_comment(self):
        self.client.force_authenticate(user=self.viewer)

        response = self.post()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['code'], 'permission_denied')
        self.assertEqual(
            response.data['detail'], 'Viewers cannot comment on issues.',
        )
        self.assertFalse(Comment.objects.exists())

    def test_non_members_get_the_same_404_as_a_missing_issue(self):
        self.client.force_authenticate(user=self.newcomer)

        hidden = self.post()
        missing = self.client.post(
            '/api/v1/issues/999999/comments/', {'body': 'x'}, format='json',
        )

        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(hidden.data, missing.data)
        self.assertFalse(Comment.objects.exists())

    def test_membership_in_another_project_grants_nothing(self):
        other = Project.objects.create(
            key='OTH', name='Other', created_by=self.newcomer,
        )
        self.add_member(
            self.newcomer, ProjectMember.Role.PROJECT_MANAGER, other,
        )
        self.client.force_authenticate(user=self.newcomer)

        self.assertEqual(self.post().status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_requests_are_rejected(self):
        self.client.force_authenticate(user=None)

        self.assertEqual(
            self.post().status_code, status.HTTP_401_UNAUTHORIZED,
        )

    def test_archived_issues_are_read_only(self):
        self.issue.is_archived = True
        self.issue.save()

        response = self.post()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'bad_request')
        self.assertFalse(Comment.objects.exists())

    def test_archived_projects_are_hidden_like_the_issue_endpoints(self):
        self.archive_project()

        self.assertEqual(self.post().status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Comment.objects.exists())


class ListCommentsTests(CommentEndpointTestCase):

    def get(self, params=None, issue=None):
        return self.client.get(self.list_url(issue), params or {})

    def test_comments_are_listed_oldest_first_with_author_and_timestamps(self):
        first = self.make_comment(self.member, 'first')
        second = self.make_comment(self.manager, 'second')

        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(self.ids(response), [first.id, second.id])

        item = response.data['results'][0]
        self.assertEqual(set(item), COMMENT_FIELDS)
        self.assertEqual(item['author'], {'id': self.member.id, 'username': 'member'})
        self.assertEqual(item['body'], 'first')
        self.assertIsNotNone(item['created_at'])

    def test_every_role_can_read(self):
        self.make_comment()

        for user in (self.manager, self.member, self.viewer):
            self.client.force_authenticate(user=user)

            response = self.get()

            self.assertEqual(response.status_code, 200, user.username)
            self.assertEqual(response.data['count'], 1)

    def test_only_this_issues_comments_are_listed(self):
        other_issue = self.make_issue(2)
        mine = self.make_comment()
        self.make_comment(issue=other_issue)

        self.assertEqual(self.ids(self.get()), [mine.id])

    def test_empty_discussion(self):
        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])

    def test_pagination(self):
        created = [self.make_comment(body=str(i)) for i in range(5)]

        first = self.get({'page_size': 2, 'page': 1})
        last = self.get({'page_size': 2, 'page': 3})

        self.assertEqual(first.data['count'], 5)
        self.assertEqual(self.ids(first), [c.id for c in created[:2]])
        self.assertIsNotNone(first.data['next'])
        self.assertIsNone(first.data['previous'])
        self.assertEqual(self.ids(last), [created[4].id])
        self.assertIsNone(last.data['next'])

    def test_default_page_size_is_twenty_and_the_cap_is_one_hundred(self):
        Comment.objects.bulk_create([
            Comment(issue=self.issue, author=self.manager, body=str(i))
            for i in range(105)
        ])

        self.assertEqual(len(self.get().data['results']), 20)
        self.assertEqual(
            len(self.get({'page_size': 1000}).data['results']), 100,
        )

    def test_page_beyond_the_end_is_not_found(self):
        self.make_comment()

        self.assertEqual(self.get({'page': 5}).status_code, 404)

    def test_deleted_comments_stay_in_the_timeline_without_their_text(self):
        before = self.make_comment(body='before')
        gone = self.make_comment(
            self.member, body='', deleted_at=timezone.now(),
            deleted_by=self.manager,
        )
        after = self.make_comment(body='after')

        response = self.get()

        self.assertEqual(self.ids(response), [before.id, gone.id, after.id])

        tombstone = response.data['results'][1]
        self.assertTrue(tombstone['is_deleted'])
        self.assertIsNone(tombstone['body'])
        self.assertIsNotNone(tombstone['deleted_at'])
        self.assertEqual(tombstone['author']['username'], 'member')

    def test_query_count_does_not_grow_with_the_number_of_comments(self):
        self.make_comment(self.member)

        with CaptureQueriesContext(connection) as one:
            self.get()

        for _ in range(9):
            self.make_comment(self.member)

        with CaptureQueriesContext(connection) as ten:
            self.get()

        self.assertEqual(len(ten), len(one))

    def test_non_members_get_the_same_404_as_a_missing_issue(self):
        self.make_comment()
        self.client.force_authenticate(user=self.newcomer)

        hidden = self.get()
        missing = self.client.get('/api/v1/issues/999999/comments/')

        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(hidden.data, missing.data)

    def test_removed_members_lose_access(self):
        self.make_comment()
        ProjectMember.objects.filter(
            project=self.project, user=self.viewer,
        ).delete()
        self.client.force_authenticate(user=self.viewer)

        self.assertEqual(self.get().status_code, status.HTTP_404_NOT_FOUND)

    def test_members_added_later_can_read_older_comments(self):
        old = self.make_comment()
        self.client.force_authenticate(user=self.newcomer)
        self.assertEqual(self.get().status_code, 404)

        self.add_member(self.newcomer, ProjectMember.Role.VIEWER)

        self.assertEqual(self.ids(self.get()), [old.id])

    def test_unauthenticated_requests_are_rejected(self):
        self.client.force_authenticate(user=None)

        self.assertEqual(self.get().status_code, status.HTTP_401_UNAUTHORIZED)

    def test_archived_issues_stay_readable(self):
        self.make_comment()
        self.issue.is_archived = True
        self.issue.save()

        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_archived_projects_are_hidden_like_the_issue_endpoints(self):
        self.make_comment()
        self.archive_project()

        self.assertEqual(self.get().status_code, status.HTTP_404_NOT_FOUND)


class RetrieveCommentTests(CommentEndpointTestCase):

    def test_member_can_retrieve_a_comment(self):
        comment = self.make_comment(self.member, 'Hello')
        self.client.force_authenticate(user=self.viewer)

        response = self.client.get(self.detail_url(comment))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data), COMMENT_FIELDS)
        self.assertEqual(response.data['id'], comment.id)
        self.assertEqual(response.data['body'], 'Hello')

    def test_a_comment_cannot_be_read_through_another_issue(self):
        other_issue = self.make_issue(2)
        comment = self.make_comment()

        response = self.client.get(self.detail_url(comment, issue=other_issue))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_members_get_the_same_404_as_for_a_missing_issue(self):
        comment = self.make_comment()
        self.client.force_authenticate(user=self.newcomer)

        hidden = self.client.get(self.detail_url(comment))
        missing = self.client.get('/api/v1/issues/999999/comments/1/')

        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(hidden.data, missing.data)

    def test_a_missing_comment_is_a_404(self):
        response = self.client.get(f'{self.list_url()}999999/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_deleted_comment_is_a_tombstone(self):
        comment = self.make_comment(
            body='', deleted_at=timezone.now(), deleted_by=self.manager,
        )

        response = self.client.get(self.detail_url(comment))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_deleted'])
        self.assertIsNone(response.data['body'])

    def test_unauthenticated_requests_are_rejected(self):
        comment = self.make_comment()
        self.client.force_authenticate(user=None)

        self.assertEqual(
            self.client.get(self.detail_url(comment)).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_the_list_endpoint_does_not_accept_put_or_delete(self):
        for method in ('put', 'patch', 'delete'):
            response = getattr(self.client, method)(
                self.list_url(), {'body': 'x'}, format='json',
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_405_METHOD_NOT_ALLOWED,
                method,
            )


class EditCommentTests(CommentEndpointTestCase):

    def setUp(self):
        super().setUp()
        self.comment = self.make_comment(self.member, 'The login API is not working.')
        self.client.force_authenticate(user=self.member)

    def patch(self, body='Edited', comment=None, issue=None, **extra):
        return self.client.patch(
            self.detail_url(comment or self.comment, issue),
            {'body': body, **extra},
            format='json',
        )

    def test_author_can_edit_their_own_comment(self):
        response = self.patch('The login API returns 401 with valid credentials.')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['body'],
            'The login API returns 401 with valid credentials.',
        )

        self.comment.refresh_from_db()
        self.assertEqual(
            self.comment.body,
            'The login API returns 401 with valid credentials.',
        )

    def test_timestamps_author_and_issue_behave(self):
        original = Comment.objects.get(pk=self.comment.pk)
        later = timezone.now() + timedelta(hours=1)

        with mock.patch('django.utils.timezone.now', return_value=later):
            response = self.patch('Edited')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        edited = Comment.objects.get(pk=self.comment.pk)
        self.assertEqual(edited.created_at, original.created_at)
        self.assertEqual(edited.author, self.member)
        self.assertEqual(edited.issue, self.issue)
        self.assertEqual(edited.id, original.id)
        self.assertEqual(edited.edited_at, later)
        self.assertEqual(edited.updated_at, later)
        self.assertGreater(edited.updated_at, original.updated_at)
        self.assertEqual(response.data['edited_at'], response.data['updated_at'])

    def test_a_new_comment_has_not_been_edited(self):
        self.assertIsNone(self.comment.edited_at)

    def test_text_is_trimmed(self):
        response = self.patch('  tidy  ')

        self.assertEqual(response.data['body'], 'tidy')

    def test_empty_missing_and_whitespace_only_text_is_rejected(self):
        for payload in ({}, {'body': ''}, {'body': '  \n '}, {'body': None}):
            response = self.client.patch(
                self.detail_url(self.comment), payload, format='json',
            )

            self.assertEqual(
                response.status_code, status.HTTP_400_BAD_REQUEST, payload,
            )
            self.assertEqual(response.data['code'], 'validation_error')
            self.assertIn('body', response.data['errors'])

        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, 'The login API is not working.')
        self.assertIsNone(self.comment.edited_at)

    def test_length_limit(self):
        response = self.patch('x' * (MAX_COMMENT_LENGTH + 1))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            self.patch('x' * MAX_COMMENT_LENGTH).status_code, status.HTTP_200_OK,
        )

    def test_saving_the_same_text_is_not_an_edit(self):
        before = Comment.objects.get(pk=self.comment.pk)

        response = self.patch('The login API is not working.')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['edited_at'])

        after = Comment.objects.get(pk=self.comment.pk)
        self.assertIsNone(after.edited_at)
        self.assertEqual(after.updated_at, before.updated_at)

    def test_author_issue_and_timestamps_cannot_be_changed_through_the_payload(self):
        other_issue = self.make_issue(2)
        before = Comment.objects.get(pk=self.comment.pk)

        response = self.client.patch(
            self.detail_url(self.comment),
            {
                'body': 'Edited',
                'author': self.manager.id,
                'issue': other_issue.id,
                'id': 9999,
                'created_at': '2001-01-01T00:00:00Z',
                'is_deleted': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        after = Comment.objects.get(pk=self.comment.pk)
        self.assertEqual(after.author, self.member)
        self.assertEqual(after.issue, self.issue)
        self.assertEqual(after.created_at, before.created_at)
        self.assertIsNone(after.deleted_at)
        self.assertFalse(Comment.objects.filter(pk=9999).exists())

    def test_nobody_can_edit_someone_elses_comment_not_even_a_manager(self):
        for user in (self.manager, self.viewer):
            self.client.force_authenticate(user=user)

            response = self.patch('Hijacked')

            self.assertEqual(
                response.status_code, status.HTTP_403_FORBIDDEN, user.username,
            )
            self.assertEqual(response.data['code'], 'permission_denied')

        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, 'The login API is not working.')
        self.assertIsNone(self.comment.edited_at)

    def test_a_team_member_cannot_edit_another_members_comment(self):
        mine = self.make_comment(self.manager, 'Manager says')
        self.client.force_authenticate(user=self.member)

        response = self.patch('Hijacked', comment=mine)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data['detail'], 'You can only edit your own comments.',
        )

    def test_an_author_who_became_a_viewer_can_no_longer_edit(self):
        ProjectMember.objects.filter(
            project=self.project, user=self.member,
        ).update(role=ProjectMember.Role.VIEWER)

        response = self.patch('Still mine?')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data['detail'], 'Viewers cannot edit comments.',
        )

    def test_non_members_get_the_same_404_as_for_a_missing_issue(self):
        self.client.force_authenticate(user=self.newcomer)

        hidden = self.patch('x')
        missing = self.client.patch(
            '/api/v1/issues/999999/comments/1/', {'body': 'x'}, format='json',
        )

        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(hidden.data, missing.data)

    def test_a_comment_cannot_be_edited_through_another_issue(self):
        other_issue = self.make_issue(2)

        response = self.patch('x', issue=other_issue)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_deleted_comments_cannot_be_edited(self):
        gone = self.make_comment(
            self.member, body='', deleted_at=timezone.now(),
            deleted_by=self.member,
        )

        response = self.patch('Revived', comment=gone)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        gone.refresh_from_db()
        self.assertEqual(gone.body, '')

    def test_archived_issues_are_read_only(self):
        self.issue.is_archived = True
        self.issue.save()

        response = self.patch('Too late')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, 'The login API is not working.')

    def test_archived_projects_are_hidden_like_the_issue_endpoints(self):
        self.archive_project()

        self.assertEqual(self.patch('x').status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_requests_are_rejected(self):
        self.client.force_authenticate(user=None)

        self.assertEqual(
            self.patch('x').status_code, status.HTTP_401_UNAUTHORIZED,
        )

    def test_edits_show_up_in_the_list(self):
        self.patch('Edited')

        item = self.client.get(self.list_url()).data['results'][0]

        self.assertEqual(item['body'], 'Edited')
        self.assertIsNotNone(item['edited_at'])


class DeleteCommentTests(CommentEndpointTestCase):

    def setUp(self):
        super().setUp()
        self.comment = self.make_comment(self.member, 'Something private')
        self.client.force_authenticate(user=self.member)

    def delete(self, comment=None, issue=None):
        return self.client.delete(self.detail_url(comment or self.comment, issue))

    def test_author_can_delete_their_own_comment(self):
        response = self.delete()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data), COMMENT_FIELDS)
        self.assertTrue(response.data['is_deleted'])
        self.assertIsNone(response.data['body'])
        self.assertIsNotNone(response.data['deleted_at'])
        self.assertEqual(response.data['id'], self.comment.id)
        self.assertEqual(response.data['author']['username'], 'member')

    def test_the_text_is_erased_and_the_deleter_is_recorded(self):
        self.delete()

        comment = Comment.objects.get(pk=self.comment.pk)
        self.assertEqual(comment.body, '')
        self.assertIsNotNone(comment.deleted_at)
        self.assertEqual(comment.deleted_by, self.member)
        self.assertEqual(comment.author, self.member)

    def test_the_comment_keeps_its_place_in_the_discussion(self):
        before = self.make_comment(self.manager, 'before')
        # Created after `self.comment` (the member's), so it sorts after it.
        after = self.make_comment(self.manager, 'after')

        self.delete()

        response = self.client.get(self.list_url())

        self.assertEqual(response.data['count'], 3)
        self.assertEqual(
            self.ids(response), [self.comment.id, before.id, after.id],
        )
        self.assertTrue(response.data['results'][0]['is_deleted'])
        self.assertEqual(response.data['results'][1]['body'], 'before')
        self.assertEqual(response.data['results'][2]['body'], 'after')

    def test_a_project_manager_can_delete_any_comment_and_is_recorded(self):
        self.client.force_authenticate(user=self.manager)

        response = self.delete()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        comment = Comment.objects.get(pk=self.comment.pk)
        self.assertEqual(comment.deleted_by, self.manager)
        self.assertEqual(comment.author, self.member)
        self.assertEqual(comment.body, '')

    def test_a_team_member_cannot_delete_someone_elses_comment(self):
        theirs = self.make_comment(self.manager, 'Manager says')

        response = self.delete(comment=theirs)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['code'], 'permission_denied')
        self.assertEqual(
            response.data['detail'], 'You can only delete your own comments.',
        )
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_deleted)
        self.assertEqual(theirs.body, 'Manager says')

    def test_viewers_cannot_delete_comments(self):
        # Neither someone else's nor their own from before they were demoted.
        viewers_own = self.make_comment(self.viewer, 'From the viewer')
        self.client.force_authenticate(user=self.viewer)

        for comment in (self.comment, viewers_own):
            response = self.delete(comment=comment)

            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.assertFalse(Comment.objects.filter(deleted_at__isnull=False).exists())

    def test_non_members_get_the_same_404_as_for_a_missing_issue(self):
        self.client.force_authenticate(user=self.newcomer)

        hidden = self.delete()
        missing = self.client.delete('/api/v1/issues/999999/comments/1/')

        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(hidden.data, missing.data)
        self.assertFalse(Comment.objects.get(pk=self.comment.pk).is_deleted)

    def test_a_comment_cannot_be_deleted_through_another_issue(self):
        other_issue = self.make_issue(2)

        response = self.delete(issue=other_issue)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Comment.objects.get(pk=self.comment.pk).is_deleted)

    def test_deleting_twice_is_rejected_and_keeps_the_first_deleter(self):
        self.delete()
        self.client.force_authenticate(user=self.manager)

        response = self.delete()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Comment is already deleted.')
        self.assertEqual(
            Comment.objects.get(pk=self.comment.pk).deleted_by, self.member,
        )

    def test_archived_issues_are_read_only(self):
        self.issue.is_archived = True
        self.issue.save()

        response = self.delete()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Comment.objects.get(pk=self.comment.pk).is_deleted)

    def test_archived_projects_are_hidden_like_the_issue_endpoints(self):
        self.archive_project()

        self.assertEqual(self.delete().status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_requests_are_rejected(self):
        self.client.force_authenticate(user=None)

        self.assertEqual(
            self.delete().status_code, status.HTTP_401_UNAUTHORIZED,
        )

    def test_the_original_text_is_gone_from_every_response_and_from_storage(self):
        self.delete()

        for response in (
            self.client.get(self.list_url()),
            self.client.get(self.detail_url(self.comment)),
        ):
            self.assertNotIn('Something private', str(response.data))

        stored = Comment.objects.filter(pk=self.comment.pk).values()
        self.assertNotIn('Something private', str(list(stored)))

    def test_a_deleted_comment_cannot_be_brought_back_by_editing(self):
        self.delete()

        response = self.client.patch(
            self.detail_url(self.comment), {'body': 'Revived'}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Comment.objects.get(pk=self.comment.pk).is_deleted)

    def test_other_comments_are_untouched(self):
        other = self.make_comment(self.member, 'Keep me')

        self.delete()

        other.refresh_from_db()
        self.assertFalse(other.is_deleted)
        self.assertEqual(other.body, 'Keep me')
