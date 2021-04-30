import copy
from datetime import datetime

from django.http import StreamingHttpResponse
from django.test import TestCase

import mock
from complaint_search.es_builders import AggregationBuilder, SearchBuilder
from complaint_search.es_interface import (
    _extract_total,
    _get_meta,
    document,
    filter_suggest,
    search,
    suggest,
)
from complaint_search.export import ElasticSearchExporter
from complaint_search.tests.es_interface_test_helpers import (
    assertBodyEqual,
    load,
)
from elasticsearch7 import Elasticsearch
from nose_parameterized import parameterized


class EsInterfaceTest_Search(TestCase):
    def setUp(self):
        self.maxDiff = None

    # -------------------------------------------------------------------------
    # Helper Attributes
    # -------------------------------------------------------------------------
    MOCK_SEARCH_SIDE_EFFECT = [
        {
            "search": "OK",
            "_scroll_id": "This_is_a_scroll_id",
            "hits": {
                "hits": [0, 1, 2, 3],
                "total": {
                    "value": 4,
                    "relation": "eq"
                },
            }
        },
        {
            "aggregations": {
                "max_date": {
                    "value_as_string": "2017-01-01"
                },
                "max_indexed_date": {
                    "value_as_string": "2017-01-02"
                },
                "max_narratives": {
                    "max_date": {
                        "value": 1483400000.0
                        # 150970000.0 for November 3rd 2017
                    }
                }
            }
        }
    ]

    MOCK_COUNT_RETURN_VALUE = {"count": 100}

    MOCK_SEARCH_RESULT = {
        'search': 'OK',
        "_scroll_id": "This_is_a_scroll_id",
        "hits": {
            "hits": [0, 1, 2, 3],
            "total": 4
        },
        '_meta': {
            'total_record_count': 100,
            'last_indexed': '2017-01-02',
            'last_updated': '2017-01-01',
            'license': 'CC0',
            'is_data_stale': False,
            'is_narrative_stale': False,
            'has_data_issue': False,
        }
    }

    MOCK_SCROLL_SIDE_EFFECT = [
        {
            "hits": {
                "hits": [4, 5, 6, 7]
            }
        },
        {
            "hits": {
                "hits": [8, 9, 10, 11]
            }
        }
    ]

    DEFAULT_EXCLUDE = ['company', 'zip_code']

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def request_test(self, expected, agg_exclude=['company', 'zip_code'],
                     **kwargs):
        body = load(expected)

        with mock.patch(
            "complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX"
        ), mock.patch(
            "complaint_search.es_interface._get_meta"
        ) as mock_get_meta, mock.patch.object(
            Elasticsearch, 'search'
        ) as mock_search, mock.patch.object(
            Elasticsearch, 'count'
        ) as mock_count, mock.patch.object(
            Elasticsearch, 'scroll'
        ) as mock_scroll:
            mock_search.side_effect = copy.deepcopy(
                self.MOCK_SEARCH_SIDE_EFFECT)
            mock_count.return_value = self.MOCK_COUNT_RETURN_VALUE
            mock_get_meta.return_value = copy.deepcopy(
                self.MOCK_SEARCH_RESULT["_meta"])
            mock_scroll.return_value = self.MOCK_SEARCH_SIDE_EFFECT[0]

            res = search(agg_exclude, **kwargs)

        self.assertEqual(1, len(mock_search.call_args_list))
        self.assertEqual(2, len(mock_search.call_args_list[0]))
        self.assertEqual(0, len(mock_search.call_args_list[0][0]))
        self.assertEqual(3, len(mock_search.call_args_list[0][1]))

        assertBodyEqual(body, mock_search.call_args_list[0][1]['body'])
        self.assertEqual(mock_search.call_args_list[0][1]['index'], 'INDEX')
        mock_scroll.assert_not_called()
        self.assertDictEqual(self.MOCK_SEARCH_RESULT, res)

    # -------------------------------------------------------------------------
    # Tests
    # -------------------------------------------------------------------------

    def test__extract_total_missing(self):
        fixture = {'hits': {}}
        actual = _extract_total(fixture)
        self.assertEqual(None, actual)

    def test__extract_from_aggs_good(self):
        fixture = {
            'hits': {'total': {'value': 10000, 'relation': 'gte'}},
            'aggregations': {'has_narrative': {'doc_count': 99999}}
        }
        actual = _extract_total(fixture)
        self.assertEqual(99999, actual)

    def test__extract_from_aggs_failed(self):
        fixture = {
            'hits': {'total': {'value': 10000, 'relation': 'gte'}}
        }
        actual = _extract_total(fixture)
        self.assertEqual(None, actual)

    @mock.patch("complaint_search.es_interface._get_now")
    @mock.patch.object(Elasticsearch, 'search')
    @mock.patch.object(Elasticsearch, 'count')
    def test_get_meta(self, mock_count, mock_search, mock_now):
        mock_search.return_value = self.MOCK_SEARCH_SIDE_EFFECT[1]
        mock_count.return_value = self.MOCK_COUNT_RETURN_VALUE
        mock_now.return_value = datetime(2017, 1, 3)

        res = _get_meta()
        self.assertDictEqual(self.MOCK_SEARCH_RESULT["_meta"], res)

    @mock.patch("complaint_search.es_interface._get_now")
    @mock.patch.object(Elasticsearch, 'search')
    @mock.patch.object(Elasticsearch, 'count')
    def test_get_meta_data_stale(self, mock_count, mock_search, mock_now):
        mock_search.return_value = self.MOCK_SEARCH_SIDE_EFFECT[1]
        mock_count.return_value = self.MOCK_COUNT_RETURN_VALUE
        mock_now.return_value = datetime(2017, 11, 1)

        res = _get_meta()
        exp_res = copy.deepcopy(self.MOCK_SEARCH_RESULT["_meta"])
        exp_res['is_data_stale'] = True
        exp_res['is_narrative_stale'] = True
        self.assertDictEqual(exp_res, res)

    @mock.patch("complaint_search.es_interface._get_now")
    @mock.patch("complaint_search.es_interface.flag_enabled")
    @mock.patch.object(Elasticsearch, 'search')
    @mock.patch.object(Elasticsearch, 'count')
    def test_get_meta_data_issue(
            self, mock_count, mock_search, mock_flag_enabled, mock_now):
        mock_search.return_value = self.MOCK_SEARCH_SIDE_EFFECT[1]
        mock_count.return_value = self.MOCK_COUNT_RETURN_VALUE
        mock_now.return_value = datetime(2017, 1, 1)
        mock_flag_enabled.return_value = True

        res = _get_meta()
        exp_res = copy.deepcopy(self.MOCK_SEARCH_RESULT["_meta"])
        exp_res['has_data_issue'] = True
        self.assertDictEqual(exp_res, res)

    @mock.patch('requests.get', ok=True, content="RGET_OK")
    def test_search_no_param__valid(self, mock_rget):
        self.request_test("search_no_param__valid")
        mock_rget.assert_not_called()

    @mock.patch('requests.get', ok=True, content="RGET_OK")
    def test_search_agg_exclude__valid(self, mock_rget):
        self.request_test("search_agg_exclude__valid",
                          agg_exclude=['zip_code'])
        mock_rget.assert_not_called()

    @parameterized.expand([
        ['csv'],
        ['json']
    ])
    @mock.patch.object(ElasticSearchExporter, 'export_csv')
    @mock.patch.object(ElasticSearchExporter, 'export_json')
    @mock.patch.object(Elasticsearch, 'search')
    @mock.patch('elasticsearch7.helpers.scan')
    def test_search_with_format__valid(
        self,
        export_type,
        mock_es_helper,
        mock_search,
        mock_exporter_json,
        mock_exporter_csv
    ):
        mock_search_side_effect = copy.deepcopy(self.MOCK_SEARCH_SIDE_EFFECT)
        mock_search_side_effect[0]['hits']['total'] = 4
        mock_search.side_effect = mock_search_side_effect

        mock_exporter_csv.return_value = StreamingHttpResponse()
        mock_exporter_json.return_value = StreamingHttpResponse()

        res = search(format=export_type)

        self.assertIsInstance(res, StreamingHttpResponse)
        self.assertEqual(1, mock_es_helper.call_count)
        if export_type == 'csv':
            self.assertEqual(1, mock_exporter_csv.call_count)
            self.assertEqual(0, mock_exporter_json.call_count)
        else:
            self.assertEqual(1, mock_search.call_count)
            self.assertEqual(1, mock_exporter_json.call_count)
            self.assertEqual(0, mock_exporter_csv.call_count)

    @mock.patch.object(Elasticsearch, 'search')
    @mock.patch('requests.get', ok=True, content="RGET_OK")
    def test_search_with_format__invalid(self, mock_rget, mock_search):
        mock_search.return_value = 'OK'
        res = search(format="pdf")
        self.assertEqual(res, {})
        mock_search.assert_not_called()
        mock_rget.assert_not_called()

    def test_search_with_size__valid(self):
        self.request_test("search_with_size__valid", size=40)

    def test_search_with_size_corrected__valid(self):
        self.request_test("search_with_size_corrected__valid", size=5000)

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._get_meta")
    @mock.patch.object(Elasticsearch, 'search')
    @mock.patch.object(Elasticsearch, 'count')
    @mock.patch.object(Elasticsearch, 'scroll')
    def test_search_with_frm__valid(
        self, mock_scroll, mock_count, mock_search, mock_get_meta
    ):
        mock_search.side_effect = copy.deepcopy(self.MOCK_SEARCH_SIDE_EFFECT)
        mock_count.return_value = self.MOCK_COUNT_RETURN_VALUE
        mock_get_meta.return_value = copy.deepcopy(
            self.MOCK_SEARCH_RESULT["_meta"])
        mock_scroll.side_effect = copy.deepcopy(self.MOCK_SCROLL_SIDE_EFFECT)
        body = load("search_with_frm__valid")
        res = search(self.DEFAULT_EXCLUDE, frm=20)
        self.assertEqual(1, len(mock_search.call_args_list))
        self.assertEqual(2, len(mock_search.call_args_list[0]))
        self.assertEqual(0, len(mock_search.call_args_list[0][0]))
        self.assertEqual(3, len(mock_search.call_args_list[0][1]))
        self.assertDictEqual(mock_search.call_args_list[0][1]['body'], body)
        self.assertEqual(mock_search.call_args_list[0][1]['index'], 'INDEX')
        self.assertEqual(mock_scroll.call_count, 2)
        search_result = copy.deepcopy(self.MOCK_SEARCH_RESULT)
        search_result['hits'][
            'hits'] = self.MOCK_SCROLL_SIDE_EFFECT[1]['hits']['hits']
        self.assertDictEqual(search_result, res)

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch("complaint_search.es_interface._get_meta")
    @mock.patch.object(Elasticsearch, 'search')
    @mock.patch.object(Elasticsearch, 'count')
    @mock.patch.object(Elasticsearch, 'scroll')
    def test_search_with_sort__valid(
        self, mock_scroll, mock_count, mock_search, mock_get_meta
    ):

        sort_fields = [
            ("relevance_desc", "_score", "desc"),
            ("relevance_asc", "_score", "asc"),
            ("created_date_desc", "date_received", "desc"),
            ("created_date_asc", "date_received", "asc")
        ]

        # 4 is the length of sort_field
        # mock_search.side_effect = []
        # mock_count.side_effect = []
        # for i in range(4):

        mock_search.side_effect = [
            copy.deepcopy(self.MOCK_SEARCH_SIDE_EFFECT[0])
            for i in range(4)
        ]

        mock_count.side_effect = [
            copy.deepcopy(self.MOCK_COUNT_RETURN_VALUE)
            for i in range(4)
        ]
        mock_get_meta.side_effect = [
            copy.deepcopy(self.MOCK_SEARCH_RESULT["_meta"])
            for i in range(4)
        ]
        body = load("search_with_sort__valid")

        for s in sort_fields:
            res = search(self.DEFAULT_EXCLUDE, sort=s[0])
            body["sort"] = [{s[1]: {"order": s[2]}}]
            mock_search.assert_any_call(
                body=body,
                index="INDEX",
                scroll="10m"
            )
            self.assertEqual(self.MOCK_SEARCH_RESULT, res)

        mock_scroll.assert_not_called()
        self.assertEqual(4, mock_search.call_count)

    def test_search_with_search_term_field_all(self):
        self.request_test("search_with_search_term_field_all",
                          search_term="test term", field="all")

    def test_search_with_search_term_field__all(self):
        self.request_test("search_with_search_term_field_all",
                          search_term="test term", field="_all")

    def test_search_with_search_term_match__valid(self):
        self.request_test("search_with_search_term_match__valid",
                          search_term="test term")

    def test_search_with_search_term_qsq_and__valid(self):
        self.request_test("search_with_search_term_qsq_and__valid",
                          search_term="test AND term")

    def test_search_with_search_term_qsq_or__valid(self):
        self.request_test("search_with_search_term_qsq_or__valid",
                          search_term="test OR term")

    def test_search_with_search_term_qsq_not__valid(self):
        self.request_test("search_with_search_term_qsq_not__valid",
                          search_term="test NOT term")

    def test_search_with_search_term_qsq_to__valid(self):
        self.request_test("search_with_search_term_qsq_to__valid",
                          search_term="term TO test")

    def test_search_with_date_received_min__valid(self):
        self.request_test("search_with_date_received_min__valid",
                          date_received_min="2014-04-14")

    def test_search_with_date_received_max__valid(self):
        self.request_test("search_with_date_received_max__valid",
                          date_received_max="2017-04-14")

    def test_search_with_company_received_min__valid(self):
        self.request_test("search_with_company_received_min__valid",
                          company_received_min="2014-04-14")

    def test_search_with_company_received_max__valid(self):
        self.request_test("search_with_company_received_max__valid",
                          company_received_max="2017-04-14")

    def test_search_with_company__valid(self):
        self.request_test("search_with_company__valid",
                          company=["Bank 1", "Second Bank"])

    def test_search_with_not_company__valid(self):
        self.request_test("search_with_not_company__valid",
                          not_company=["EQUIFAX, INC."])

    def test_search_with_company_agg_exclude__valid(self):
        self.request_test("search_with_company_agg_exclude__valid",
                          agg_exclude=['company'],
                          company=["Bank 1", "Second Bank"])

    def test_search_with_product__valid(self):
        self.request_test(
            "search_with_product__valid",
            agg_exclude=[u"zip_code", u"company"],
            product=["Payday loan", u"Mortgage\u2022FHA mortgage"]
        )

    def test_search_with_not_product__valid(self):
        self.request_test(
            "search_with_not_product__valid",
            not_product=["Credit reporting, credit repair services, or "
                         "other personal consumer reports",
                         "Mortgage\u2022FHA mortgage"]
        )

    def test_search_with_issue__valid(self):
        self.request_test(
            "search_with_issue__valid",
            agg_exclude=[u"zip_code", u"company"],
            issue=[u"Communication tactics\u2022Frequent or repeated calls",
                   "Loan servicing, payments, escrow account"]
        )

    def test_search_with_not_issue__valid(self):
        self.request_test(
            "search_with_not_issue__valid",
            not_issue=["Incorrect information on your report"]
        )

    def test_search_with_two_not__valid(self):
        self.request_test(
            "search_with_two_not__valid",
            not_issue=["Incorrect information on your report"],
            not_product=["Credit reporting, credit repair services, or "
                         "other personal consumer reports"]
        )

    def test_search_with_state__valid(self):
        self.request_test("search_with_state__valid", state=["CA", "VA", "OR"])

    def test_search_with_zip_code__valid(self):
        self.request_test("search_with_zip_code__valid",
                          zip_code=["12345", "23435", "03433"])

    def test_search_with_zip_code_agg_exclude__valid(self):
        self.request_test(
            "search_with_zip_code_agg_exclude__valid",
            agg_exclude=['zip_code'],
            zip_code=["12345", "23435", "03433"]
        )

    def test_search_with_timely__valid(self):
        self.request_test("search_with_timely__valid", timely=["Yes", "No"])

    def test_search_with_company_response__valid(self):
        self.request_test(
            "search_with_company_response__valid",
            company_response=["Closed", "Closed with non-monetary relief"]
        )

    def test_search_with_company_public_response__valid(self):
        self.request_test(
            "search_with_company_public_response__valid",
            company_public_response=[
                "Company chooses not to provide a public response",
                "Company believes it acted appropriately as authorized by "
                "contract or law"
            ])

    def test_search_with_consumer_consent_provided__valid(self):
        self.request_test(
            "search_with_consumer_consent_provided__valid",
            consumer_consent_provided=["Consent provided"]
        )

    def test_search_with_submitted_via__valid(self):
        self.request_test("search_with_submitted_via__valid",
                          submitted_via=["Web"])

    def test_search_with_tags__valid(self):
        self.request_test("search_with_tags__valid",
                          tags=["Older American", "Servicemember"])

    def test_search_with_has_narrative__valid(self):
        self.request_test("search_with_has_narrative__valid",
                          has_narrative=["true"])

    @mock.patch('requests.get', ok=True, content="RGET_OK")
    def test_search_no_highlight__valid(self, mock_rget):
        self.request_test("search_no_highlight__valid", no_highlight=True)
        mock_rget.assert_not_called()


class EsInterfaceTest_Suggest(TestCase):
    def setUp(self):
        self.fixture_response = {
            "suggest": {
                "sgg": [
                    {
                        'options': [
                            {
                                "text": "test 1",
                                "score": 1.0
                            },
                            {
                                "text": "test 2",
                                "score": 1.0
                            }
                        ]
                    }
                ]
            }
        }
        self.fixture_request = {
            "_source": False,
            "suggest": {
                "sgg": {
                    "completion": {
                        "field": "typeahead_dropdown",
                        "skip_duplicates": True,
                        "size": 6
                    },
                    "text": "Loan"
                }
            }
        }

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch.object(Elasticsearch, 'search')
    def test_suggest_with_no_param__valid(self, mock_suggest):
        mock_suggest.return_value = self.fixture_response
        res = suggest()
        mock_suggest.assert_not_called()
        self.assertEqual([], res)

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch.object(Elasticsearch, 'search')
    def test_suggest_with_text__valid(self, mock_suggest):
        mock_suggest.return_value = self.fixture_response
        self.fixture_request['suggest']['sgg']['text'] = 'Mortgage'

        res = suggest(text="Mortgage")
        self.assertEqual(len(mock_suggest.call_args), 2)
        self.assertEqual(0, len(mock_suggest.call_args[0]))
        self.assertEqual(2, len(mock_suggest.call_args[1]))
        self.assertDictEqual(mock_suggest.call_args[1]['body'],
                             self.fixture_request)
        self.assertEqual(mock_suggest.call_args[1]['index'], 'INDEX')
        self.assertEqual(['test 1', 'test 2'], res)

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch.object(Elasticsearch, 'search')
    def test_suggest_with_size__valid(self, mock_suggest):
        mock_suggest.return_value = self.fixture_response
        self.fixture_request['suggest']['sgg']['completion']['size'] = 10
        res = suggest(text="Loan", size=10)
        self.assertEqual(len(mock_suggest.call_args), 2)
        self.assertEqual(0, len(mock_suggest.call_args[0]))
        self.assertEqual(2, len(mock_suggest.call_args[1]))
        self.assertDictEqual(mock_suggest.call_args[1]['body'],
                             self.fixture_request)
        self.assertEqual(mock_suggest.call_args[1]['index'], 'INDEX')
        self.assertEqual(['test 1', 'test 2'], res)


class EsInterfaceTest_FilterSuggest(TestCase):

    def setUp(self):
        self.body = {'foo': 'bar'}
        self.oneAgg = {
            'filter': {
                'bool': {
                    'must': []
                }
            }
        }
        self.result = {
            "hits": {
                "total": 99999,
                "max_score": 0.0,
                "hits": []
            },
            "aggregations": {}}

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch.object(AggregationBuilder, 'build_one')
    @mock.patch.object(SearchBuilder, 'build')
    @mock.patch.object(Elasticsearch, 'search')
    def test_filter_suggest_company__valid(
        self, mock_search, mock_builder1, mock_builder2
    ):

        result = copy.deepcopy(self.result)
        result["aggregations"]["company.suggest"] = {
            "doc_count": 4954,
            "company.suggest": {
                "doc_count_error_upper_bound": 0,
                "sum_other_doc_count": 360,
                "buckets": [
                    {"key": "bank 1", "doc_count": 1481},
                    {"key": "Bank 2", "doc_count": 1123},
                    {"key": "BANK 3rd", "doc_count": 810},
                    {"key": "bank 4", "doc_count": 775},
                    {"key": "BANK 5th", "doc_count": 405},
                    {"key": "company 1", "doc_count": 12}
                ]}}
        mock_search.return_value = result
        mock_builder1.return_value = self.body
        agg = copy.deepcopy(self.oneAgg)
        agg['aggs'] = {
            "company.suggest": {
                "terms": {
                    "field": "company.suggest",
                    "size": 0
                }
            }
        }
        mock_builder2.return_value = agg

        actual = filter_suggest(
            'company.suggest',
            display_field='company.raw',
            text='BA',
            company='company 1'
        )

        mock_search.assert_called_once_with(
            body={
                'foo': 'bar',
                'aggs': {
                    'company.suggest': {
                        'filter': {
                            'bool': {
                                'must': [
                                    {
                                        'wildcard': {
                                            'company.suggest': '*BA*'
                                        }}]}
                        },
                        "aggs": {
                            "company.suggest": {
                                "terms": {
                                    "field": "company.raw",
                                    "size": 0
                                }
                            }
                        }
                    }
                }
            },
            index='INDEX')
        mock_builder2.assert_called_once_with('company.suggest')
        self.assertEqual(actual, [
            'bank 1', 'Bank 2', 'BANK 3rd', 'bank 4', 'BANK 5th', 'company 1'
        ])

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch.object(AggregationBuilder, 'build_one')
    @mock.patch.object(SearchBuilder, 'build')
    @mock.patch.object(Elasticsearch, 'search')
    def test_filter_suggest_zip_code__valid(
        self, mock_search, mock_builder1, mock_builder2
    ):
        result = copy.deepcopy(self.result)
        result["aggregations"]["zip_code"] = {
            "doc_count": 4954,
            "zip_code": {
                "doc_count_error_upper_bound": 0,
                "sum_other_doc_count": 360,
                "buckets": [
                    {"key": "207XX", "doc_count": 1481},
                    {"key": "200XX", "doc_count": 1123},
                    {"key": "201XX", "doc_count": 810},
                    {"key": "208XX", "doc_count": 775},
                    {"key": "206XX", "doc_count": 405}
                ]}}

        mock_search.return_value = result
        mock_builder1.return_value = self.body
        agg = copy.deepcopy(self.oneAgg)
        agg['aggs'] = {
            "zip_code": {
                "terms": {
                    "field": "zip_code",
                    "size": 0
                }
            }
        }
        mock_builder2.return_value = agg

        actual = filter_suggest('zip_code', text='20')

        mock_search.assert_called_once_with(
            body={
                'foo': 'bar',
                'aggs': {
                    'zip_code': {
                        'filter': {
                            'bool': {
                                'must': [
                                    {
                                        'prefix': {
                                            'zip_code': '20'
                                        }}]}
                        },
                        "aggs": {
                            "zip_code": {
                                "terms": {
                                    "field": "zip_code",
                                    "size": 0
                                }
                            }
                        }
                    }
                }
            },
            index='INDEX')
        mock_builder2.assert_called_once_with('zip_code')
        self.assertEqual(actual, [
            '207XX', '200XX', '201XX', '208XX', '206XX'
        ])


class EsInterfaceTest_Document(TestCase):

    @mock.patch("complaint_search.es_interface._COMPLAINT_ES_INDEX", "INDEX")
    @mock.patch.object(Elasticsearch, 'search')
    def test_document__valid(self, mock_search):
        mock_search.return_value = 'OK'
        body = {"query": {"term": {"_id": 123456}}}
        res = document(123456)
        self.assertEqual(len(mock_search.call_args), 2)
        self.assertEqual(0, len(mock_search.call_args[0]))
        self.assertEqual(2, len(mock_search.call_args[1]))
        self.assertDictEqual(mock_search.call_args[1]['body'], body)
        self.assertEqual(mock_search.call_args[1]['index'], 'INDEX')
        self.assertEqual('OK', res)
