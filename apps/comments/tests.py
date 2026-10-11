from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from .models import Comment
from .services.mentions import MAX_MENTIONS, extract_mentioned_usernames
from .testing import CommentAPITestCase

User = get_user_model()


class CommentModelTests(CommentAPITestCase):

    def test_defaults(self):
        comment = self.make_comment()

        self.assertEqual(comment.issue, self.issue)
        self.assertEqual(comment.author, self.manager)
        self.assertIsNotNone(comment.created_at)
        self.assertIsNotNone(comment.updated_at)
        self.assertIsNone(comment.edited_at)
        self.assertIsNone(comment.deleted_at)
        self.assertIsNone(comment.deleted_by)
        self.assertFalse(comment.is_deleted)

    def test_is_deleted_follows_deleted_at(self):
        comment = self.make_comment(deleted_at=timezone.now())

        self.assertTrue(comment.is_deleted)

    def test_oldest_first_ordering(self):
        now = timezone.now()

        for offset, body in ((2, 'third'), (0, 'first'), (1, 'second')):
            with mock.patch(
                'django.utils.timezone.now',
                return_value=now + timedelta(minutes=offset),
            ):
                self.make_comment(body=body)

        self.assertEqual(
            list(Comment.objects.values_list('body', flat=True)),
            ['first', 'second', 'third'],
        )

    def test_equal_timestamps_are_ordered_by_id(self):
        frozen = timezone.now()

        with mock.patch('django.utils.timezone.now', return_value=frozen):
            created = [self.make_comment(body=str(i)) for i in range(4)]

        self.assertEqual(
            list(Comment.objects.values_list('id', flat=True)),
            [c.id for c in created],
        )

    def test_comments_belong_to_exactly_one_issue(self):
        other = self.make_issue(2)
        mine = self.make_comment()
        self.make_comment(issue=other)

        self.assertEqual(list(self.issue.comments.all()), [mine])

    def test_issue_index_exists(self):
        self.assertEqual(
            {index.name for index in Comment._meta.indexes},
            {'comment_issue_created_idx'},
        )

    def test_authors_with_comments_cannot_be_deleted(self):
        self.make_comment(author=self.member)

        with self.assertRaises(ProtectedError):
            self.member.delete()

    def test_deleting_an_issue_removes_its_comments(self):
        other = self.make_issue(2)
        self.make_comment(issue=other)

        other.delete()

        self.assertFalse(Comment.objects.filter(issue_id=other.id).exists())


class CommentAdminTests(CommentAPITestCase):

    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser(
            username='root', password='TestPassword123',
        )
        self.comment = self.make_comment(body='Visible in admin')
        self.client.force_login(self.admin_user)

    def test_changelist_is_visible(self):
        response = self.client.get('/admin/comments/comment/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Comment #')

    def test_cannot_add_or_rewrite_comments(self):
        self.assertEqual(
            self.client.get('/admin/comments/comment/add/').status_code, 403,
        )

        url = f'/admin/comments/comment/{self.comment.pk}/change/'
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(
            self.client.post(url, {'body': 'tampered'}).status_code, 403,
        )

        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, 'Visible in admin')


class ExtractMentionedUsernamesTests(TestCase):

    def test_finds_mentions_in_order_without_duplicates(self):
        text = '@sam please review, cc @priya and @sam again'

        self.assertEqual(
            extract_mentioned_usernames(text), ['sam', 'priya'],
        )

    def test_is_case_insensitive(self):
        self.assertEqual(extract_mentioned_usernames('Hi @Sam'), ['sam'])

    def test_mention_at_the_start_and_after_punctuation(self):
        self.assertEqual(
            extract_mentioned_usernames('(@sam) and "@priya"\n@jo'),
            ['sam', 'priya', 'jo'],
        )

    def test_trailing_punctuation_is_not_part_of_the_name(self):
        self.assertEqual(
            extract_mentioned_usernames('Thanks @sam. And @jo, bye @amy!'),
            ['sam', 'jo', 'amy'],
        )

    def test_names_may_contain_dots_dashes_and_underscores(self):
        self.assertEqual(
            extract_mentioned_usernames('@jane.doe @a-b @c_d'),
            ['jane.doe', 'a-b', 'c_d'],
        )

    def test_email_addresses_are_not_mentions(self):
        self.assertEqual(
            extract_mentioned_usernames('mail jane@example.com or a.b@c.org'),
            [],
        )

    def test_lone_and_doubled_at_signs_are_ignored(self):
        self.assertEqual(
            extract_mentioned_usernames('@ @@sam @. email@'), [],
        )

    def test_empty_and_missing_text(self):
        self.assertEqual(extract_mentioned_usernames(''), [])
        self.assertEqual(extract_mentioned_usernames(None), [])

    def test_number_of_mentions_is_bounded(self):
        text = ' '.join(f'@user{i}' for i in range(MAX_MENTIONS + 15))

        self.assertEqual(len(extract_mentioned_usernames(text)), MAX_MENTIONS)
