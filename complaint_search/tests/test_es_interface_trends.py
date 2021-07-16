from django.test import TestCase

import mock
from complaint_search.es_interface import trends
from complaint_search.tests.es_interface_test_helpers import load
from elasticsearch7 import Elasticsearch


class EsInterfaceTest_Trends(TestCase):

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._COMPLAINT_DOC_TYPE",
                "DOC_TYPE")
    @mock.patch.object(Elasticsearch, 'search')
    def test_trends_default_params__valid(self, mock_search):
        trends_params = {
            'lens': 'overview',
            'trend_interval': 'year'
        }
        body = load("trends_default_params__valid")
        mock_search.return_value = body

        res = trends(**trends_params)
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertEqual(body, res)

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._COMPLAINT_DOC_TYPE",
                "DOC_TYPE")
    @mock.patch.object(Elasticsearch, 'search')
    def test_trends_sub_lens_product__valid(self, mock_search):
        trends_params = {
            'lens': 'product',
            'trend_interval': 'year',
            'sub_lens': 'sub_product',
            'trend_depth': 5,
            'sub_lens_depth': 5
        }
        body = load("trends_sub_lens_product__valid")
        mock_search.return_value = body

        res = trends(**trends_params)
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertEqual(body, res)

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._COMPLAINT_DOC_TYPE",
                "DOC_TYPE")
    @mock.patch.object(Elasticsearch, 'search')
    def test_trends_exclude_and_date_filters__valid(self, mock_search):
        trends_params = {
            'lens': 'overview',
            'trend_interval': 'year',
            'date_received_min': '2019-01-01',
            'date_received_max': '2020-01-01',
            'company_received_min': '2019-01-01',
            'company_received_max': '2020-01-01',
        }
        body = load("trends_exclude_and_date_filters__valid")
        mock_search.return_value = body

        res = trends(agg_exclude=['zip_code'], **trends_params)
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertEqual(body, res)

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._COMPLAINT_DOC_TYPE",
                "DOC_TYPE")
    @mock.patch.object(Elasticsearch, 'search')
    def test_trends_filter__valid(self, mock_search):
        trends_params = {
            'lens': 'product',
            'trend_interval': 'year',
            'sub_lens': 'sub_product',
            'trend_depth': 5,
            'sub_lens_depth': 5,
            'issue': 'Incorrect information on your report'
        }
        body = load("trends_filter__valid")
        mock_search.return_value = body

        res = trends(**trends_params)
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertEqual(body, res)

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._COMPLAINT_DOC_TYPE",
                "DOC_TYPE")
    @mock.patch.object(Elasticsearch, 'search')
    def test_trends_top_self_filter__valid(self, mock_search):
        trends_params = {
            'lens': 'overview',
            'trend_interval': 'year',
            'trend_depth': 5,
            'issue': 'Incorrect information on your report'
        }
        body = load("trends_filter__valid")
        mock_search.return_value = body

        res = trends(**trends_params)
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertEqual(body, res)
        self.assertTrue('company' not in res['aggregations'])

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._COMPLAINT_DOC_TYPE",
                "DOC_TYPE")
    @mock.patch.object(Elasticsearch, 'search')
    def test_trends_company_filter__valid(self, mock_search):
        default_exclude = ['company', 'zip_code']
        trends_params = {
            'lens': 'overview',
            'trend_interval': 'year',
            'company': 'EQUIFAX, INC.'
        }

        body = load("trends_company_filter__valid")
        mock_search.return_value = body

        res = trends(default_exclude, **trends_params)
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertTrue('company' in res['aggregations'])

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._COMPLAINT_DOC_TYPE",
                "DOC_TYPE")
    @mock.patch.object(Elasticsearch, 'search')
    def test_trends_issue_focus__valid(self, mock_search):
        default_exclude = ['company', 'zip_code']
        trends_params = {
            'lens': 'issue',
            'trend_interval': 'year',
            'trend_depth': 5,
            'focus': 'Incorrect information on your report'
        }

        body = load("trends_issue_focus__valid")
        mock_search.return_value = body

        res = trends(default_exclude, **trends_params)
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertFalse('company' in res['aggregations'])
        self.assertEqual(len(res['aggregations']['issue']['issue']['buckets']),
                         1)

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._COMPLAINT_DOC_TYPE",
                "DOC_TYPE")
    @mock.patch.object(Elasticsearch, 'search')
    def test_trends_issue_focus_company_filter__valid(self, mock_search):
        default_exclude = ['company', 'zip_code']
        trends_params = {
            'lens': 'issue',
            'trend_interval': 'year',
            'trend_depth': 5,
            'focus': 'Incorrect information on your report',
            'company': 'EQUIFAX, INC.'
        }

        body = load("trends_issue_focus_company_filter__valid")
        mock_search.return_value = body

        res = trends(default_exclude, **trends_params)
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertTrue('company' in res['aggregations'])
        self.assertEqual(len(res['aggregations']['issue']['issue']['buckets']),
                         1)
