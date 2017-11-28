#!/usr/local/bin/python
# coding: utf-8

from rest_framework import status
from rest_framework.decorators import (
    api_view, renderer_classes, throttle_classes
)
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer
from rest_framework.response import Response
from django.http import HttpResponse, StreamingHttpResponse
from django.conf import settings
from datetime import datetime
from elasticsearch import TransportError
import es_interface
from complaint_search.defaults import (
    AGG_EXCLUDE_FIELDS,
    EXPORT_FORMATS,
    FORMAT_CONTENT_TYPE_MAP
)
from complaint_search.renderers import (
    DefaultRenderer, CSVRenderer
)
from complaint_search.decorators import catch_es_error
from complaint_search.serializer import (
    SearchInputSerializer, SuggestInputSerializer, SuggestFilterInputSerializer
)
from complaint_search.throttling import (
    SearchAnonRateThrottle,
    ExportUIRateThrottle,
    ExportAnonRateThrottle,
    DocumentAnonRateThrottle,
)

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
    'frm',
    'no_aggs',
    'no_highlight',
    'search_term',
    'size',
    'sort'
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


def _parse_query_params(query_params, validVars=None):
    if not validVars:
        validVars = list(QPARAMS_VARS)

    data = {}
    for param in query_params:
        if param in validVars:
            data[param] = query_params.get(param)
        elif param in QPARAMS_LISTS:
            data[param] = query_params.getlist(param)
          # TODO: else: Error if extra parameters? Or ignore?

    return data


# -----------------------------------------------------------------------------
# Header methods

def _buildHeaders():
    # Local development requires CORS support
    headers = {}
    if settings.DEBUG:
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET'
        }
    return headers


# -----------------------------------------------------------------------------
# Request Handlers

@api_view(['GET'])
@renderer_classes((
    DefaultRenderer,
    JSONRenderer,
    CSVRenderer,
    BrowsableAPIRenderer,
))
@throttle_classes([
    SearchAnonRateThrottle,
    ExportUIRateThrottle,
    ExportAnonRateThrottle,
])
@catch_es_error
def search(request):
    """
    Search through everything in Consumer Complaints
    ---
    path: "/"
    parameters:
        - name: format
          in: query
          description: Format to be returned
          required: false
          type: string
          enum:
            - json
            - csv
            - xls
            - xlsx
          default: json
          collectionFormat: multi
        - name: field
          in: query
          description: Search by particular field
          required: false
          type: array
          items:
          type: string
          enum:
            - complaint_what_happened
            - company_public_response
            - all
          default: all
          collectionFormat: multi
        - name: size
          in: query
          description: Limit the size of the search result
          required: false
          type: integer
          maximum: 100000
          minimum: 1
          format: int64
        - name: from
          in: query
          description: Return results starting from a specific index
          required: false
          type: integer
          maximum: 100000
          minimum: 1
          format: int64
        - name: sort
          in: query
          description: Return results sort in a particular order
          required: false
          type: string
          enum:
            - "-relevance"
            - "+relevance"
            - "-created_date"
            - "+created_date"
          default: "-relevance"
        - name: search_term
          in: query
          description: Return results containing specific term
          required: false
          type: string
        - name: min_date
          in: query
          description: Return results with date >= min_date (i.e. 2017-03-04)
          required: false
          type: string
          format: date
        - name: max_date
          in: query
          description: Return results with date < max_date (i.e. 2017-03-04)
          required: false
          type: string
          format: date
        - name: company
          in: query
          description: Filter the results to only return these companies
          required: false
          type: array
          items: 
          type: string
          collectionFormat: multi
        - name: product
          in: query
          description: "Filter the results to only return these types of product and subproduct, i.e. product-only: Mortgage, subproduct needs to include product, separated by '•', U+2022: Mortgage•FHA mortgage"
          required: false
          type: array
          items: 
          type: string
          collectionFormat: multi
        - name: issue
          in: query
          description: "Filter the results to only return these types of issue and subissue, i.e. product-only: Getting a Loan, subproduct needs to include product, separated by '•', U+2022: Getting a Loan•Can't qualify for a loan"
          required: false
          type: array
          items: 
          type: string
          collectionFormat: multi
        - name: state
          in: query
          description: Filter the results to only return these states (use abbreviation, i.e. CA, VA)
          required: false
          type: array
          items: 
          type: string
          collectionFormat: multi
        - name: consumer_disputed
          in: query
          description: Filter the results to only return the specified state of consumer disputed, i.e. yes, no
          required: false
          type: array
          items: 
          type: string
          collectionFormat: multi
        - name: company_response
          in: query
          description: Filter the results to only return these types of response by the company
          required: false
          type: array
          items: 
          type: string
          collectionFormat: multi
        - name: company_public_response
          in: query
          description: Filter the results to only return these types of public response by the company
          required: false
          type: array
          items: 
          type: string
          collectionFormat: multi
        - name: consumer_consent_provided
          in: query
          description: Filter the results to only return these types of consent consumer provided
          required: false
          type: array
          items: 
          type: string
          collectionFormat: multi
        - name: submitted_via
          in: query
          description: Filter the results to only return these types of way consumers submitted their complaints
          required: false
          type: array
          items: 
          type: string
          collectionFormat: multi
        - name: tag
          in: query
          description: Filter the results to only return these types of tag
          required: false
          type: array
          items: 
          type: string
          collectionFormat: multi
        - name: has_narratives
          in: query
          description: Filter the results to only return the specified state of whether it has narrative in the complaint or not, i.e. yes, no
          required: false
          type: array
          items: 
          type: string
          collectionFormat: multi

    request_serializer: SearchInputSerializer

    type:
        results_array:
            required: True
            type: array
            items:
              $ref: '#/definitions/Complaint'

    many: True

    responseMessages:
        - code: 200
          message: "Successful Operation"
        - code: 400
          message: "Invalid status value"

    consumes:
        - application/json
        - application/xml

    produces:
        - "application/json"
        - "text/csv"
        - "application/vnd.ms-excel"
        - "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    """
    fixed_qparam = request.query_params
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
    """
    Autocomplete for the Search of consumer complaints
    ---
    parameters:
        - name: size
          in: query
          description: number of suggestions to return, default 6
          required: true
          type: integer
        - name: text
          in: query
          description: text to find suggestions on
          required: true
          type: string

    request_serializer: SuggestInputSerializer

    type:
        suggest_array:
            required: True
            type: array
            items:
                type: string

    many: True

    responseMessages:
        - code: 200
          message: "Successful Operation"
        - code: 400
          message: "Invalid input"

    consumes:
        - application/json
        - application/xml

    produces:
        - application/json
    """
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
    """
    Find comsumer complaint by ID
    ---
    parameters:
        - name: id
          in: path
          description: ID of the complaint
          required: true
          type: integer
          maximum: 9999999999
          minimum: 0
          format: int64

    responseMessages:
        - code: 200
          message: "Successful Operation"
        - code: 400
          message: "Invalid input"
    """
    results = es_interface.document(id)
    return Response(results, headers=_buildHeaders())
