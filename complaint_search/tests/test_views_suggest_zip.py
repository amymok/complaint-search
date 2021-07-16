from django.conf import settings

import mock
from elasticsearch7 import TransportError
from rest_framework import status
from rest_framework.test import APITestCase


try:
    from django.urls import reverse
except ImportError:
    from django.core.urlresolvers import reverse


class SuggestZipTests(APITestCase):

    def setUp(self):
        pass

    @mock.patch('complaint_search.es_interface.filter_suggest')
    def test_suggest_no_param(self, mock_essuggest):
        """
        Suggesting with no parameters
        """
        url = reverse('complaint_search:suggest_zip')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_essuggest.assert_not_called()
        self.assertDictEqual(
            {'text': [u'This field is required.']},
            response.data)

    @mock.patch('complaint_search.es_interface.filter_suggest')
    def test_suggest_text__valid(self, mock_essuggest):
        """
        Suggesting with text
        """
        url = reverse('complaint_search:suggest_zip')
        param = {"text": "20x"}
        mock_essuggest.return_value = 'OK'
        response = self.client.get(url, param)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_essuggest.assert_called_once_with(
            'zip_code',
            None,
            field='complaint_what_happened',
            format='default',
            frm=0,
            no_aggs=False,
            no_highlight=False,
            page=1,
            size=25,
            sort='relevance_desc',
            text=u'20X'
        )
        self.assertEqual('OK', response.data)

    @mock.patch('complaint_search.es_interface.filter_suggest')
    def test_suggest_cors_headers(self, mock_essuggest):
        """
        Make sure the response has CORS headers in debug mode
        """
        settings.DEBUG = True
        url = reverse('complaint_search:suggest_zip')
        param = {"text": "20"}
        mock_essuggest.return_value = 'OK'
        response = self.client.get(url, param)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.has_header('Access-Control-Allow-Origin'))

    @mock.patch('complaint_search.es_interface.filter_suggest')
    def test_suggest__transport_error(
        self, mock_essuggest
    ):
        mock_essuggest.side_effect = TransportError('N/A', "Error")
        url = reverse('complaint_search:suggest_zip')
        param = {"text": "test"}
        response = self.client.get(url, param)
        self.assertEqual(response.status_code, 424)
        self.assertDictEqual(
            {"error": "There was an error calling Elasticsearch"},
            response.data
        )
