import copy

import mock
from complaint_search.defaults import AGG_EXCLUDE_FIELDS, PARAMS
from complaint_search.serializer import SearchInputSerializer
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APITestCase


try:
    from django.urls import reverse

except ImportError:
    from django.core.urlresolvers import reverse


class StatesTests(APITestCase):

    def setUp(self):
        pass

    def buildDefaultParams(self, overrides):
        params = copy.deepcopy(PARAMS)
        del params["search_after"]
        params.update(overrides)
        return params

    @mock.patch('complaint_search.es_interface.states_agg')
    def test_states_no_param(self, mock_essearch):
        """
        Searching with no parameters
        """
        url = reverse('complaint_search:states')
        mock_essearch.return_value = 'OK'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_essearch.assert_called_once_with(agg_exclude=AGG_EXCLUDE_FIELDS,
                                              **self.buildDefaultParams({}))
        self.assertEqual('OK', response.data)

    @parameterized.expand([
        [('complaint_what_happened', 'complaint_what_happened field')],
        [('company', 'company field')],
        [('all', 'all fields')],
    ])
    @mock.patch('complaint_search.es_interface.states_agg')
    def test_states_with_field__valid(self, test_pair, mock_essearch):
        url = reverse('complaint_search:states')
        params = {"field": test_pair[0]}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual('OK', response.data)

        calls = [
            mock.call(
                agg_exclude=AGG_EXCLUDE_FIELDS,
                **self.buildDefaultParams({
                    "field": SearchInputSerializer.FIELD_MAP.get(
                        test_pair[0],
                        test_pair[0]
                    )})
            )
        ]
        mock_essearch.assert_has_calls(calls)

    @mock.patch('complaint_search.es_interface.states_agg')
    def test_state_with_field__invalid(self, mock_essearch):
        url = reverse('complaint_search:states')
        params = {"field": "invalid_choice"}
        mock_essearch.return_value = 'OK'
        response = self.client.get(url, params)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        mock_essearch.assert_not_called()
        self.assertDictEqual(
            {"field": ["\"invalid_choice\" is not a valid choice."]},
            response.data
        )
