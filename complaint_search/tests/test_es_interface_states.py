from django.test import TestCase

import mock
from complaint_search.es_interface import states_agg
from complaint_search.tests.es_interface_test_helpers import (
    assertBodyEqual,
    load,
)
from elasticsearch7 import Elasticsearch


class EsInterfaceTest_States(TestCase):

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._extract_count")
    @mock.patch.object(Elasticsearch, 'search')
    @mock.patch.object(Elasticsearch, 'count')
    def test_states__valid(self, mock_count, mock_search, mock_extract):
        mock_count.return_value = {"count": 100}
        mock_extract.return_value = 100
        body = load('states_agg__valid')
        mock_search.return_value = {"hits": {
            "total": {"value": 100, "relation": "eq"}}
        }
        res = states_agg()
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(0, len(mock_search.call_args[0]))
        self.assertEqual(2, len(mock_search.call_args[1]))
        assertBodyEqual(body, mock_search.call_args_list[0][1]['body'])
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertEqual(res["hits"]["total"]["relation"], "eq")

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch.object(Elasticsearch, 'search')
    @mock.patch.object(Elasticsearch, 'count')
    def test_states_exclude__valid(self, mock_count, mock_search):
        body = load('states_agg__valid')
        mock_search.return_value = {"hits": {
            "total": {"value": 100, "relation": "eq"}}
        }
        res = states_agg(['zip_code'])
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(0, len(mock_search.call_args[0]))
        self.assertEqual(2, len(mock_search.call_args[1]))
        assertBodyEqual(body, mock_search.call_args_list[0][1]['body'])
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertEqual(res["hits"]["total"]["relation"], "eq")

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._extract_count")
    @mock.patch.object(Elasticsearch, 'search')
    def test_states_date_filters__valid(self, mock_search, mock_extract):
        params = {
            'date_received_min': '2020-01-01',
            'date_received_max': '2020-05-05',
            'company_received_min': '2020-01-01',
            'company_received_max': '2020-05-05',
            'state': ['VA'],
            'size': 0
        }
        mock_extract.return_value = 100

        body = load('states_date_filters__valid')

        mock_search.return_value = {"hits": {
            "total": {"value": 100, "relation": "eq"}}
        }
        res = states_agg(**params)
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(0, len(mock_search.call_args[0]))
        self.assertEqual(2, len(mock_search.call_args[1]))
        assertBodyEqual(body, mock_search.call_args_list[0][1]['body'])
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertEqual(res, mock_search.return_value)
