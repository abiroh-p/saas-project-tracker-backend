from django.http import QueryDict
from django.test import SimpleTestCase

from .query_params import SEARCH_MAX_LENGTH, QueryParamError, get_search_term


class GetSearchTermTests(SimpleTestCase):

    def term(self, query_string):
        return get_search_term(QueryDict(query_string))

    def test_missing_search_returns_none(self):
        self.assertIsNone(self.term(''))
        self.assertIsNone(self.term('page=2'))

    def test_blank_search_returns_none(self):
        self.assertIsNone(self.term('search='))
        self.assertIsNone(self.term('search=%20%20'))
        self.assertIsNone(self.term('search=%09%0A'))

    def test_term_is_stripped(self):
        self.assertEqual(self.term('search=%20login%20'), 'login')

    def test_inner_whitespace_is_kept(self):
        self.assertEqual(self.term('search=login%20page'), 'login page')

    def test_case_is_preserved(self):
        self.assertEqual(self.term('search=LoGiN'), 'LoGiN')

    def test_plain_dict_is_accepted(self):
        self.assertEqual(get_search_term({'search': 'login'}), 'login')

    def test_term_at_the_limit_is_accepted(self):
        term = 'a' * SEARCH_MAX_LENGTH

        self.assertEqual(self.term(f'search={term}'), term)

    def test_term_over_the_limit_is_rejected(self):
        with self.assertRaisesMessage(
            QueryParamError, 'Search term must be at most 100 characters.',
        ):
            self.term('search=' + 'a' * (SEARCH_MAX_LENGTH + 1))

    def test_limit_applies_after_trimming(self):
        padded = '%20' * 10 + 'a' * SEARCH_MAX_LENGTH + '%20' * 10

        self.assertEqual(
            self.term(f'search={padded}'), 'a' * SEARCH_MAX_LENGTH,
        )

    def test_nul_character_is_rejected(self):
        for query_string in ('search=a%00b', 'search=%00'):
            with self.subTest(query_string=query_string):
                with self.assertRaisesMessage(
                    QueryParamError, 'Invalid search term.',
                ):
                    self.term(query_string)

    def test_repeated_search_uses_the_last_value(self):
        self.assertEqual(self.term('search=first&search=second'), 'second')

    def test_percent_and_underscore_are_left_alone(self):
        # Escaping for LIKE is the ORM's job; the helper must not alter them.
        self.assertEqual(self.term('search=100%25_x'), '100%_x')
