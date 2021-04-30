import copy
from datetime import date, datetime

from django.conf import settings
from django.core.cache import cache
from django.http import StreamingHttpResponse

import mock
from complaint_search.defaults import (
    AGG_EXCLUDE_FIELDS,
    FORMAT_CONTENT_TYPE_MAP,
    PARAMS,
)
from complaint_search.serializer import SearchInputSerializer
from complaint_search.throttling import (
    _CCDB_UI_URL,
    ExportAnonRateThrottle,
    ExportUIRateThrottle,
    SearchAnonRateThrottle,
)
from elasticsearch7 import TransportError
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APITestCase


try:
    from django.urls import reverse
except ImportError:
    from django.core.urlresolvers import reverse


class SearchTests(APITestCase):

    def setUp(self):
        self.orig_search_anon_rate = SearchAnonRateThrottle.rate
        self.orig_export_ui_rate = ExportUIRateThrottle.rate
        self.orig_export_anon_rate = ExportAnonRateThrottle.rate
        # Setting rates to something really big so it doesn't affect testing
        SearchAnonRateThrottle.rate = '2000/min'
        ExportUIRateThrottle.rate = '2000/min'
        ExportAnonRateThrottle.rate = '2000/min'

    def tearDown(self):
        cache.clear()
        SearchAnonRateThrottle.rate = self.orig_search_anon_rate
        ExportUIRateThrottle.rate = self.orig_export_ui_rate
        ExportAnonRateThrottle.rate = self.orig_export_anon_rate

    def buildDefaultParams(self, overrides):
        params = copy.deepcopy(PARAMS)
        params.update(overrides)
        return params

    @mock.patch('complaint_search.es_interface.search')
    def test_search_no_param(self, mock_essearch):
        """
        Searching with no parameters
        """
        url = reverse('complaint_search:search')
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_essearch.assert_called_once_with(agg_exclude=AGG_EXCLUDE_FIELDS,
                                              **self.buildDefaultParams({}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_cors_headers(self, mock_essearch):
        """
        Make sure the response has CORS headers in debug mode
        """
        settings.DEBUG = True
        url = reverse('complaint_search:search')
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.has_header('Access-Control-Allow-Origin'))

    @mock.patch('complaint_search.views.datetime')
    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_format(self, mock_essearch, mock_dt):
        """
        Searching with format
        """
        for k, v in FORMAT_CONTENT_TYPE_MAP.items():
            url = reverse('complaint_search:search')
            params = {"format": k}
            mock_essearch.return_value = 'OK'
            mock_dt.now.return_value = datetime(2017, 1, 1, 12, 0)
            response = self.client.get(url, params)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn(v, response.get('Content-Type'))
            self.assertEqual(
                response.get('Content-Disposition'),
                'attachment; filename="complaints-2017-01-01_12_00.{}"'.format(
                    k
                )
            )
            self.assertTrue(isinstance(response, StreamingHttpResponse))
        mock_essearch.has_calls(
            [
                mock.call(format=k) for k in FORMAT_CONTENT_TYPE_MAP
            ],
            any_order=True
        )
        self.assertEqual(
            len(FORMAT_CONTENT_TYPE_MAP), mock_essearch.call_count
        )

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_field__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        for field in SearchInputSerializer.FIELD_CHOICES:
            params = {"field": field[0]}
            mock_essearch.return_value = 'OK'
            response = self.client.get(url, params)
            self.assertEqual(status.HTTP_200_OK, response.status_code)
            self.assertEqual('OK', response.data)

        calls = [
            mock.call(
                agg_exclude=AGG_EXCLUDE_FIELDS,
                **self.buildDefaultParams({
                    "field": SearchInputSerializer.FIELD_MAP.get(
                        field_pair[0],
                        field_pair[0]
                    )})
            )
            for field_pair in SearchInputSerializer.FIELD_CHOICES
        ]
        mock_essearch.assert_has_calls(calls)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_field__invalid_choice(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"field": "invalid_choice"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"field": ["\"invalid_choice\" is not a valid choice."]},
            response.data
        )

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_size__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"size": 4}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams(params)
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_size__valid_zero(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"size": 0}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams(params)
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_size__invalid_type(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"size": "not_integer"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual({"size": ["A valid integer is required."]},
                             response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_size__invalid_smaller_than_min_number(
        self, mock_essearch
    ):
        url = reverse('complaint_search:search')
        params = {"size": -1}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"size": ["Ensure this value is greater than or equal to 0."]},
            response.data
        )

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_size__invalid_exceed_max_number(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"size": 10000001}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"size": ["Ensure this value is less than or equal to 10000000."]},
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_frm__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"frm": 10}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams(params)
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_frm__invalid_type(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"frm": "not_integer"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"frm": ["A valid integer is required."]},
            response.data
        )

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_frm__invalid_smaller_than_min_number(
        self, mock_essearch
    ):
        url = reverse('complaint_search:search')
        params = {"frm": -1}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"frm": ["Ensure this value is greater than or equal to 0."]},
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_frm__invalid_exceed_max_number(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"frm": 10000001}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"frm": ["Ensure this value is less than or equal to 10000000."]},
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_frm__invalid_frm_not_multiples_of_size(
        self, mock_essearch
    ):
        url = reverse('complaint_search:search')
        params = {"frm": 4}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"non_field_errors": ["frm is not zero or a multiple of size"]},
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_sort__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        for sort in SearchInputSerializer.SORT_CHOICES:
            params = {"sort": sort[0]}
            mock_essearch.return_value = 'OK'
            response = self.client.get(url, params)
            self.assertEqual(status.HTTP_200_OK, response.status_code)
            self.assertEqual('OK', response.data)

        calls = [
            mock.call(agg_exclude=AGG_EXCLUDE_FIELDS,
                      **self.buildDefaultParams({"sort": sort_pair[0]}))
            for sort_pair in SearchInputSerializer.SORT_CHOICES
        ]
        mock_essearch.assert_has_calls(calls)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_sort__invalid_choice(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"sort": "invalid_choice"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"sort": ["\"invalid_choice\" is not a valid choice."]},
            response.data
        )

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_search_term__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"search_term": "FHA Mortgage"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams(params)
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_date_received_min__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"date_received_min": "2017-04-11"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "date_received_min": date(2017, 4, 11)})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_date_received_min__invalid_format(
        self, mock_essearch
    ):
        url = reverse('complaint_search:search')
        params = {"date_received_min": "not_a_date"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {'date_received_min': [
                ErrorDetail(
                    string='Date has wrong format. Use one of these formats '
                    'instead: YYYY-MM-DD.',
                    code='invalid'
                )
            ]},
            response.data
        )

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_date_received_max__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"date_received_max": "2017-04-11"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "date_received_max": date(2017, 4, 11)})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_date_received_max__invalid_format(
        self, mock_essearch
    ):
        url = reverse('complaint_search:search')
        params = {"date_received_max": "not_a_date"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {'date_received_max': [
                ErrorDetail(
                    string='Date has wrong format. Use one of these formats '
                    'instead: YYYY-MM-DD.',
                    code='invalid'
                )
            ]},
            response.data
        )

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_received_min__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"company_received_min": "2017-04-11"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "company_received_min": date(2017, 4, 11)})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_received_min__invalid_format(
        self, mock_essearch
    ):
        url = reverse('complaint_search:search')
        params = {"company_received_min": "not_a_date"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {'company_received_min': [
                ErrorDetail(
                    string='Date has wrong format. Use one of these formats '
                    'instead: YYYY-MM-DD.',
                    code='invalid')
            ]},
            response.data
        )

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_received_max__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"company_received_max": "2017-04-11"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "company_received_max": date(2017, 4, 11)})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_received_max__invalid_format(
        self, mock_essearch
    ):
        url = reverse('complaint_search:search')
        params = {"company_received_max": "not_a_date"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"company_received_max": [
                ErrorDetail(
                    string="Date has wrong format. Use one of these formats "
                    "instead: YYYY-MM-DD.",
                    code='invalid'
                )
            ]},
            response.data
        )

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?company=One%20Bank&company=Bank%202"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "company": ["One Bank", "Bank 2"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_not_company__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?not_company=One%20Bank&not_company=Bank%202"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "not_company": ["One Bank", "Bank 2"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_product__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        # parameter doesn't represent real data, as client has a hard time
        # taking unicode.  The original API will use a bullet u2022 in place
        # of the '-'
        url += "?product=Mortgage-FHA%20Mortgage&product=Payday%20Loan"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "product": ["Mortgage-FHA Mortgage", "Payday Loan"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_issue__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        # parameter doesn't represent real data, as client has a hard time
        # taking unicode.  The original API will use a bullet u2022 in place
        # of the '-'
        url += (
            "?issue=Communication%20tactics-Frequent%20or%20repeated%20calls"
            "&issue=Loan%20servicing,%20payments,%20escrow%20account"
        )
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "issue": ["Communication tactics-Frequent or repeated calls",
                          "Loan servicing, payments, escrow account"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_state__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?state=CA&state=FL&state=VA"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "state": ["CA", "FL", "VA"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_zip_code__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?zip_code=94XXX&zip_code=24236&zip_code=23456"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "zip_code": ["94XXX", "24236", "23456"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_timely__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?timely=YES&timely=NO"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "timely": ["YES", "NO"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_consumer_disputed__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?consumer_disputed=yes&consumer_disputed=no"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "consumer_disputed": ["yes", "no"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_response__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?company_response=Closed&company_response=No%20response"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "company_response": ["Closed", "No response"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_public_response__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += (
            "?company_public_response=Closed&"
            "company_public_response=No%20response"
        )
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "company_public_response": ["Closed", "No response"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_consumer_consent_provided__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?consumer_consent_provided=Yes&consumer_consent_provided=No"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "consumer_consent_provided": ["Yes", "No"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_has_narrative__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?has_narrative=Yes&has_narrative=No"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "has_narrative": ["Yes", "No"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_submitted_via__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?submitted_via=Web&submitted_via=Phone"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "submitted_via": ["Web", "Phone"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_tags__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?tags=Older%20American&tags=Servicemember"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "tags": ["Older American", "Servicemember"]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with__multiple_tags__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?tags=Older%20American%2C%20Servicemember"
        url += "&tags=Older%20American"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "tags": [
                    "Older American, Servicemember",
                    "Older American"
                ]})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_no_aggs__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"no_aggs": True}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "no_aggs": True})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_no_aggs__invalid_type(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"no_aggs": "Not boolean"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {'no_aggs': [
                ErrorDetail(string='Must be a valid boolean.', code='invalid')
            ]},
            response.data
        )

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_no_highlight__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"no_highlight": True}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(
            agg_exclude=AGG_EXCLUDE_FIELDS,
            **self.buildDefaultParams({
                "no_highlight": True})
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_no_highlight__invalid_type(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"no_highlight": "Not boolean"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {'no_highlight': [
                ErrorDetail(string='Must be a valid boolean.', code='invalid')
            ]},
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_search_anon_rate_throttle(self, mock_essearch):
        url = reverse('complaint_search:search')
        mock_essearch.return_value = 'OK'
        SearchAnonRateThrottle.rate = self.orig_search_anon_rate
        ExportUIRateThrottle.rate = self.orig_export_ui_rate
        ExportAnonRateThrottle.rate = self.orig_export_anon_rate
        limit = int(self.orig_search_anon_rate.split('/')[0])
        for _ in range(limit):
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual('OK', response.data)

        response = self.client.get(url)
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS
        )
        self.assertIsNotNone(response.data.get('detail'))
        self.assertIn("Request was throttled", response.data.get('detail'))
        self.assertEqual(limit, mock_essearch.call_count)
        self.assertEqual(20, limit)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_search_ui_rate_throttle(self, mock_essearch):
        url = reverse('complaint_search:search')
        mock_essearch.return_value = 'OK'

        SearchAnonRateThrottle.rate = self.orig_search_anon_rate
        ExportUIRateThrottle.rate = self.orig_export_ui_rate
        ExportAnonRateThrottle.rate = self.orig_export_anon_rate
        limit = int(self.orig_search_anon_rate.split('/')[0])
        for _ in range(limit):
            response = self.client.get(url, HTTP_REFERER=_CCDB_UI_URL)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual('OK', response.data)

        response = self.client.get(url, HTTP_REFERER=_CCDB_UI_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual('OK', response.data)
        self.assertEqual(limit + 1, mock_essearch.call_count)
        self.assertEqual(20, limit)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_export_anon_rate_throttle(self, mock_essearch):
        url = reverse('complaint_search:search')
        mock_essearch.return_value = 'OK'
        SearchAnonRateThrottle.rate = self.orig_search_anon_rate
        ExportUIRateThrottle.rate = self.orig_export_ui_rate
        ExportAnonRateThrottle.rate = self.orig_export_anon_rate
        limit = int(self.orig_export_anon_rate.split('/')[0])
        for i in range(limit):
            response = self.client.get(url, {"format": "csv"})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(isinstance(response, StreamingHttpResponse))

        response = self.client.get(url, {"format": "csv"})
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS
        )
        self.assertIsNotNone(response.data.get('detail'))
        self.assertIn("Request was throttled", response.data.get('detail'))
        self.assertEqual(limit, mock_essearch.call_count)
        self.assertEqual(2, limit)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_export_ui_rate_throttle(self, mock_essearch):
        url = reverse('complaint_search:search')
        mock_essearch.return_value = 'OK'
        SearchAnonRateThrottle.rate = self.orig_search_anon_rate
        ExportUIRateThrottle.rate = self.orig_export_ui_rate
        ExportAnonRateThrottle.rate = self.orig_export_anon_rate
        limit = int(self.orig_export_ui_rate.split('/')[0])
        for _ in range(limit):
            response = self.client.get(
                url, {"format": "csv"}, HTTP_REFERER=_CCDB_UI_URL
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(isinstance(response, StreamingHttpResponse))

        response = self.client.get(
            url, {"format": "csv"}, HTTP_REFERER=_CCDB_UI_URL
        )
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS
        )
        self.assertIsNotNone(response.data.get('detail'))
        self.assertIn("Request was throttled", response.data.get('detail'))
        self.assertEqual(limit, mock_essearch.call_count)
        self.assertEqual(6, limit)

    @mock.patch('complaint_search.es_interface.search')
    def test_search__transport_error(self, mock_essearch):
        mock_essearch.side_effect = TransportError('N/A', "Error")
        url = reverse('complaint_search:search')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 424)
        self.assertDictEqual(
            {"error": "There was an error calling Elasticsearch"},
            response.data
        )

    @mock.patch('complaint_search.es_interface.search')
    def test_search__big_error(self, mock_essearch):
        mock_essearch.side_effect = MemoryError("Out of memory")
        url = reverse('complaint_search:search')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 500)
        self.assertDictEqual(
            {"error": "There was a problem retrieving your request"},
            response.data
        )
