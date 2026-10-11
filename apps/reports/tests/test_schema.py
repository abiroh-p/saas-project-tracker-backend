from drf_spectacular.generators import SchemaGenerator

from ..testing import ReportsTestCase

BASE = '/api/v1/projects/{project_id}/reports/'
OPERATIONS = {
    'overview/': 'project_report_overview',
    'status-distribution/': 'project_report_status_distribution',
    'priority-distribution/': 'project_report_priority_distribution',
    'assignee-workload/': 'project_report_assignee_workload',
    'trends/': 'project_report_trends',
}


class ReportSchemaTests(ReportsTestCase):

    def setUp(self):
        super().setUp()
        self.schema = SchemaGenerator().get_schema(request=None, public=True)

    def test_every_report_endpoint_is_documented_as_get_only(self):
        for suffix, operation_id in OPERATIONS.items():
            with self.subTest(endpoint=suffix):
                path = self.schema['paths'][BASE + suffix]

                self.assertEqual(set(path) - {'parameters'}, {'get'})
                self.assertEqual(path['get']['operationId'], operation_id)

    def test_error_responses_are_documented(self):
        for suffix in OPERATIONS:
            with self.subTest(endpoint=suffix):
                responses = self.schema['paths'][BASE + suffix]['get'][
                    'responses'
                ]

                self.assertIn('200', responses)
                self.assertIn('401', responses)
                self.assertIn('404', responses)

    def test_trends_documents_its_query_parameters(self):
        operation = self.schema['paths'][BASE + 'trends/']['get']
        params = {p['name']: p for p in operation['parameters']}

        self.assertTrue(params['date_from']['required'])
        self.assertTrue(params['date_to']['required'])
        self.assertFalse(params['interval'].get('required', False))
        self.assertIn('400', operation['responses'])
