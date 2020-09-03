import copy
import logging
import os
from datetime import datetime, timedelta

from complaint_search.defaults import (
    CSV_ORDERED_HEADERS,
    EXPORT_FORMATS,
    PARAMS,
)
from complaint_search.es_builders import (
    AggregationBuilder,
    DateRangeBucketsBuilder,
    PostFilterBuilder,
    SearchBuilder,
    StateAggregationBuilder,
    TrendsAggregationBuilder,
)
from complaint_search.export import ElasticSearchExporter
from elasticsearch2 import Elasticsearch, helpers
from flags.state import flag_enabled


_ES_URL = "{}://{}:{}".format("http", os.environ.get('ES_HOST', 'localhost'),
                              os.environ.get('ES_PORT', '9200'))
_ES_USER = os.environ.get('ES_USER', '')
_ES_PASSWORD = os.environ.get('ES_PASSWORD', '')

_ES_INSTANCE = None

_COMPLAINT_ES_INDEX = os.environ.get('COMPLAINT_ES_INDEX', 'complaint-index')
_COMPLAINT_DOC_TYPE = os.environ.get('COMPLAINT_DOC_TYPE', 'complaint-doctype')


# -----------------------------------------------------------------------------
# Trends Operations
# -----------------------------------------------------------------------------

# Safely extracts a string from an object
# if it isn't present, the default value is returned
def extract_date(agg_term, default_value):
    return agg_term['value_as_string'] \
        if 'value_as_string' in agg_term else default_value


def build_trend_meta(response):
    meta = {}

    if 'max_date' in response['aggregations']:
        date_max = extract_date(response['aggregations']['max_date'], None)
        date_min = extract_date(response['aggregations']['min_date'], None)

        # del response["aggregations"]["max_date"]
        # del response["aggregations"]["min_date"]

        meta['date_min'] = date_min
        meta['date_max'] = date_max

    return meta


# Find sub_agg name if it exists in order to filter percent change
def get_sug_agg_key_if_exists(agg):
    agg_keys_exclude = ('trend_period', 'key', 'doc_count')
    for key in agg.keys():
        if key not in agg_keys_exclude:
            return key
    return None


# Filter out all but the most recent buckets in sub agg for the Percent
# Change on chart
def process_trend_aggregations(aggregations):
    trend_charts = (
        'product',
        'sub-product',
        'issue',
        'sub-issue',
        'tags'
    )

    for agg_name in trend_charts:
        if agg_name in aggregations:
            agg_buckets = \
                aggregations[agg_name][agg_name]['buckets']
            for sub_agg in agg_buckets:
                sub_agg['trend_period']['buckets'] = sorted(
                    sub_agg['trend_period']['buckets'],
                    key=lambda k: k['key_as_string'], reverse=True)
                sub_agg_name = get_sug_agg_key_if_exists(sub_agg)
                if sub_agg_name:
                    for sub_sub_agg in sub_agg[sub_agg_name]['buckets']:
                        sub_sub_agg['trend_period']['buckets'] = sorted(
                            sub_sub_agg['trend_period']['buckets'],
                            key=lambda k: k['key_as_string'],
                            reverse=True)[1:2]
    return aggregations


# Process the response from a trends query
def process_trends_response(response):
    response['aggregations'] = \
        process_trend_aggregations(response['aggregations'])

    response['_meta'] = build_trend_meta(response)

    return response


def _get_es():
    global _ES_INSTANCE
    if _ES_INSTANCE is None:
        _ES_INSTANCE = Elasticsearch(
            [_ES_URL],
            http_auth=(_ES_USER, _ES_PASSWORD),
            timeout=100
        )
    return _ES_INSTANCE


def _get_now():
    return datetime.now()


def _min_valid_time():
    # show notification starting fifth business day data has not been updated
    # M-Th, data needs to have been updated 6 days ago; F-S, preceding Monday
    now = _get_now()
    weekday = datetime.weekday(now)
    # When bigger than 3, it means it is a Friday/Saturday/Sunday,
    # we can use the weekday integer to get 4 days ago without the need to
    # worry about hitting the weekend.  Else we need to include the weekend
    delta = weekday if weekday > 3 else 6
    return (now - timedelta(delta)).strftime("%Y-%m-%d")


def _is_data_stale(last_updated_time):
    if (last_updated_time < _min_valid_time()):
        return True

    return False


def from_timestamp(seconds):
    # Socrata fields (:field_name) are indexed in seconds, not the usual
    # milliseconds
    fromtimestamp = datetime.fromtimestamp(seconds)
    return fromtimestamp.strftime('%Y-%m-%d')


def _get_meta():
    # Hard code noon Eastern Time zone since that is where it is built
    body = {
        # size: 0 here to prevent taking too long since we only needed max_date
        "size": 0,
        "aggs": {
            "max_date": {
                "max": {
                    "field": "date_received",
                    "format": "yyyy-MM-dd'T'12:00:00-05:00"
                }
            },
            "max_indexed_date": {
                "max": {
                    "field": "date_indexed",
                    "format": "yyyy-MM-dd'T'12:00:00-05:00"
                }
            },
            "max_narratives": {
                "filter": {"term": {"has_narrative": "true"}},
                "aggs": {
                    "max_date": {
                        "max": {
                            "field": ":updated_at",
                        }
                    }
                }
            }
        }
    }
    max_date_res = _get_es().search(index=_COMPLAINT_ES_INDEX, body=body)
    count_res = _get_es().count(
        index=_COMPLAINT_ES_INDEX,
        doc_type=_COMPLAINT_DOC_TYPE
    )

    result = {
        "license": "CC0",
        "last_updated":
            max_date_res["aggregations"]["max_date"]["value_as_string"],
        "last_indexed":
            max_date_res["aggregations"]["max_indexed_date"]
            ["value_as_string"],
        "total_record_count": count_res["count"],
        "is_data_stale": _is_data_stale(
            max_date_res["aggregations"]["max_date"]["value_as_string"]),
        "is_narrative_stale": _is_data_stale(from_timestamp(
            max_date_res["aggregations"]["max_narratives"]["max_date"]["value"]
        )),
        "has_data_issue": bool(flag_enabled('CCDB_TECHNICAL_ISSUES'))
    }

    return result

# List of possible arguments:
# - format: format to be returned: "json", "csv"
# - field: field you want to search in: "complaint_what_happened",
#   "company_public_response", "_all"
# - size: number of complaints to return
# - frm: from which index to start returning
# - sort: sort by: "relevance_desc", "relevance_asc", "created_date_desc",
#   "created_date_asc"
# - search_term: the term to be searched
# - date_received_min: return only date received including and later than this
#   date i.e. 2017-03-02
# - date_received_max: return only date received before this date, i.e.
#   2017-04-12
# - company_received_min: return only date company received including and later
#   than this date i.e. 2017-03-02
# - company_received_max: return only date company received before this date,
#   i.e. 2017-04-12
# - company: filters a list of companies you want ["Bank 1", "Bank 2"]
# - product: filters a list of product you want if a subproduct is needed to
#   filter, separated by a bullet (u'\u2022), i.e.
#   [u"Mortgage\u2022FHA Mortgage", "Payday Loan"]
# - issue: filters a list of issue you want if a subissue is needed to filter,
#   separated by a bullet (u'\u2022), i.e. See Product above
# - state: filters a list of states you want
# - zip_code: filters a list of zipcodes you want
# - timely: filters a list of whether the company responds in a timely matter
#   or not
# - consumer_disputed: filters a list of dispute resolution
# - company_response: filters a list of response from the company to consumer
# - company_public_response: filters a list of public response from the company
# - consumer_consent_provided: filters a list of whether consumer consent was
#   provided in the complaint
# - has_narrative: filters a list of whether complaint has narratives or not
# - submitted_via: filters a list of ways the complaint was submitted
# - tags - filters a list of tags


def search(agg_exclude=None, **kwargs):
    params = copy.deepcopy(PARAMS)
    params.update(**kwargs)
    search_builder = SearchBuilder()
    search_builder.add(**params)
    body = search_builder.build()
    post_filter_builder = PostFilterBuilder()
    post_filter_builder.add(**params)
    body["post_filter"] = post_filter_builder.build()

    log = logging.getLogger(__name__)
    log.info(
        'Calling %s/%s/%s/_search with %s',
        _ES_URL, _COMPLAINT_ES_INDEX, _COMPLAINT_DOC_TYPE, body
    )

    # format
    res = {}
    format = params.get("format")
    if format == "default":
        if body["size"] > 1000:
            body["size"] = 1000

        if not params.get("no_aggs"):
            aggregation_builder = AggregationBuilder()
            aggregation_builder.add(**params)
            if agg_exclude:
                aggregation_builder.add_exclude(agg_exclude)
            body["aggs"] = aggregation_builder.build()

        res = _get_es().search(index=_COMPLAINT_ES_INDEX,
                               doc_type=_COMPLAINT_DOC_TYPE,
                               body=body,
                               scroll="10m")

        if res['hits']['hits']:
            num_of_scroll = params.get("frm") / body["size"]
            scroll_id = res['_scroll_id']
            if num_of_scroll > 0:
                while num_of_scroll > 0:
                    res['hits']['hits'] = _get_es().scroll(
                        scroll_id=scroll_id,
                        scroll="10m"
                    )['hits']['hits']
                    num_of_scroll -= 1
        res["_meta"] = _get_meta()

    elif format in EXPORT_FORMATS:
        scanResponse = helpers.scan(
            client=_get_es(),
            query=body,
            scroll="10m",
            index=_COMPLAINT_ES_INDEX,
            size=7000,
            doc_type=_COMPLAINT_DOC_TYPE,
            request_timeout=3000
        )

        exporter = ElasticSearchExporter()

        if params.get("format") == 'csv':
            res = exporter.export_csv(
                scanResponse,
                CSV_ORDERED_HEADERS
            )
        elif params.get("format") == 'json':
            if 'highlight' in body:
                del body['highlight']
            body['size'] = 0

            res = _get_es().search(index=_COMPLAINT_ES_INDEX,
                                   doc_type=_COMPLAINT_DOC_TYPE,
                                   body=body,
                                   scroll="10m")
            res = exporter.export_json(scanResponse, res['hits']['total'])

    return res


def suggest(text=None, size=6):
    if text is None:
        return []
    body = {"sgg": {"text": text, "completion": {
        "field": "suggest", "size": size}}}

    res = _get_es().suggest(index=_COMPLAINT_ES_INDEX, body=body)
    candidates = [e['text'] for e in res['sgg'][0]['options']]
    return candidates


def filter_suggest(filterField, display_field=None, **kwargs):
    params = dict(**kwargs)
    params.update({
        'size': 0,
        'no_highlight': True
    })

    search_builder = SearchBuilder()
    search_builder.add(**params)
    body = search_builder.build()

    aggregation_builder = AggregationBuilder()
    aggregation_builder.add(**params)
    aggs = {
        filterField: aggregation_builder.build_one(filterField)
    }
    # add the input value as a must match
    if filterField != 'zip_code':
        aggs[filterField]['filter']['bool']['must'].append(
            {
                'wildcard': {filterField: '*{}*'.format(params['text'])}
            }
        )
    else:
        aggs[filterField]['filter']['bool']['must'].append(
            {
                'prefix': {filterField: params['text']}
            }
        )

    # choose which field to actually display
    aggs[filterField]['aggs'][filterField]['terms'][
        'field'] = filterField if display_field is None else display_field
    # add to the body
    body['aggs'] = aggs

    # format
    res = _get_es().search(
        index=_COMPLAINT_ES_INDEX,
        doc_type=_COMPLAINT_DOC_TYPE,
        body=body
    )
    # reformat the return
    candidates = [
        x['key']
        for x in res['aggregations'][filterField][filterField]['buckets'][:10]
    ]

    return candidates


def document(complaint_id):
    doc_query = {"query": {"term": {"_id": complaint_id}}}
    res = _get_es().search(index=_COMPLAINT_ES_INDEX,
                           doc_type=_COMPLAINT_DOC_TYPE, body=doc_query)
    return res


def states_agg(agg_exclude=None, **kwargs):
    params = copy.deepcopy(PARAMS)
    params.update(**kwargs)
    params.update({'size': 0})
    search_builder = SearchBuilder()
    search_builder.add(**params)
    body = search_builder.build()

    log = logging.getLogger(__name__)
    log.info(
        'Calling %s/%s/%s/states with %s',
        _ES_URL, _COMPLAINT_ES_INDEX, _COMPLAINT_DOC_TYPE, body
    )

    aggregation_builder = StateAggregationBuilder()
    aggregation_builder.add(**params)
    if agg_exclude:
        aggregation_builder.add_exclude(agg_exclude)
    body["aggs"] = aggregation_builder.build()

    res = _get_es().search(index=_COMPLAINT_ES_INDEX,
                           doc_type=_COMPLAINT_DOC_TYPE,
                           body=body,
                           scroll="10m")

    return res


def trends(agg_exclude=None, **kwargs):
    params = copy.deepcopy(PARAMS)
    params.update(**kwargs)
    params.update(size=0)
    search_builder = SearchBuilder()
    search_builder.add(**params)
    body = search_builder.build()

    res_trends = None

    aggregation_builder = TrendsAggregationBuilder()
    aggregation_builder.add(**params)
    if agg_exclude:
        aggregation_builder.add_exclude(agg_exclude)
    body["aggs"] = aggregation_builder.build()

    res_trends = _get_es().search(index=_COMPLAINT_ES_INDEX,
                                  doc_type=_COMPLAINT_DOC_TYPE,
                                  body=body)

    res_date_buckets = None

    date_bucket_body = copy.deepcopy(body)
    date_bucket_body['query'] = {
        "query_string": {
            "query": "*",
            "fields": [
                "_all"
            ],
            "default_operator": "AND"
        }
    }

    date_range_buckets_builder = DateRangeBucketsBuilder()
    date_range_buckets_builder.add(**params)
    date_bucket_body['aggs'] = date_range_buckets_builder.build()

    res_date_buckets = _get_es().search(index=_COMPLAINT_ES_INDEX,
                                        doc_type=_COMPLAINT_DOC_TYPE,
                                        body=date_bucket_body)

    res_trends = process_trends_response(res_trends)
    res_trends['aggregations']['dateRangeBuckets'] = \
        res_date_buckets['aggregations']['dateRangeBuckets']

    return res_trends
