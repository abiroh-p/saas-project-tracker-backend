"""Search on GET /api/v1/projects/."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from .models import Project, ProjectMember

User = get_user_model()

URL = '/api/v1/projects/'


class ProjectSearchTestCase(APITestCase):
    """`alice` is authenticated; `bob` is a separate user with his own
    projects."""

    def setUp(self):
        self.alice = User.objects.create_user(
            username='alice', password='TestPassword123',
        )
        self.bob = User.objects.create_user(
            username='bob', password='TestPassword123',
        )

        self.client.force_authenticate(user=self.alice)

    def make_project(self, key, name, owner=None, **extra):
        owner = owner or self.alice
        project = Project.objects.create(
            key=key, name=name, created_by=owner, **extra,
        )
        ProjectMember.objects.create(
            project=project,
            user=owner,
            role=ProjectMember.Role.PROJECT_MANAGER,
        )

        return project

    def get(self, params=None):
        return self.client.get(URL, params or {})

    def keys(self, response):
        return [item['key'] for item in response.data['results']]


class ProjectSearchTests(ProjectSearchTestCase):

    def test_search_matches_name(self):
        self.make_project('TRKR', 'Issue Tracker')
        self.make_project('WEB', 'Website')

        response = self.get({'search': 'tracker'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.keys(response), ['TRKR'])

    def test_search_matches_key(self):
        self.make_project('TRKR', 'Alpha')
        self.make_project('WEB', 'Beta')

        self.assertEqual(self.keys(self.get({'search': 'TRKR'})), ['TRKR'])

    def test_search_matches_part_of_a_key(self):
        self.make_project('TRKR', 'Alpha')
        self.make_project('WEB', 'Beta')

        self.assertEqual(self.keys(self.get({'search': 'TRK'})), ['TRKR'])

    def test_search_is_case_insensitive_for_name_and_key(self):
        self.make_project('TRKR', 'Issue Tracker')

        for term in ('tracker', 'TRACKER', 'trkr', 'TrKr'):
            with self.subTest(term=term):
                self.assertEqual(self.keys(self.get({'search': term})), ['TRKR'])

    def test_search_matches_name_or_key(self):
        self.make_project('APP', 'Mobile client')
        self.make_project('MOB', 'Backend')
        self.make_project('WEB', 'Website')

        response = self.get({'search': 'mob'})

        self.assertEqual(sorted(self.keys(response)), ['APP', 'MOB'])

    def test_description_is_not_searched(self):
        self.make_project('DOCS', 'Docs', description='All about trackers')

        self.assertEqual(self.get({'search': 'trackers'}).data['count'], 0)

    def test_non_matching_term_returns_empty_page(self):
        self.make_project('TRKR', 'Issue Tracker')

        response = self.get({'search': 'zzz-no-match'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])
        self.assertIsNone(response.data['next'])
        self.assertIsNone(response.data['previous'])

    def test_search_term_is_trimmed(self):
        self.make_project('TRKR', 'Issue Tracker')

        self.assertEqual(self.keys(self.get({'search': '  tracker '})), ['TRKR'])

    def test_blank_search_is_ignored(self):
        self.make_project('AAA', 'One')
        self.make_project('BBB', 'Two')

        for term in ('', '   '):
            with self.subTest(term=term):
                response = self.get({'search': term})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['count'], 2)

    def test_percent_and_underscore_are_matched_literally(self):
        self.make_project('PCT', '100% done')
        self.make_project('SNK', 'snake_case')
        self.make_project('PLN', 'Plain')

        self.assertEqual(self.keys(self.get({'search': '%'})), ['PCT'])
        self.assertEqual(self.keys(self.get({'search': '_'})), ['SNK'])

    def test_sql_like_input_is_treated_as_text(self):
        self.make_project('SQL', "x'); DROP TABLE projects_project;--")
        self.make_project('PLN', 'Plain')

        response = self.get({'search': "'); DROP TABLE"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.keys(response), ['SQL'])
        self.assertEqual(Project.objects.count(), 2)

    def test_unicode_search(self):
        self.make_project('CAFE', 'Café redesign')

        self.assertEqual(self.keys(self.get({'search': 'CAFÉ'})), ['CAFE'])

    def test_search_keeps_newest_first_order(self):
        self.make_project('TRK1', 'Tracker one')
        self.make_project('TRK2', 'Tracker two')
        self.make_project('TRK3', 'Tracker three')

        self.assertEqual(
            self.keys(self.get({'search': 'tracker'})),
            ['TRK3', 'TRK2', 'TRK1'],
        )

    # -- validation -------------------------------------------------------

    def test_search_at_the_length_limit_is_accepted(self):
        self.assertEqual(self.get({'search': 'a' * 100}).status_code, 200)

    def test_search_over_the_length_limit_is_rejected(self):
        response = self.get({'search': 'a' * 101})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'bad_request')
        self.assertEqual(
            response.data['detail'],
            'Search term must be at most 100 characters.',
        )

    def test_search_with_nul_character_is_rejected_not_a_server_error(self):
        response = self.get({'search': 'abc\x00def'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'bad_request')
        self.assertEqual(response.data['detail'], 'Invalid search term.')

    def test_errors_use_the_standard_error_shape(self):
        response = self.get({'search': 'a' * 101})

        self.assertEqual(set(response.data), {'detail', 'code'})

    def test_unknown_query_parameters_are_ignored(self):
        self.make_project('TRKR', 'Issue Tracker')

        response = self.get({'colour': 'red', 'is_archived': 'true'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)


class ProjectSearchAccessControlTests(ProjectSearchTestCase):

    def test_unauthenticated_request_is_rejected(self):
        self.client.force_authenticate(user=None)

        self.assertEqual(self.get({'search': 'tracker'}).status_code, 401)

    def test_search_only_returns_projects_the_user_belongs_to(self):
        self.make_project('MINE', 'Tracker public')
        self.make_project('SECRET', 'Tracker secret', owner=self.bob)

        response = self.get({'search': 'tracker'})

        self.assertEqual(self.keys(response), ['MINE'])

    def test_other_users_projects_cannot_be_found_by_name_or_key(self):
        self.make_project('MINE', 'Mine')
        self.make_project('SECRET', 'Hidden roadmap', owner=self.bob)

        for term in ('SECRET', 'secret', 'hidden roadmap', 'roadmap'):
            with self.subTest(term=term):
                self.assertEqual(self.get({'search': term}).data['count'], 0)

    def test_search_does_not_change_the_total_visible_to_the_user(self):
        self.make_project('MINE', 'Mine')
        self.make_project('THEIRS', 'Theirs', owner=self.bob)

        self.assertEqual(self.get().data['count'], 1)
        self.assertEqual(self.get({'search': 'e'}).data['count'], 1)

    def test_shared_project_is_found_by_every_role(self):
        project = self.make_project('SHARED', 'Shared tracker', owner=self.bob)
        ProjectMember.objects.create(
            project=project,
            user=self.alice,
            role=ProjectMember.Role.VIEWER,
        )

        self.assertEqual(self.keys(self.get({'search': 'shared'})), ['SHARED'])

    def test_archived_projects_stay_excluded(self):
        self.make_project('LIVE', 'Tracker live')
        self.make_project('OLD', 'Tracker old', is_archived=True)

        self.assertEqual(self.keys(self.get({'search': 'tracker'})), ['LIVE'])

    def test_removed_member_no_longer_finds_the_project(self):
        project = self.make_project('SHARED', 'Shared tracker', owner=self.bob)
        membership = ProjectMember.objects.create(
            project=project,
            user=self.alice,
            role=ProjectMember.Role.TEAM_MEMBER,
        )
        self.assertEqual(self.get({'search': 'shared'}).data['count'], 1)

        membership.delete()

        self.assertEqual(self.get({'search': 'shared'}).data['count'], 0)

    def test_project_with_many_members_is_returned_once(self):
        project = self.make_project('TEAM', 'Tracker team')

        for index in range(3):
            user = User.objects.create_user(
                username=f'teammate{index}', password='TestPassword123',
            )
            ProjectMember.objects.create(
                project=project,
                user=user,
                role=ProjectMember.Role.TEAM_MEMBER,
            )

        response = self.get({'search': 'tracker'})

        self.assertEqual(response.data['count'], 1)
        self.assertEqual(len(response.data['results']), 1)


class ProjectSearchPaginationTests(ProjectSearchTestCase):

    def setUp(self):
        super().setUp()

        for number in range(1, 26):
            self.make_project(f'TRK{number}', f'Tracker {number}')

        for number in range(1, 11):
            self.make_project(f'OTH{number}', f'Other {number}')

    def test_pagination_applies_after_search(self):
        first = self.get({'search': 'tracker', 'page_size': 10})
        last = self.get({'search': 'tracker', 'page_size': 10, 'page': 3})

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
            response = self.get({
                'search': 'tracker', 'page_size': 10, 'page': page,
            })
            seen.extend(self.keys(response))

        self.assertEqual(len(seen), 25)
        self.assertEqual(len(set(seen)), 25)
        self.assertTrue(all(key.startswith('TRK') for key in seen))

    def test_page_links_keep_the_search(self):
        response = self.get({'search': 'tracker', 'page_size': 10})

        self.assertIn('search=tracker', response.data['next'])
        self.assertIn('page_size=10', response.data['next'])

    def test_page_past_the_end_is_not_found(self):
        response = self.get({'search': 'tracker', 'page_size': 10, 'page': 4})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['code'], 'not_found')

    def test_page_size_stays_capped(self):
        response = self.get({'page_size': 500})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 35)
        self.assertEqual(len(response.data['results']), 35)

    def test_response_contract_is_unchanged(self):
        searched = self.get({'search': 'tracker', 'page_size': 1})
        plain = self.get({'page_size': 1})

        self.assertEqual(
            set(searched.data), {'count', 'next', 'previous', 'results'},
        )
        self.assertEqual(
            set(searched.data['results'][0]),
            set(plain.data['results'][0]),
        )

    def test_without_parameters_behaviour_is_unchanged(self):
        response = self.get()

        self.assertEqual(response.data['count'], 35)
        self.assertEqual(len(response.data['results']), 20)
        self.assertEqual(response.data['results'][0]['key'], 'OTH10')


class ProjectSearchQueryCountTests(ProjectSearchTestCase):

    def test_query_count_does_not_grow_with_the_number_of_results(self):
        for number in range(1, 3):
            self.make_project(f'AA{number}', f'Tracker {number}')

        with CaptureQueriesContext(connection) as small:
            self.assertEqual(self.get({'search': 'tracker'}).data['count'], 2)

        for number in range(3, 15):
            self.make_project(f'AA{number}', f'Tracker {number}')

        with CaptureQueriesContext(connection) as large:
            self.assertEqual(self.get({'search': 'tracker'}).data['count'], 14)

        self.assertEqual(len(small), len(large))
