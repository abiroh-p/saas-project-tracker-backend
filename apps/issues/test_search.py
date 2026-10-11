"""Search, filtering and ordering on GET /api/v1/projects/<id>/issues/."""
from datetime import date, datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.projects.models import Project, ProjectMember

from .filters import ORDERING_CHOICES, issue_number_from_key
from .models import Issue
from .serializers import IssueSerializer

User = get_user_model()


class IssueKeyParsingTests(SimpleTestCase):
    """`issue_key` is a property, so keys are parsed rather than queried."""

    def test_full_key_returns_the_issue_number(self):
        self.assertEqual(issue_number_from_key('SRCH-12', 'SRCH'), 12)

    def test_key_is_case_insensitive_on_both_sides(self):
        self.assertEqual(issue_number_from_key('srch-12', 'SRCH'), 12)
        self.assertEqual(issue_number_from_key('SRCH-12', 'srch'), 12)

    def test_leading_zeros_are_accepted(self):
        self.assertEqual(issue_number_from_key('SRCH-007', 'SRCH'), 7)

    def test_other_project_prefix_does_not_match(self):
        self.assertIsNone(issue_number_from_key('OTHER-1', 'SRCH'))

    def test_prefix_that_only_starts_with_the_key_does_not_match(self):
        self.assertIsNone(issue_number_from_key('SRCHX-1', 'SRCH'))

    def test_non_keys_return_none(self):
        for term in (
            'SRCH', 'SRCH-', '-1', 'SRCH-abc', 'SRCH-1-2', 'SRCH 1',
            'login', '', 'SRCH-1.5', 'SRCH--1',
        ):
            with self.subTest(term=term):
                self.assertIsNone(issue_number_from_key(term, 'SRCH'))

    def test_zero_and_out_of_range_numbers_return_none(self):
        for term in ('SRCH-0', 'SRCH-2147483648', 'SRCH-' + '9' * 40):
            with self.subTest(term=term):
                self.assertIsNone(issue_number_from_key(term, 'SRCH'))

    def test_largest_database_integer_is_accepted(self):
        self.assertEqual(
            issue_number_from_key('SRCH-2147483647', 'SRCH'),
            2147483647,
        )


class IssueListAPITestCase(APITestCase):
    """A project with a manager, member, viewer and outsider, plus a second
    project the manager also belongs to. The manager is authenticated."""

    def setUp(self):
        self.manager = User.objects.create_user(
            username='s_manager', password='TestPassword123',
        )
        self.member = User.objects.create_user(
            username='s_member', password='TestPassword123',
        )
        self.viewer = User.objects.create_user(
            username='s_viewer', password='TestPassword123',
        )
        self.outsider = User.objects.create_user(
            username='s_outsider', password='TestPassword123',
        )

        self.project = Project.objects.create(
            key='SRCH', name='Search project', created_by=self.manager,
        )
        self.add_member(self.manager, ProjectMember.Role.PROJECT_MANAGER)
        self.add_member(self.member, ProjectMember.Role.TEAM_MEMBER)
        self.add_member(self.viewer, ProjectMember.Role.VIEWER)

        self.other_project = Project.objects.create(
            key='OTHER', name='Other project', created_by=self.manager,
        )
        self.add_member(
            self.manager,
            ProjectMember.Role.PROJECT_MANAGER,
            project=self.other_project,
        )

        self.client.force_authenticate(user=self.manager)

    # -- helpers ----------------------------------------------------------

    def add_member(self, user, role, project=None):
        return ProjectMember.objects.create(
            project=project or self.project, user=user, role=role,
        )

    def make_issue(self, number, project=None, **extra):
        extra.setdefault('title', f'Issue {number}')
        extra.setdefault('reporter', self.manager)

        return Issue.objects.create(
            project=project or self.project,
            issue_number=number,
            **extra,
        )

    def url(self, project=None):
        return f'/api/v1/projects/{(project or self.project).id}/issues/'

    def get(self, params=None, project=None):
        return self.client.get(self.url(project), params or {})

    def keys(self, response):
        return [item['issue_key'] for item in response.data['results']]

    def assert_bad_request(self, response, detail=None):
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data['code'], 'bad_request')

        if detail is not None:
            self.assertEqual(response.data['detail'], detail)


class IssueSearchTests(IssueListAPITestCase):

    def test_search_matches_title(self):
        self.make_issue(1, title='Fix the login button')
        self.make_issue(2, title='Update billing page')

        response = self.get({'search': 'login'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.keys(response), ['SRCH-1'])

    def test_search_matches_description(self):
        self.make_issue(1, title='Crash', description='Fails during login')
        self.make_issue(2, title='Typo', description='Wrong label')

        self.assertEqual(self.keys(self.get({'search': 'login'})), ['SRCH-1'])

    def test_search_matches_title_or_description(self):
        self.make_issue(1, title='Login page crash')
        self.make_issue(2, title='Checkout', description='after login')
        self.make_issue(3, title='Unrelated')

        response = self.get({'search': 'login', 'ordering': 'issue_number'})

        self.assertEqual(self.keys(response), ['SRCH-1', 'SRCH-2'])

    def test_search_is_case_insensitive(self):
        self.make_issue(1, title='Fix Login Bug')

        for term in ('login', 'LOGIN', 'LoGiN'):
            with self.subTest(term=term):
                self.assertEqual(
                    self.keys(self.get({'search': term})), ['SRCH-1'],
                )

    def test_search_matches_part_of_a_word(self):
        self.make_issue(1, title='Authentication flow')

        self.assertEqual(self.keys(self.get({'search': 'thentic'})), ['SRCH-1'])

    def test_non_matching_term_returns_empty_page(self):
        self.make_issue(1, title='Fix login')

        response = self.get({'search': 'zzz-no-match'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])
        self.assertIsNone(response.data['next'])
        self.assertIsNone(response.data['previous'])

    def test_search_term_is_trimmed(self):
        self.make_issue(1, title='Fix login')

        self.assertEqual(self.keys(self.get({'search': '  login  '})), ['SRCH-1'])

    def test_blank_search_is_ignored(self):
        self.make_issue(1)
        self.make_issue(2)

        for term in ('', '   '):
            with self.subTest(term=term):
                response = self.get({'search': term})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['count'], 2)

    def test_search_keeps_spaces_inside_the_term(self):
        self.make_issue(1, title='Fix login page')
        self.make_issue(2, title='Fix page login')

        self.assertEqual(
            self.keys(self.get({'search': 'login page'})), ['SRCH-1'],
        )

    def test_percent_and_underscore_are_matched_literally(self):
        self.make_issue(1, title='Reach 100% coverage')
        self.make_issue(2, title='snake_case names')
        self.make_issue(3, title='Plain title')

        self.assertEqual(self.keys(self.get({'search': '%'})), ['SRCH-1'])
        self.assertEqual(self.keys(self.get({'search': '_'})), ['SRCH-2'])

    def test_sql_like_input_is_treated_as_text(self):
        self.make_issue(1, title="Robert'); DROP TABLE issues_issue;--")
        self.make_issue(2, title='Plain')

        response = self.get({'search': "'); DROP TABLE"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.keys(response), ['SRCH-1'])
        self.assertEqual(Issue.objects.count(), 2)

    def test_unicode_search(self):
        self.make_issue(1, title='Café menu update')
        self.make_issue(2, title='Plain')

        self.assertEqual(self.keys(self.get({'search': 'CAFÉ'})), ['SRCH-1'])

    def test_search_does_not_match_people(self):
        # Reporter and assignee names are not searchable fields.
        secret = User.objects.create_user(
            username='hidden_person',
            email='hidden_person@example.com',
            password='TestPassword123',
        )
        self.add_member(secret, ProjectMember.Role.TEAM_MEMBER)
        self.make_issue(1, title='Plain', reporter=secret, assignee=secret)

        for term in ('hidden_person', 'hidden_person@example.com'):
            with self.subTest(term=term):
                self.assertEqual(self.get({'search': term}).data['count'], 0)

    # -- search term validation ------------------------------------------

    def test_search_at_the_length_limit_is_accepted(self):
        response = self.get({'search': 'a' * 100})

        self.assertEqual(response.status_code, 200)

    def test_search_over_the_length_limit_is_rejected(self):
        response = self.get({'search': 'a' * 101})

        self.assert_bad_request(
            response, 'Search term must be at most 100 characters.',
        )

    def test_search_with_nul_character_is_rejected_not_a_server_error(self):
        response = self.get({'search': 'abc\x00def'})

        self.assert_bad_request(response, 'Invalid search term.')

    # -- issue key search -------------------------------------------------

    def test_search_by_issue_key(self):
        self.make_issue(1)
        self.make_issue(2)
        self.make_issue(20)

        self.assertEqual(self.keys(self.get({'search': 'SRCH-2'})), ['SRCH-2'])

    def test_issue_key_search_is_case_insensitive(self):
        self.make_issue(7)

        self.assertEqual(self.keys(self.get({'search': 'srch-7'})), ['SRCH-7'])

    def test_issue_key_search_is_exact_not_a_prefix(self):
        self.make_issue(1)
        self.make_issue(10)

        self.assertEqual(self.keys(self.get({'search': 'SRCH-1'})), ['SRCH-1'])

    def test_issue_key_of_another_project_finds_nothing(self):
        self.make_issue(1)
        self.make_issue(1, project=self.other_project, title='Elsewhere')

        response = self.get({'search': 'OTHER-1'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_unknown_issue_number_finds_nothing(self):
        self.make_issue(1)

        self.assertEqual(self.get({'search': 'SRCH-99'}).data['count'], 0)

    def test_huge_issue_number_is_not_a_server_error(self):
        self.make_issue(1)

        for term in ('SRCH-0', 'SRCH-2147483648', 'SRCH-' + '9' * 40):
            with self.subTest(term=term):
                response = self.get({'search': term})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['count'], 0)

    def test_key_search_also_matches_text_containing_the_term(self):
        self.make_issue(1, title='Duplicate of SRCH-5')
        self.make_issue(5)

        response = self.get({'search': 'SRCH-5', 'ordering': 'issue_number'})

        self.assertEqual(self.keys(response), ['SRCH-1', 'SRCH-5'])

    def test_key_search_skips_archived_issues(self):
        self.make_issue(1, is_archived=True)

        self.assertEqual(self.get({'search': 'SRCH-1'}).data['count'], 0)

    # -- scope ------------------------------------------------------------

    def test_search_never_returns_another_projects_issues(self):
        self.make_issue(1, title='Login here')
        self.make_issue(1, project=self.other_project, title='Login elsewhere')

        response = self.get({'search': 'login'})

        self.assertEqual(self.keys(response), ['SRCH-1'])

    def test_archived_issues_stay_excluded_from_search(self):
        self.make_issue(1, title='Login live')
        self.make_issue(2, title='Login archived', is_archived=True)

        self.assertEqual(self.keys(self.get({'search': 'login'})), ['SRCH-1'])


class IssueFilterCombinationTests(IssueListAPITestCase):
    """Search and filters narrow the result together (AND)."""

    def setUp(self):
        super().setUp()

        self.make_issue(
            1, title='Login page crash',
            issue_type=Issue.IssueType.BUG,
            priority=Issue.Priority.HIGH,
            status=Issue.Status.IN_PROGRESS,
            assignee=self.member,
        )
        self.make_issue(
            2, title='Login form typo',
            issue_type=Issue.IssueType.TASK,
            priority=Issue.Priority.LOW,
            status=Issue.Status.TODO,
        )
        self.make_issue(
            3, title='Checkout fails', description='Happens after login',
            issue_type=Issue.IssueType.BUG,
            priority=Issue.Priority.HIGH,
            status=Issue.Status.IN_PROGRESS,
            assignee=self.member,
        )
        self.make_issue(
            4, title='Unrelated bug',
            issue_type=Issue.IssueType.BUG,
            priority=Issue.Priority.HIGH,
            status=Issue.Status.IN_PROGRESS,
            assignee=self.member,
        )
        self.make_issue(5, title='Login archived', is_archived=True)

    def found(self, params):
        params = {'ordering': 'issue_number', **params}
        response = self.get(params)

        self.assertEqual(response.status_code, 200, response.data)

        return self.keys(response)

    def test_search_alone(self):
        self.assertEqual(
            self.found({'search': 'login'}), ['SRCH-1', 'SRCH-2', 'SRCH-3'],
        )

    def test_search_with_status(self):
        self.assertEqual(
            self.found({'search': 'login', 'status': 'IN_PROGRESS'}),
            ['SRCH-1', 'SRCH-3'],
        )

    def test_search_with_priority(self):
        self.assertEqual(
            self.found({'search': 'login', 'priority': 'LOW'}), ['SRCH-2'],
        )

    def test_search_with_issue_type(self):
        self.assertEqual(
            self.found({'search': 'login', 'issue_type': 'TASK'}), ['SRCH-2'],
        )

    def test_search_with_assignee(self):
        self.assertEqual(
            self.found({'search': 'login', 'assignee': self.member.id}),
            ['SRCH-1', 'SRCH-3'],
        )

    def test_search_with_every_filter(self):
        self.assertEqual(
            self.found({
                'search': 'login',
                'status': 'IN_PROGRESS',
                'priority': 'HIGH',
                'issue_type': 'BUG',
                'assignee': self.member.id,
            }),
            ['SRCH-1', 'SRCH-3'],
        )

    def test_filters_do_not_override_each_other(self):
        # Matches the search, but not the status.
        self.assertEqual(
            self.found({'search': 'typo', 'status': 'IN_PROGRESS'}), [],
        )
        # Matches status and priority, but not the search.
        self.assertEqual(
            self.found({
                'search': 'checkout', 'status': 'IN_PROGRESS',
                'priority': 'LOW',
            }),
            [],
        )

    def test_filters_without_search_still_work(self):
        self.assertEqual(
            self.found({'status': 'TODO'}), ['SRCH-2'],
        )
        self.assertEqual(
            self.found({'issue_type': 'BUG'}),
            ['SRCH-1', 'SRCH-3', 'SRCH-4'],
        )

    def test_assignee_who_is_not_a_project_member_returns_empty(self):
        response = self.get({'assignee': self.outsider.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_blank_filter_values_are_ignored(self):
        response = self.get({
            'status': '', 'priority': '', 'issue_type': '', 'assignee': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 4)

    def test_unknown_query_parameters_are_ignored(self):
        response = self.get({'colour': 'red', 'is_archived': 'true'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 4)


class IssueFilterValidationTests(IssueListAPITestCase):

    def test_invalid_enum_values_keep_their_messages(self):
        cases = (
            ('status', 'INVALID', 'Invalid status filter.'),
            ('priority', 'INVALID', 'Invalid priority filter.'),
            ('issue_type', 'INVALID', 'Invalid issue type filter.'),
        )

        for name, value, detail in cases:
            with self.subTest(name=name):
                self.assert_bad_request(self.get({name: value}), detail)

    def test_enum_values_are_case_sensitive(self):
        self.assert_bad_request(
            self.get({'status': 'todo'}), 'Invalid status filter.',
        )

    def test_invalid_assignee_values_are_rejected(self):
        for value in ('abc', '1.5', '0', '-1', '99999999999999999999', ' '):
            if value.strip() == '':
                continue  # blank is "no filter", covered elsewhere

            with self.subTest(value=value):
                self.assert_bad_request(
                    self.get({'assignee': value}),
                    'Invalid assignee filter.',
                )

    def test_invalid_filter_never_applies_partially(self):
        self.make_issue(1)

        response = self.get({'search': 'issue', 'status': 'INVALID'})

        self.assert_bad_request(response, 'Invalid status filter.')

    def test_errors_use_the_standard_error_shape(self):
        response = self.get({'priority': 'INVALID'})

        self.assertEqual(set(response.data), {'detail', 'code'})


class IssueDueDateFilterTests(IssueListAPITestCase):

    def setUp(self):
        super().setUp()

        self.make_issue(1, due_date=date(2026, 10, 1))
        self.make_issue(2, due_date=date(2026, 10, 15))
        self.make_issue(3, due_date=date(2026, 10, 31))
        self.make_issue(4)  # no due date

    def found(self, params):
        response = self.get({'ordering': 'issue_number', **params})

        self.assertEqual(response.status_code, 200, response.data)

        return self.keys(response)

    def test_due_before_is_inclusive(self):
        self.assertEqual(
            self.found({'due_before': '2026-10-15'}), ['SRCH-1', 'SRCH-2'],
        )

    def test_due_after_is_inclusive(self):
        self.assertEqual(
            self.found({'due_after': '2026-10-15'}), ['SRCH-2', 'SRCH-3'],
        )

    def test_due_range_combines(self):
        self.assertEqual(
            self.found({'due_after': '2026-10-02', 'due_before': '2026-10-30'}),
            ['SRCH-2'],
        )

    def test_single_day_range_is_allowed(self):
        self.assertEqual(
            self.found({'due_after': '2026-10-15', 'due_before': '2026-10-15'}),
            ['SRCH-2'],
        )

    def test_issues_without_a_due_date_are_excluded_by_date_filters(self):
        keys = self.found({'due_after': '1900-01-01', 'due_before': '2999-12-31'})

        self.assertNotIn('SRCH-4', keys)

    def test_due_date_filter_combines_with_search_and_status(self):
        Issue.objects.filter(issue_number=2).update(
            title='Release notes', status=Issue.Status.DONE,
        )

        self.assertEqual(
            self.found({
                'due_before': '2026-10-31',
                'search': 'release',
                'status': 'DONE',
            }),
            ['SRCH-2'],
        )

    def test_invalid_dates_are_rejected(self):
        for value in (
            'abc', '2026-13-01', '2026-02-30', '2026-1-1', '20261001',
            '2026-10-01T00:00:00', '01-10-2026', '0000-01-01', '2026-10-1',
        ):
            for name in ('due_before', 'due_after'):
                with self.subTest(name=name, value=value):
                    self.assert_bad_request(
                        self.get({name: value}),
                        f'Invalid {name} filter. Use the format YYYY-MM-DD.',
                    )

    def test_conflicting_range_is_rejected(self):
        response = self.get({
            'due_after': '2026-10-20', 'due_before': '2026-10-10',
        })

        self.assert_bad_request(
            response, 'due_after cannot be later than due_before.',
        )

    def test_blank_dates_are_ignored(self):
        response = self.get({'due_before': '', 'due_after': ''})

        self.assertEqual(response.data['count'], 4)


class IssueOrderingTests(IssueListAPITestCase):

    def ordered(self, ordering, **params):
        response = self.get({'ordering': ordering, **params})

        self.assertEqual(response.status_code, 200, response.data)

        return self.keys(response)

    def test_default_order_is_newest_first(self):
        self.make_issue(1)
        self.make_issue(2)
        self.make_issue(3)

        self.assertEqual(self.keys(self.get()), ['SRCH-3', 'SRCH-2', 'SRCH-1'])

    def test_blank_ordering_uses_the_default(self):
        self.make_issue(1)
        self.make_issue(2)

        self.assertEqual(self.keys(self.get({'ordering': ''})), ['SRCH-2', 'SRCH-1'])

    def test_order_by_created_at(self):
        issues = [self.make_issue(n) for n in (1, 2, 3)]
        for offset, issue in zip((2, 0, 1), issues):
            Issue.objects.filter(pk=issue.pk).update(
                created_at=datetime(2026, 1, 1 + offset, tzinfo=dt_timezone.utc),
            )

        self.assertEqual(
            self.ordered('created_at'), ['SRCH-2', 'SRCH-3', 'SRCH-1'],
        )
        self.assertEqual(
            self.ordered('-created_at'), ['SRCH-1', 'SRCH-3', 'SRCH-2'],
        )

    def test_order_by_updated_at(self):
        issues = [self.make_issue(n) for n in (1, 2, 3)]
        for day, issue in zip((3, 1, 2), issues):
            Issue.objects.filter(pk=issue.pk).update(
                updated_at=datetime(2026, 2, day, tzinfo=dt_timezone.utc),
            )

        self.assertEqual(
            self.ordered('updated_at'), ['SRCH-2', 'SRCH-3', 'SRCH-1'],
        )
        self.assertEqual(
            self.ordered('-updated_at'), ['SRCH-1', 'SRCH-3', 'SRCH-2'],
        )

    def test_order_by_title_ignores_case(self):
        self.make_issue(1, title='banana')
        self.make_issue(2, title='Apple')
        self.make_issue(3, title='cherry')

        self.assertEqual(self.ordered('title'), ['SRCH-2', 'SRCH-1', 'SRCH-3'])
        self.assertEqual(self.ordered('-title'), ['SRCH-3', 'SRCH-1', 'SRCH-2'])

    def test_order_by_priority_sorts_by_urgency_not_alphabet(self):
        self.make_issue(1, priority=Issue.Priority.HIGH)
        self.make_issue(2, priority=Issue.Priority.LOW)
        self.make_issue(3, priority=Issue.Priority.URGENT)
        self.make_issue(4, priority=Issue.Priority.MEDIUM)

        self.assertEqual(
            self.ordered('priority'),
            ['SRCH-2', 'SRCH-4', 'SRCH-1', 'SRCH-3'],
        )
        self.assertEqual(
            self.ordered('-priority'),
            ['SRCH-3', 'SRCH-1', 'SRCH-4', 'SRCH-2'],
        )

    def test_order_by_due_date_puts_missing_dates_last_both_ways(self):
        self.make_issue(1, due_date=date(2026, 10, 20))
        self.make_issue(2)
        self.make_issue(3, due_date=date(2026, 10, 5))

        self.assertEqual(self.ordered('due_date'), ['SRCH-3', 'SRCH-1', 'SRCH-2'])
        self.assertEqual(self.ordered('-due_date'), ['SRCH-1', 'SRCH-3', 'SRCH-2'])

    def test_order_by_issue_number(self):
        for number in (3, 1, 2):
            self.make_issue(number)

        self.assertEqual(
            self.ordered('issue_number'), ['SRCH-1', 'SRCH-2', 'SRCH-3'],
        )
        self.assertEqual(
            self.ordered('-issue_number'), ['SRCH-3', 'SRCH-2', 'SRCH-1'],
        )

    def test_every_documented_ordering_value_is_accepted(self):
        self.make_issue(1)

        for value in ORDERING_CHOICES:
            with self.subTest(ordering=value):
                self.assertEqual(self.get({'ordering': value}).status_code, 200)

    def test_unsupported_ordering_is_rejected(self):
        for value in (
            'id', '-id', 'reporter', 'reporter__password', 'assignee__email',
            'project__key', 'status', 'password', 'TITLE', '?',
            'title,created_at', '-title,-id', '--title', '-', ' title',
            'title; DROP TABLE issues_issue', 'created_at desc',
        ):
            with self.subTest(ordering=value):
                response = self.get({'ordering': value})

                self.assert_bad_request(response)
                self.assertTrue(
                    response.data['detail'].startswith('Invalid ordering.')
                )

    def test_equal_values_keep_a_stable_order_across_pages(self):
        for number in range(1, 26):
            self.make_issue(number, title='Same title')

        for ordering in ('title', '-title', 'priority', 'due_date'):
            with self.subTest(ordering=ordering):
                seen = []

                for page in (1, 2, 3):
                    response = self.get({
                        'ordering': ordering, 'page': page, 'page_size': 10,
                    })

                    self.assertEqual(response.status_code, 200)
                    seen.extend(item['id'] for item in response.data['results'])

                self.assertEqual(len(seen), 25)
                self.assertEqual(len(set(seen)), 25)
                self.assertEqual(
                    seen,
                    sorted(seen, reverse=ordering.startswith('-')),
                )

    def test_ordering_combines_with_search_and_filters(self):
        self.make_issue(1, title='Login b', priority=Issue.Priority.LOW)
        self.make_issue(2, title='Login a', priority=Issue.Priority.HIGH)
        self.make_issue(3, title='Login c', priority=Issue.Priority.HIGH)
        self.make_issue(4, title='Other', priority=Issue.Priority.HIGH)

        self.assertEqual(
            self.ordered('-title', search='login', priority='HIGH'),
            ['SRCH-3', 'SRCH-2'],
        )


class IssuePaginationTests(IssueListAPITestCase):

    def setUp(self):
        super().setUp()

        for number in range(1, 26):
            self.make_issue(number, title=f'Login {number}')

        for number in range(26, 36):
            self.make_issue(number, title=f'Other {number}')

    def test_pagination_applies_after_search(self):
        first = self.get({'search': 'login', 'page_size': 10})
        last = self.get({'search': 'login', 'page_size': 10, 'page': 3})

        self.assertEqual(first.data['count'], 25)
        self.assertEqual(len(first.data['results']), 10)
        self.assertIsNone(first.data['previous'])
        self.assertIsNotNone(first.data['next'])

        self.assertEqual(last.data['count'], 25)
        self.assertEqual(len(last.data['results']), 5)
        self.assertIsNone(last.data['next'])
        self.assertIsNotNone(last.data['previous'])

    def test_pages_do_not_overlap_or_leak_non_matches(self):
        seen = []

        for page in (1, 2, 3):
            response = self.get({'search': 'login', 'page_size': 10, 'page': page})
            seen.extend(item['title'] for item in response.data['results'])

        self.assertEqual(len(seen), 25)
        self.assertEqual(len(set(seen)), 25)
        self.assertTrue(all(title.startswith('Login') for title in seen))

    def test_page_links_keep_the_search_and_filters(self):
        response = self.get({
            'search': 'login', 'ordering': 'title', 'page_size': 10,
        })

        self.assertIn('search=login', response.data['next'])
        self.assertIn('ordering=title', response.data['next'])
        self.assertIn('page_size=10', response.data['next'])

    def test_page_past_the_end_is_not_found(self):
        response = self.get({'search': 'login', 'page_size': 10, 'page': 4})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['code'], 'not_found')

    def test_page_size_stays_capped(self):
        response = self.get({'page_size': 500})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 35)
        self.assertEqual(len(response.data['results']), 35)

    def test_response_contract_is_unchanged(self):
        response = self.get({'search': 'login', 'page_size': 1})

        self.assertEqual(
            set(response.data), {'count', 'next', 'previous', 'results'},
        )
        self.assertEqual(
            set(response.data['results'][0]),
            set(IssueSerializer.Meta.fields),
        )

    def test_without_parameters_behaviour_is_unchanged(self):
        response = self.get()

        self.assertEqual(response.data['count'], 35)
        self.assertEqual(len(response.data['results']), 20)
        self.assertEqual(response.data['results'][0]['issue_key'], 'SRCH-35')


class IssueSearchAccessControlTests(IssueListAPITestCase):

    def setUp(self):
        super().setUp()

        self.make_issue(1, title='Login secret')

    def test_unauthenticated_request_is_rejected(self):
        self.client.force_authenticate(user=None)

        response = self.get({'search': 'login'})

        self.assertEqual(response.status_code, 401)

    def test_non_member_cannot_search_a_project(self):
        self.client.force_authenticate(user=self.outsider)

        response = self.get({'search': 'login'})

        self.assertEqual(response.status_code, 404)
        self.assertNotIn('results', response.data)

    def test_non_member_gets_the_same_answer_as_for_a_missing_project(self):
        self.client.force_authenticate(user=self.outsider)

        real = self.get({'search': 'login'})
        missing = self.client.get(
            '/api/v1/projects/999999/issues/', {'search': 'login'},
        )

        self.assertEqual(real.status_code, missing.status_code)
        self.assertEqual(real.data, missing.data)

    def test_invalid_parameters_do_not_reveal_a_project_to_non_members(self):
        self.client.force_authenticate(user=self.outsider)

        response = self.get({'status': 'INVALID'})

        self.assertEqual(response.status_code, 404)

    def test_member_cannot_search_a_project_they_do_not_belong_to(self):
        self.client.force_authenticate(user=self.member)

        response = self.get({'search': 'login'}, project=self.other_project)

        self.assertEqual(response.status_code, 404)

    def test_viewer_can_search(self):
        self.client.force_authenticate(user=self.viewer)

        response = self.get({'search': 'login'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.keys(response), ['SRCH-1'])

    def test_team_member_can_search(self):
        self.client.force_authenticate(user=self.member)

        self.assertEqual(self.get({'search': 'login'}).data['count'], 1)

    def test_archived_project_cannot_be_searched(self):
        Project.objects.filter(pk=self.project.pk).update(is_archived=True)

        response = self.get({'search': 'login'})

        self.assertEqual(response.status_code, 404)

    def test_removed_member_loses_access(self):
        ProjectMember.objects.filter(
            project=self.project, user=self.viewer,
        ).delete()
        self.client.force_authenticate(user=self.viewer)

        self.assertEqual(self.get({'search': 'login'}).status_code, 404)


class IssueSearchQueryCountTests(IssueListAPITestCase):

    def test_query_count_does_not_grow_with_the_number_of_results(self):
        def populate(start, count):
            for number in range(start, start + count):
                self.make_issue(
                    number,
                    title=f'Login {number}',
                    assignee=self.member,
                    priority=Issue.Priority.HIGH,
                )

        params = {'search': 'login', 'ordering': '-priority', 'status': 'TODO'}

        populate(1, 2)
        with CaptureQueriesContext(connection) as small:
            self.assertEqual(self.get(params).data['count'], 2)

        populate(3, 15)
        with CaptureQueriesContext(connection) as large:
            self.assertEqual(self.get(params).data['count'], 17)

        self.assertEqual(len(small), len(large))
