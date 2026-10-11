from datetime import date

from rest_framework import status

from apps.reports.params import MAX_REPORT_DATE, MIN_REPORT_DATE

from .test_trends import TrendsTestCase


class TrendsDateBoundsTests(TrendsTestCase):
    """Dates the range arithmetic cannot handle must be a 400, never a 500."""

    def assert_bad_request(self, **params):
        response = self.get(**params)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'bad_request')

        return response

    def test_the_largest_date_is_rejected_instead_of_overflowing(self):
        # Adding a day to 9999-12-31 used to raise OverflowError (a 500).
        self.assert_bad_request(date_from='9999-12-31', date_to='9999-12-31')
        self.assert_bad_request(date_from='9999-12-01', date_to='9999-12-31')
        self.assert_bad_request(
            date_from='9999-12-01', date_to='9999-12-31', interval='week',
        )

    def test_dates_after_the_upper_bound_are_rejected(self):
        self.assert_bad_request(date_from='2100-12-31', date_to='2101-01-01')
        self.assert_bad_request(date_from='2101-01-01', date_to='2101-01-02')

    def test_dates_before_the_lower_bound_are_rejected(self):
        self.assert_bad_request(date_from='1969-12-31', date_to='1970-01-02')
        self.assert_bad_request(date_from='0001-01-01', date_to='0001-01-31')

    def test_the_error_names_the_parameter_and_the_allowed_window(self):
        response = self.assert_bad_request(
            date_from='2026-01-01', date_to='2101-01-01',
        )

        self.assertIn('date_to', response.data['detail'])
        self.assertIn('1970-01-01', response.data['detail'])
        self.assertIn('2100-12-31', response.data['detail'])

    def test_the_bounds_themselves_are_accepted(self):
        lower = self.get(date_from='1970-01-01', date_to='1970-01-03')
        upper = self.get(date_from='2100-12-29', date_to='2100-12-31')

        self.assertEqual(lower.status_code, status.HTTP_200_OK)
        self.assertEqual(len(lower.data['results']), 3)
        self.assertEqual(upper.status_code, status.HTTP_200_OK)
        self.assertEqual(len(upper.data['results']), 3)
        self.assertEqual(MIN_REPORT_DATE, date(1970, 1, 1))
        self.assertEqual(MAX_REPORT_DATE, date(2100, 12, 31))

    def test_weekly_trends_work_at_both_bounds(self):
        # 1970-01-01 is a Thursday, so its week is labelled by Monday
        # 1969-12-29, before the lower bound; counts still cover only the
        # requested days.
        lower = self.get(
            date_from='1970-01-01', date_to='1970-01-12', interval='week',
        )
        upper = self.get(
            date_from='2100-12-20', date_to='2100-12-31', interval='week',
        )

        self.assertEqual(lower.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row['period'] for row in lower.data['results']],
            [date(1969, 12, 29), date(1970, 1, 5), date(1970, 1, 12)],
        )
        self.assertEqual(upper.status_code, status.HTTP_200_OK)
        self.assertEqual(upper.data['results'][-1]['period'], date(2100, 12, 27))

    def test_digits_from_other_scripts_are_rejected(self):
        for bad in ('２０２６-01-01', '٢٠٢٦-٠١-٠١', '2026-०१-01'):
            with self.subTest(value=bad):
                self.assert_bad_request(date_from=bad, date_to='2026-01-31')
                self.assert_bad_request(date_from='2026-01-01', date_to=bad)

    def test_ordinary_ranges_still_work(self):
        response = self.get(date_from='2026-10-01', date_to='2026-10-05')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 5)
