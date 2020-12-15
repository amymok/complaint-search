import logging

from datetime import datetime

from django.conf import settings
from django.http import StreamingHttpResponse

from complaint_search import es_interface
from complaint_search.decorators import catch_es_error
from complaint_search.defaults import (
    AGG_EXCLUDE_FIELDS,
    EXCLUDE_PREFIX,
    EXPORT_FORMATS,
    FORMAT_CONTENT_TYPE_MAP,
)
from complaint_search.renderers import CSVRenderer, DefaultRenderer
from complaint_search.serializer import (
    SearchInputSerializer,
    SuggestFilterInputSerializer,
    SuggestInputSerializer,
    TrendsInputSerializer,
)
from complaint_search.throttling import (
    DocumentAnonRateThrottle,
    ExportAnonRateThrottle,
    ExportUIRateThrottle,
    SearchAnonRateThrottle,
)
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    renderer_classes,
    throttle_classes,
)
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response


# -----------------------------------------------------------------------------
# Query Parameters
#
# When you add a query parameter, make sure you add it to one of the
# constant tuples below so it will be parse correctly

QPARAMS_VARS = (
    'company_received_max',
    'company_received_min',
    'date_received_max',
    'date_received_min',
    'field',
    'focus',
    'frm',
    'lens',
    'no_aggs',
    'no_highlight',
    'search_term',
    'size',
    'sort',
    'sub_lens',
    'sub_lens_depth',
    'trend_depth',
    'trend_interval'
)


QPARAMS_LISTS = (
    'company',
    'company_public_response',
    'company_response',
    'consumer_consent_provided',
    'consumer_disputed',
    'has_narrative',
    'issue',
    'product',
    'state',
    'submitted_via',
    'tags',
    'timely',
    'zip_code'
)

QPARAMS_NOT_LISTS = [EXCLUDE_PREFIX + x for x in QPARAMS_LISTS]


def _parse_query_params(query_params, validVars=None):
    if not validVars:
        validVars = list(QPARAMS_VARS)

    data = {}
    for param in query_params:
        if param in validVars:
            data[param] = query_params.get(param)
        elif param in QPARAMS_LISTS:
            data[param] = query_params.getlist(param)
        elif param in QPARAMS_NOT_LISTS:
            data[param] = query_params.getlist(param)
        # TODO: else: Error if extra parameters? Or ignore?

    return data


# -----------------------------------------------------------------------------
# Header methods

def _buildHeaders():
    # API Documentation hosted on Github pages needs GET access
    headers = {
        'Access-Control-Allow-Origin': 'https://cfpb.github.io',
        'Access-Control-Allow-Methods': 'GET'
    }
    # Local development requires CORS support
    if settings.DEBUG:
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET'
        }
    return headers


# -----------------------------------------------------------------------------
# Request Handlers: Complaints

@api_view(['GET'])
@renderer_classes((
    DefaultRenderer,
    JSONRenderer,
    CSVRenderer,
))
@throttle_classes([
    SearchAnonRateThrottle,
    ExportUIRateThrottle,
    ExportAnonRateThrottle,
])
@catch_es_error
def search(request):

    data = _parse_query_params(request.query_params)

    # Add format to data
    format = request.accepted_renderer.format
    if format and format in EXPORT_FORMATS:
        data['format'] = format
    else:
        data['format'] = 'default'

    serializer = SearchInputSerializer(data=data)

    if not serializer.is_valid():
        return Response(
            serializer.errors, status=status.HTTP_400_BAD_REQUEST
        )

    results = es_interface.search(
        agg_exclude=AGG_EXCLUDE_FIELDS, **serializer.validated_data)
    headers = _buildHeaders()

    if format not in EXPORT_FORMATS:
        return Response(results, headers=headers)

    # If format is in export formats, update its attachment response
    # with a filename

    response = StreamingHttpResponse(
        streaming_content=results,
        content_type=FORMAT_CONTENT_TYPE_MAP[format]
    )
    filename = 'complaints-{}.{}'.format(
        datetime.now().strftime('%Y-%m-%d_%H_%M'), format
    )
    headerTemplate = 'attachment; filename="{}"'
    response['Content-Disposition'] = headerTemplate.format(filename)
    for header in headers:
        response[header] = headers[header]

    return response


@api_view(['GET'])
@catch_es_error
def suggest(request):
    data = _parse_query_params(request.query_params, ['text', 'size'])

    serializer = SuggestInputSerializer(data=data)
    if serializer.is_valid():
        results = es_interface.suggest(**serializer.validated_data)
        return Response(results, headers=_buildHeaders())
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def _suggest_field(data, field, display_field=None):
    serializer = SuggestFilterInputSerializer(data=data)
    if serializer.is_valid():
        results = es_interface.filter_suggest(
            field, display_field, **serializer.validated_data
        )
        return Response(results, headers=_buildHeaders())
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@catch_es_error
def suggest_zip(request):
    validVars = list(QPARAMS_VARS)
    validVars.append('text')

    data = _parse_query_params(request.query_params, validVars)
    if data.get('text'):
        data['text'] = data['text'].upper()
    return _suggest_field(data, 'zip_code')


@api_view(['GET'])
@catch_es_error
def suggest_company(request):
    # Key removal that takes mutation into account in case of other reference
    def removekey(d, key):
        r = dict(d)
        del r[key]
        return r

    validVars = list(QPARAMS_VARS)
    validVars.append('text')

    data = _parse_query_params(request.query_params, validVars)

    # Company filters should not be applied to their own aggregation filter
    if 'company' in data:
        data = removekey(data, 'company')

    if data.get('text'):
        data['text'] = data['text'].upper()

    return _suggest_field(data, 'company.suggest', 'company.raw')


@api_view(['GET'])
@throttle_classes([DocumentAnonRateThrottle, ])
@catch_es_error
def document(request, id):
    results = es_interface.document(id)
    return Response(results, headers=_buildHeaders())


# -----------------------------------------------------------------------------
# Request Handlers: Geo

@api_view(['GET'])
@catch_es_error
def states(request):
    data = _parse_query_params(request.query_params)
    serializer = SearchInputSerializer(data=data)

    if not serializer.is_valid():
        return Response(
            serializer.errors, status=status.HTTP_400_BAD_REQUEST
        )

    results = es_interface.states_agg(
        agg_exclude=AGG_EXCLUDE_FIELDS, **serializer.validated_data)
    headers = _buildHeaders()

    return Response(results, headers=headers)


# -----------------------------------------------------------------------------
# Request Handlers: Trends

@api_view(['GET'])
@catch_es_error
def trends(request):
    data = _parse_query_params(request.query_params)
    serializer = TrendsInputSerializer(data=data)

    if not serializer.is_valid():
        return Response(
            serializer.errors, status=status.HTTP_400_BAD_REQUEST
        )

    results = es_interface.trends(
        agg_exclude=AGG_EXCLUDE_FIELDS, **serializer.validated_data)
    headers = _buildHeaders()

    return Response(results, headers=headers)
