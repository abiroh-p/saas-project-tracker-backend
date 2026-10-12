"""Cross-project list (GET /api/v1/issues/) and the `assignee` filter keywords.

The per-project search/filter behaviour is covered by test_search.py.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.projects.models import Project, ProjectMember

from .filters import issue_key_parts
from .models import Issue

User = get_user_model()

URL = '/api/v1/issues/'


class IssueKeyPartsTests(APITestCase):

    def test_splits_a_full_key(self):
        self.assertEqual(issue_key_parts('API-12'), ('API', 12))
        self.assertEqual(issue_key_parts('api-007'), ('api', 7))

    def test_rejects_anything_that_is_not_a_key(self):
        for term in ('', 'API', 'API-', '-12', 'API-1x', 'API 12', 'A-B-1',
                     'API-0', 'API-2147483648'):
            with self.subTest(term=term):
                self.assertIsNone(issue_key_parts(term))


class GlobalIssueListTestCase(APITestCase):
    """`me` belongs to ALPHA (manager) and BETA (viewer); not to GAMMA."""

    def setUp(self):
        self.me = User.objects.create_user(
            username='me', password='TestPassword123', full_name='Me Myself',
        )
        self.other = User.objects.create_user(
            username='other', password='TestPassword123',
        )

        self.alpha = self.make_project('ALPHA', self.me)
        self.beta = self.make_project('BETA', self.other)
        self.gamma = self.make_project('GAMMA', self.other)

        self.add_member(self.alpha, self.me, ProjectMember.Role.PROJECT_MANAGER)
        self.add_member(self.alpha, self.other, ProjectMember.Role.TEAM_MEMBER)
        self.add_member(self.beta, self.me, ProjectMember.Role.VIEWER)
        self.add_member(self.beta, self.other, ProjectMember.Role.PROJECT_MANAGER)
        self.add_member(self.gamma, self.other, ProjectMember.Role.PROJECT_MANAGER)

        self.client.force_authenticate(user=self.me)

    def make_project(self, key, creator, **extra):
        return Project.objects.create(
            key=key, name=f'{key} project', created_by=creator, **extra,
        )

    def add_member(self, project, user, role):
        return ProjectMember.objects.create(
            project=project, user=user, role=role,
        )

    def make_issue(self, project, number, **extra):
        extra.setdefault('title', f'{project.key} issue {number}')
        extra.setdefault('reporter', self.other)

        return Issue.objects.create(
            project=project, issue_number=number, **extra,
        )

    def get(self, params=None):
        return self.client.get(URL, params or {})

    def keys(self, response):
        return [item['issue_key'] for item in response.data['results']]

    def assert_bad_request(self, response, detail=None):
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data['code'], 'bad_request')

        if detail is not None:
            self.assertEqual(response.data['detail'], detail)


class GlobalIssueListAccessTests(GlobalIssueListTestCase):

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)

        self.assertEqual(self.get().status_code, 401)

    def test_only_get_is_allowed(self):
        for method in ('post', 'put', 'patch', 'delete'):
            response = getattr(self.client, method)(URL, {}, format='json')

            self.assertEqual(response.status_code, 405, method)

    def test_lists_issues_of_every_project_the_user_belongs_to(self):
        self.make_issue(self.alpha, 1)
        self.make_issue(self.beta, 1)

        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(self.keys(response)), {'ALPHA-1', 'BETA-1'},
        )
        self.assertEqual(response.data['count'], 2)

    def test_projects_the_user_is_not_a_member_of_are_hidden(self):
        self.make_issue(self.alpha, 1)
        self.make_issue(self.gamma, 1, title='secret roadmap')

        response = self.get()

        self.assertEqual(self.keys(response), ['ALPHA-1'])
        self.assertNotIn('secret roadmap', str(response.data))

    def test_archived_projects_and_archived_issues_are_hidden(self):
        archived_project = self.make_project(
            'OLD', self.me, is_archived=True,
        )
        self.add_member(
            archived_project, self.me, ProjectMember.Role.PROJECT_MANAGER,
        )
        self.make_issue(archived_project, 1)
        self.make_issue(self.alpha, 1, is_archived=True)
        self.make_issue(self.alpha, 2)

        self.assertEqual(self.keys(self.get()), ['ALPHA-2'])

    def test_viewers_can_read(self):
        self.make_issue(self.beta, 1)

        self.assertEqual(self.keys(self.get()), ['BETA-1'])

    def test_losing_membership_removes_the_issues(self):
        self.make_issue(self.beta, 1)
        ProjectMember.objects.get(project=self.beta, user=self.me).delete()

        self.assertEqual(self.keys(self.get()), [])

    def test_a_crowded_project_does_not_repeat_issues(self):
        for index in range(5):
            extra = User.objects.create_user(
                username=f'extra{index}', password='TestPassword123',
            )
            self.add_member(self.alpha, extra, ProjectMember.Role.TEAM_MEMBER)

        self.make_issue(self.alpha, 1)

        response = self.get()

        self.assertEqual(self.keys(response), ['ALPHA-1'])
        self.assertEqual(response.data['count'], 1)

    def test_empty_result_is_a_valid_page(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])


class GlobalIssueListPaginationTests(GlobalIssueListTestCase):

    def test_pages_across_projects(self):
        for number in range(1, 8):
            self.make_issue(self.alpha, number)
        for number in range(1, 6):
            self.make_issue(self.beta, number)

        first = self.get({'page_size': 5})
        last = self.get({'page_size': 5, 'page': 3})

        self.assertEqual(first.data['count'], 12)
        self.assertEqual(len(first.data['results']), 5)
        self.assertEqual(len(last.data['results']), 2)

    def test_default_page_size_is_20_and_capped_at_100(self):
        for number in range(1, 26):
            self.make_issue(self.alpha, number)

        self.assertEqual(len(self.get().data['results']), 20)
        self.assertEqual(
            len(self.get({'page_size': 1000}).data['results']), 25,
        )

    def test_page_out_of_range_is_a_404(self):
        self.make_issue(self.alpha, 1)

        self.assertEqual(self.get({'page': 9}).status_code, 404)


class GlobalIssueListFilterTests(GlobalIssueListTestCase):

    def test_filters_by_status_priority_and_type(self):
        self.make_issue(
            self.alpha, 1, status=Issue.Status.DONE,
            priority=Issue.Priority.URGENT, issue_type=Issue.IssueType.BUG,
        )
        self.make_issue(self.beta, 1)

        self.assertEqual(self.keys(self.get({'status': 'DONE'})), ['ALPHA-1'])
        self.assertEqual(
            self.keys(self.get({'priority': 'URGENT'})), ['ALPHA-1'],
        )
        self.assertEqual(
            self.keys(self.get({'issue_type': 'BUG'})), ['ALPHA-1'],
        )

    def test_filters_by_due_date_range(self):
        self.make_issue(self.alpha, 1, due_date=date(2026, 11, 1))
        self.make_issue(self.beta, 1, due_date=date(2026, 12, 1))
        self.make_issue(self.beta, 2)

        response = self.get({
            'due_after': '2026-11-15', 'due_before': '2026-12-31',
        })

        self.assertEqual(self.keys(response), ['BETA-1'])

    def test_project_filter_narrows_to_one_project(self):
        self.make_issue(self.alpha, 1)
        self.make_issue(self.beta, 1)

        response = self.get({'project': self.beta.id})

        self.assertEqual(self.keys(response), ['BETA-1'])

    def test_project_filter_for_a_foreign_project_matches_nothing(self):
        self.make_issue(self.gamma, 1)

        response = self.get({'project': self.gamma.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_invalid_project_filter_is_a_400(self):
        for value in ('abc', '0', '-3', '2147483648', '1.5'):
            with self.subTest(value=value):
                self.assert_bad_request(
                    self.get({'project': value}),
                    'Invalid project filter.',
                )

    def test_invalid_values_are_rejected_like_the_project_list(self):
        self.assert_bad_request(
            self.get({'status': 'BOGUS'}), 'Invalid status filter.',
        )
        self.assert_bad_request(
            self.get({'ordering': 'nope'}),
        )
        self.assert_bad_request(
            self.get({'due_after': '2026-12-31', 'due_before': '2026-01-01'}),
            'due_after cannot be later than due_before.',
        )

    def test_filters_combine_with_and(self):
        self.make_issue(self.alpha, 1, status=Issue.Status.DONE)
        self.make_issue(self.beta, 1, status=Issue.Status.DONE)

        response = self.get({
            'status': 'DONE', 'project': self.alpha.id,
        })

        self.assertEqual(self.keys(response), ['ALPHA-1'])


class GlobalIssueListAssigneeTests(GlobalIssueListTestCase):

    def setUp(self):
        super().setUp()
        self.mine = self.make_issue(self.alpha, 1, assignee=self.me)
        self.theirs = self.make_issue(self.alpha, 2, assignee=self.other)
        self.nobody = self.make_issue(self.alpha, 3)
        self.mine_beta = self.make_issue(self.beta, 1, assignee=self.me)

    def test_assignee_me_means_the_requester(self):
        response = self.get({'assignee': 'me'})

        self.assertEqual(
            set(self.keys(response)), {'ALPHA-1', 'BETA-1'},
        )

    def test_assignee_me_follows_the_authenticated_user(self):
        self.client.force_authenticate(user=self.other)

        self.assertEqual(self.keys(self.get({'assignee': 'me'})), ['ALPHA-2'])

    def test_assignee_me_is_case_insensitive(self):
        self.assertEqual(self.get({'assignee': 'ME'}).data['count'], 2)

    def test_assignee_unassigned(self):
        self.assertEqual(
            self.keys(self.get({'assignee': 'unassigned'})), ['ALPHA-3'],
        )

    def test_assignee_id_still_works(self):
        response = self.get({'assignee': self.other.id})

        self.assertEqual(self.keys(response), ['ALPHA-2'])

    def test_invalid_assignee_keeps_its_message(self):
        for value in ('abc', '0', '-1', '2147483648', 'nobody'):
            with self.subTest(value=value):
                self.assert_bad_request(
                    self.get({'assignee': value}),
                    'Invalid assignee filter.',
                )

    def test_keywords_work_on_the_project_list_too(self):
        url = f'/api/v1/projects/{self.alpha.id}/issues/'

        mine = self.client.get(url, {'assignee': 'me'})
        unassigned = self.client.get(url, {'assignee': 'unassigned'})

        self.assertEqual(
            [i['issue_key'] for i in mine.data['results']], ['ALPHA-1'],
        )
        self.assertEqual(
            [i['issue_key'] for i in unassigned.data['results']], ['ALPHA-3'],
        )

    def test_the_project_parameter_is_ignored_on_the_project_list(self):
        url = f'/api/v1/projects/{self.alpha.id}/issues/'

        response = self.client.get(url, {'project': self.beta.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 3)


class GlobalIssueListSearchTests(GlobalIssueListTestCase):

    def test_text_search_spans_projects(self):
        self.make_issue(self.alpha, 1, title='Fix login bug')
        self.make_issue(self.beta, 1, description='the login page')
        self.make_issue(self.beta, 2, title='Unrelated')

        response = self.get({'search': 'login'})

        self.assertEqual(set(self.keys(response)), {'ALPHA-1', 'BETA-1'})

    def test_an_issue_key_matches_that_issue_in_its_own_project(self):
        self.make_issue(self.alpha, 2)
        self.make_issue(self.beta, 2)
        self.make_issue(self.alpha, 3)

        self.assertEqual(self.keys(self.get({'search': 'BETA-2'})), ['BETA-2'])
        self.assertEqual(self.keys(self.get({'search': 'alpha-2'})), ['ALPHA-2'])

    def test_a_key_does_not_match_a_longer_number(self):
        self.make_issue(self.alpha, 1)
        self.make_issue(self.alpha, 10)

        self.assertEqual(self.keys(self.get({'search': 'ALPHA-1'})), ['ALPHA-1'])

    def test_a_key_of_a_project_the_user_cannot_see_finds_nothing(self):
        self.make_issue(self.gamma, 1)

        self.assertEqual(self.get({'search': 'GAMMA-1'}).data['count'], 0)

    def test_key_search_combines_with_the_project_filter(self):
        self.make_issue(self.alpha, 1)
        self.make_issue(self.beta, 1)

        response = self.get({
            'search': 'BETA-1', 'project': self.alpha.id,
        })

        self.assertEqual(response.data['count'], 0)

    def test_search_rejects_nul_and_overlong_terms(self):
        self.assert_bad_request(self.get({'search': 'a\x00b'}))
        self.assert_bad_request(self.get({'search': 'x' * 101}))


class GlobalIssueListOrderingTests(GlobalIssueListTestCase):

    def test_default_order_is_newest_first(self):
        first = self.make_issue(self.alpha, 1)
        second = self.make_issue(self.beta, 1)

        self.assertEqual(
            [item['id'] for item in self.get().data['results']],
            [second.id, first.id],
        )

    def test_ordering_by_priority_uses_urgency(self):
        self.make_issue(self.alpha, 1, priority=Issue.Priority.LOW)
        self.make_issue(self.beta, 1, priority=Issue.Priority.URGENT)
        self.make_issue(self.alpha, 2, priority=Issue.Priority.HIGH)

        response = self.get({'ordering': '-priority'})

        self.assertEqual(self.keys(response), ['BETA-1', 'ALPHA-2', 'ALPHA-1'])

    def test_issues_without_a_due_date_always_come_last(self):
        self.make_issue(self.alpha, 1)
        self.make_issue(self.alpha, 2, due_date=date(2026, 11, 2))
        self.make_issue(self.beta, 1, due_date=date(2026, 11, 1))

        ascending = self.keys(self.get({'ordering': 'due_date'}))
        descending = self.keys(self.get({'ordering': '-due_date'}))

        self.assertEqual(ascending, ['BETA-1', 'ALPHA-2', 'ALPHA-1'])
        self.assertEqual(descending, ['ALPHA-2', 'BETA-1', 'ALPHA-1'])


class GlobalIssueListPayloadTests(GlobalIssueListTestCase):

    def test_user_refs_include_the_full_name_and_nothing_private(self):
        self.other.full_name = 'Olivia Other'
        self.other.save()
        self.make_issue(self.alpha, 1, assignee=self.me)

        item = self.get().data['results'][0]

        self.assertEqual(
            item['assignee_detail'],
            {'id': self.me.id, 'username': 'me', 'full_name': 'Me Myself'},
        )
        self.assertEqual(
            item['reporter_detail'],
            {
                'id': self.other.id,
                'username': 'other',
                'full_name': 'Olivia Other',
            },
        )
        self.assertNotIn('@', str(item))

    def test_unassigned_issue_has_no_assignee_detail(self):
        self.make_issue(self.alpha, 1)

        item = self.get().data['results'][0]

        self.assertIsNone(item['assignee'])
        self.assertIsNone(item['assignee_detail'])

    def test_the_item_shape_matches_the_project_list(self):
        self.make_issue(self.alpha, 1, assignee=self.me)

        global_item = self.get().data['results'][0]
        project_item = self.client.get(
            f'/api/v1/projects/{self.alpha.id}/issues/'
        ).data['results'][0]

        self.assertEqual(global_item, project_item)

    def test_query_count_does_not_grow_with_the_number_of_issues(self):
        self.make_issue(self.alpha, 1, assignee=self.me)

        with CaptureQueriesContext(connection) as small:
            self.get()

        for number in range(2, 18):
            self.make_issue(
                self.alpha if number % 2 else self.beta,
                number,
                assignee=self.me,
            )

        with CaptureQueriesContext(connection) as large:
            self.get()

        self.assertEqual(len(small), len(large))
