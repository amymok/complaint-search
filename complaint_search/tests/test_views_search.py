from django.core.urlresolvers import reverse
from django.conf import settings
from rest_framework import status
from rest_framework.test import APITestCase
from unittest import skip
import mock
from datetime import date, datetime
from elasticsearch import TransportError
from complaint_search.es_interface import search
from complaint_search.serializer import SearchInputSerializer

class SearchTests(APITestCase):

    def setUp(self):
        pass

    def buildDefaultParams(self, overrides):
        params = {
            "field": "complaint_what_happened", 
            "format": "json", 
            "frm": 0, 
            "no_aggs": False, 
            "size": 10, 
            "sort": "relevance_desc"
        }

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
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({}))
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
        FORMAT_CONTENT_TYPE_MAP = {
            "csv": "text/csv",
            "xls": "application/vnd.ms-excel",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        }

        for k, v in FORMAT_CONTENT_TYPE_MAP.iteritems():
            url = reverse('complaint_search:search')
            params = {"format": k}
            mock_essearch.return_value = 'OK'
            mock_dt.now.return_value = datetime(2017,1,1,12,0)
            response = self.client.get(url, params)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn(v, response.get('Content-Type'))
            self.assertEqual(response.get('Content-Disposition'), 'attachment; filename="complaints-2017-01-01_12_00.{}"'.format(k))
            self.assertEqual('OK', response.content)
        mock_essearch.has_calls([ mock.call(format=k) for k in FORMAT_CONTENT_TYPE_MAP ], any_order=True)
        self.assertEqual(3, mock_essearch.call_count)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_field__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        for field in SearchInputSerializer.FIELD_CHOICES:
            params = {"field": field[0]}
            mock_essearch.return_value = 'OK'
            response = self.client.get(url, params)
            self.assertEqual(status.HTTP_200_OK, response.status_code)
            self.assertEqual('OK', response.data)

        calls = [ mock.call(**self.buildDefaultParams({
            "field": SearchInputSerializer.FIELD_MAP.get(field_pair[0], 
                field_pair[0])}))
            for field_pair in SearchInputSerializer.FIELD_CHOICES ]
        mock_essearch.assert_has_calls(calls)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_field__invalid_choice(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"field": "invalid_choice"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual({"field": ["\"invalid_choice\" is not a valid choice."]}, 
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_size__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"size": 4}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(**self.buildDefaultParams(params))
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
    def test_search_with_size__invalid_smaller_than_min_number(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"size": -1}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"size": ["Ensure this value is greater than or equal to 1."]}, 
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_size__invalid_exceed_max_number(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"size": 100001}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"size": ["Ensure this value is less than or equal to 100000."]}, 
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_frm__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = { "frm": 10 }
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(**self.buildDefaultParams(params))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_frm__invalid_type(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"frm": "not_integer"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual({"frm": ["A valid integer is required."]}, 
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_frm__invalid_smaller_than_min_number(self, mock_essearch):
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
        params = {"frm": 100001}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"frm": ["Ensure this value is less than or equal to 100000."]}, 
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_frm__invalid_frm_not_multiples_of_size(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = { "frm": 4 }
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

        calls = [ mock.call(**self.buildDefaultParams({"sort": sort_pair[0]}))
            for sort_pair in SearchInputSerializer.SORT_CHOICES ]
        mock_essearch.assert_has_calls(calls)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_sort__invalid_choice(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"sort": "invalid_choice"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual({"sort": ["\"invalid_choice\" is not a valid choice."]}, 
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_search_term__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"search_term": "FHA Mortgage"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(**self.buildDefaultParams(params))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_date_received_min__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"date_received_min": "2017-04-11"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
            "date_received_min": date(2017, 4, 11)}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_date_received_min__invalid_format(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"date_received_min": "not_a_date"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual({"date_received_min": ["Date has wrong format. Use one of these formats instead: YYYY[-MM[-DD]]."]}, 
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_date_received_max__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"date_received_max": "2017-04-11"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
            "date_received_max": date(2017, 4, 11)}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_date_received_max__invalid_format(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"date_received_max": "not_a_date"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual({"date_received_max": ["Date has wrong format. Use one of these formats instead: YYYY[-MM[-DD]]."]}, 
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_received_min__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"company_received_min": "2017-04-11"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
            "company_received_min": date(2017, 4, 11)}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_received_min__invalid_format(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"company_received_min": "not_a_date"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual({"company_received_min": ["Date has wrong format. Use one of these formats instead: YYYY[-MM[-DD]]."]}, 
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_received_max__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"company_received_max": "2017-04-11"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
            "company_received_max": date(2017, 4, 11)}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_received_max__invalid_format(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"company_received_max": "not_a_date"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual({"company_received_max": ["Date has wrong format. Use one of these formats instead: YYYY[-MM[-DD]]."]}, 
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?company=One%20Bank&company=Bank%202"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
            "company": ["One Bank", "Bank 2"]}))
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
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
            "product": ["Mortgage-FHA Mortgage", "Payday Loan"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_issue__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        # parameter doesn't represent real data, as client has a hard time 
        # taking unicode.  The original API will use a bullet u2022 in place 
        # of the '-'
        url += "?issue=Communication%20tactics-Frequent%20or%20repeated%20calls" \
        "&issue=Loan%20servicing,%20payments,%20escrow%20account"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
                "issue": ["Communication tactics-Frequent or repeated calls", 
            "Loan servicing, payments, escrow account"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_state__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?state=CA&state=FL&state=VA"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
                "state": ["CA", "FL", "VA"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_zip_code__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?zip_code=94XXX&zip_code=24236&zip_code=23456"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
                "zip_code": ["94XXX", "24236", "23456"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_timely__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?timely=YES&timely=NO"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
                "timely": ["YES", "NO"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_consumer_disputed__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?consumer_disputed=yes&consumer_disputed=no"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
                "consumer_disputed": ["yes", "no"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_response__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?company_response=Closed&company_response=No%20response"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({ 
                "company_response": ["Closed", "No response"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_company_public_response__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?company_public_response=Closed&company_public_response=No%20response"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
                "company_public_response": ["Closed", "No response"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_consumer_consent_provided__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?consumer_consent_provided=Yes&consumer_consent_provided=No"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
                "consumer_consent_provided": ["Yes", "No"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_has_narrative__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?has_narrative=Yes&has_narrative=No"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
                "has_narrative": ["Yes", "No"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_submitted_via__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?submitted_via=Web&submitted_via=Phone"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
                "submitted_via": ["Web", "Phone"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_tag__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        url += "?tag=Older%20American&tag=Servicemember"
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        # -*- coding: utf-8 -*-
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
                "tag": ["Older American", "Servicemember"]}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_no_aggs__valid(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"no_aggs": True}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_essearch.assert_called_once_with(**self.buildDefaultParams({
                "no_aggs": True}))
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search_with_no_aggs__invalid_type(self, mock_essearch):
        url = reverse('complaint_search:search')
        params = {"no_aggs": "Not boolean"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual({"no_aggs": [u'"Not boolean" is not a valid boolean.']}, 
            response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search__transport_error_with_status_code(self, mock_essearch):
        mock_essearch.side_effect = TransportError(status.HTTP_404_NOT_FOUND, "Error")
        url = reverse('complaint_search:search')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertDictEqual({"error": "Elasticsearch error: Error"}, response.data)

    @mock.patch('complaint_search.es_interface.search')
    def test_search__transport_error_without_status_code(self, mock_essearch):
        mock_essearch.side_effect = TransportError('N/A', "Error")
        url = reverse('complaint_search:search')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual({"error": "Elasticsearch error: Error"}, response.data)


