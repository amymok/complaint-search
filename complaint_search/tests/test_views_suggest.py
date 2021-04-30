from django.conf import settings

import mock
from elasticsearch7 import TransportError
from rest_framework import status
from rest_framework.test import APITestCase


try:
    from django.urls import reverse
except ImportError:
    from django.core.urlresolvers import reverse


class SuggestTests(APITestCase):

    def setUp(self):
        pass

    @mock.patch('complaint_search.es_interface.suggest')
    def test_suggest_no_param(self, mock_essuggest):
        """
        Suggesting with no parameters
        """
        url = reverse('complaint_search:suggest')
        mock_essuggest.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_essuggest.assert_called_once_with()
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.suggest')
    def test_suggest_text__valid(self, mock_essuggest):
        """
        Suggesting with no parameters
        """
        url = reverse('complaint_search:suggest')
        param = {"text": "Mortgage"}
        mock_essuggest.return_value = 'OK'
        response = self.client.get(url, param)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_essuggest.assert_called_once_with(**param)
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.suggest')
    def test_suggest_size__valid(self, mock_essuggest):
        """
        Suggesting with no parameters
        """
        url = reverse('complaint_search:suggest')
        param = {"size": 50}
        mock_essuggest.return_value = 'OK'
        response = self.client.get(url, param)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_essuggest.assert_called_once_with(**param)
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.suggest')
    def test_suggest_with_size__invalid_smaller_than_min_number(
        self, mock_essuggest
    ):
        url = reverse('complaint_search:suggest')
        params = {"size": 0}
        mock_essuggest.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essuggest.assert_not_called()
        self.assertDictEqual(
            {"size": ["Ensure this value is greater than or equal to 1."]},
            response.data)

    @mock.patch('complaint_search.es_interface.suggest')
    def test_suggest_size__invalid_exceed_number(self, mock_essuggest):
        """
        Suggesting with no parameters
        """
        url = reverse('complaint_search:suggest')
        param = {"size": 100001}
        mock_essuggest.return_value = 'OK'
        response = self.client.get(url, param)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_essuggest.assert_not_called()
        self.assertDictEqual(
            {"size": ["Ensure this value is less than or equal to 100000."]},
            response.data)

    @mock.patch('complaint_search.es_interface.suggest')
    def test_suggest_cors_headers(self, mock_essuggest):
        """
        Make sure the response has CORS headers in debug mode
        """
        settings.DEBUG = True
        url = reverse('complaint_search:suggest')
        mock_essuggest.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.has_header('Access-Control-Allow-Origin'))

    @mock.patch('complaint_search.es_interface.suggest')
    def test_suggest__transport_error(self, mock_essuggest):
        mock_essuggest.side_effect = TransportError('N/A', "Error")
        url = reverse('complaint_search:suggest')
        param = {"text": "test"}
        response = self.client.get(url, param)
        self.assertEqual(response.status_code, 424)
        self.assertDictEqual(
            {"error": "There was an error calling Elasticsearch"},
            response.data
        )
