import copy
import logging
import os
from datetime import datetime, timedelta

from complaint_search.defaults import (
    CSV_ORDERED_HEADERS,
    DEFAULT_PAGINATION_DEPTH,
    EXPORT_FORMATS,
    PARAMS,
)
from complaint_search.es_builders import (
    AggregationBuilder,
    CountBuilder,
    DateRangeBucketsBuilder,
    PostFilterBuilder,
    SearchBuilder,
    StateAggregationBuilder,
    TrendsAggregationBuilder,
)
from complaint_search.export import ElasticSearchExporter
from elasticsearch7 import Elasticsearch, RequestsHttpConnection, helpers
from flags.state import flag_enabled
from requests_aws4auth import AWS4Auth


log = logging.getLogger(__name__)

_ES_URL = "{}://{}:{}".format("http", os.environ.get('ES_HOST', 'localhost'),
                              os.environ.get('ES_PORT', '9200'))
_ES_USER = os.environ.get('ES_USER', '')
_ES_PASSWORD = os.environ.get('ES_PASSWORD', '')

_ES_INSTANCE = None

USE_AWS_ES = os.environ.get('USE_AWS_ES', False)
AWS_ES_ACCESS_KEY = os.environ.get('AWS_ES_ACCESS_KEY')
AWS_ES_SECRET_KEY = os.environ.get('AWS_ES_SECRET_KEY')
# The below was configured because of a naming convention chosen by
# CF.gov for ES7 Host. May require changing if var name changed
# https://github.com/cfpb/consumerfinance.gov/blob/main/.env_SAMPLE#L92
AWS_ES_HOST = os.environ.get('ES7_HOST')


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


def get_break_points(hits, size):
    """Return a dict of 'search-after' values for pagination."""
    end_page = int(DEFAULT_PAGINATION_DEPTH / size) - 1
    break_points = {}
    if size > len(hits):
        return break_points
    # we don't need a break point for page 1; start with page 2
    page = 2
    break_points[page] = hits[size - 1].get("sort")
    next_batch = hits[size:]
    while page < end_page and len(next_batch) > size:
        page += 1
        break_points[page] = next_batch[size - 1].get("sort")
        next_batch = next_batch[size:]
    return break_points


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
        if USE_AWS_ES:
            awsauth = AWS4Auth(
                AWS_ES_ACCESS_KEY,
                AWS_ES_SECRET_KEY,
                'us-east-1',
                'es'
            )
            _ES_INSTANCE = Elasticsearch(
                hosts=[{'host': AWS_ES_HOST, 'port': 443}],
                http_auth=awsauth,
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
                timeout=100
            )
        else:
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
        index=_COMPLAINT_ES_INDEX
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
        # TODO: remove is_narrative_stale -- no longer used
        # "is_narrative_stale": _is_data_stale(from_timestamp(
        #     max_date_res["aggregations"]["max_narratives"]["max_date"]["value"]
        # )),
        "has_data_issue": bool(flag_enabled('CCDB_TECHNICAL_ISSUES'))
    }

    return result


def _extract_count(params):
    """Consult the count API for an accurate hit count regardless of size."""
    count_builder = CountBuilder()
    count_builder.add(**params)
    body = count_builder.build()
    res = _get_es().count(index=_COMPLAINT_ES_INDEX, body=body)
    return res.get("count")


def test_float(value):
    try:
        _float = float(value)
    except Exception:
        return
    return _float


def parse_search_after(params):
    """Validate search_after and return it as a list of [score, ID]."""
    search_pair = params.get("search_after")
    sort = params.get("sort")
    if not search_pair or not sort:
        return
    if '_' not in search_pair or len(search_pair.split("_")) != 2:
        return
    _score, _id = search_pair.split("_")
    _sort = sort.split("_")[0]
    if _sort not in ["relevance", "created"]:
        log.error("{} is not a supported sort value.".format(_sort))
        return
    if _sort == "relevance":
        score = test_float(_score)
        if score is None:
            log.error("Search_after relevance score is not a float.")
            return
    elif _sort == "created":
        if not str(_score).isdigit():
            log.error("Search_after date score is not an integer.")
            return
        score = int(_score)
    return [score, _id]


def search(agg_exclude=None, **kwargs):
    params = copy.deepcopy(PARAMS)
    params.update(**kwargs)
    search_after = parse_search_after(params)
    if search_after:
        params["search_after"] = search_after
    search_builder = SearchBuilder()
    search_builder.add(**params)
    body = search_builder.build()
    post_filter_builder = PostFilterBuilder()
    post_filter_builder.add(**params)
    body["post_filter"] = post_filter_builder.build()
    # format
    res = {}
    _format = params.get("format")
    if _format == "default":
        if not params.get("no_aggs"):
            aggregation_builder = AggregationBuilder()
            aggregation_builder.add(**params)
            if agg_exclude:
                aggregation_builder.add_exclude(agg_exclude)
            body["aggs"] = aggregation_builder.build()
        log.info(
            'Requesting %s/%s/_search with %s',
            _ES_URL, _COMPLAINT_ES_INDEX, body
        )
        res = _get_es().search(index=_COMPLAINT_ES_INDEX, body=body)
        hit_total = _extract_count(params)
        res['hits']['total']['value'] = hit_total
        break_points = {}
        # page = 1
        if res['hits']['hits']:
            # if body.get("frm") and body.get("size"):
            #     page = body["frm"] / body["size"] + 1
            if hit_total and hit_total > body["size"]:
                # We have more than one page of results and need pagination
                pagination_body = copy.deepcopy(body)
                pagination_body["size"] = DEFAULT_PAGINATION_DEPTH
                if "search_after" in pagination_body:
                    del pagination_body["search_after"]
                log.info(
                    'Harvesting pagination dict using %s/%s/_search with %s',
                    _ES_URL, _COMPLAINT_ES_INDEX, pagination_body
                )
                pagination_res = _get_es().search(
                    index=_COMPLAINT_ES_INDEX,
                    body=pagination_body
                )
                break_points = get_break_points(
                    pagination_res['hits']['hits'], body["size"])
        res["_meta"] = _get_meta()
        res["_meta"]["break_points"] = break_points

    elif _format in EXPORT_FORMATS:
        scan_response = helpers.scan(
            client=_get_es(),
            query=body,
            scroll="10m",
            index=_COMPLAINT_ES_INDEX,
            size=7000,
            request_timeout=3000
        )

        exporter = ElasticSearchExporter()

        if params.get("format") == 'csv':
            res = exporter.export_csv(
                scan_response,
                CSV_ORDERED_HEADERS
            )
        elif params.get("format") == 'json':
            if 'highlight' in body:
                del body['highlight']
            body['size'] = 0

            res = _get_es().search(index=_COMPLAINT_ES_INDEX,
                                   body=body,
                                   scroll="10m")
            res = exporter.export_json(scan_response, res['hits']['total'])

    return res


def suggest(text=None, size=6):
    if text is None:
        return []
    body = {
        "_source": False,
        "suggest": {
            "sgg": {
                "text": text,
                "completion": {
                    "field": "typeahead_dropdown",
                    "skip_duplicates": True,
                    "size": size
                }}}}

    res = _get_es().search(index=_COMPLAINT_ES_INDEX, body=body)
    candidates = [e['text'] for e in res['suggest']['sgg'][0]['options']]
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
    res = _get_es().search(index=_COMPLAINT_ES_INDEX, body=doc_query)
    return res


def states_agg(agg_exclude=None, **kwargs):
    params = copy.deepcopy(PARAMS)
    params.update(**kwargs)
    params.update({'size': 500})
    search_builder = SearchBuilder()
    search_builder.add(**params)
    body = search_builder.build()
    log.info(
        'Calling %s/%s/%s/states with %s',
        _ES_URL, _COMPLAINT_ES_INDEX, _COMPLAINT_DOC_TYPE, body,
    )
    log.info(
        'Params are %s', params)

    aggregation_builder = StateAggregationBuilder()
    aggregation_builder.add(**params)
    if agg_exclude:
        aggregation_builder.add_exclude(agg_exclude)
    body["aggs"] = aggregation_builder.build()

    res = _get_es().search(
        index=_COMPLAINT_ES_INDEX,
        body=body
    )
    hit_total = _extract_count(params)
    res['hits']['total']['value'] = hit_total

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
                                  body=body)

    res_date_buckets = None

    date_bucket_body = copy.deepcopy(body)
    date_bucket_body['query'] = {
        "match_all": {}
    }

    date_range_buckets_builder = DateRangeBucketsBuilder()
    date_range_buckets_builder.add(**params)
    date_bucket_body['aggs'] = date_range_buckets_builder.build()

    res_date_buckets = _get_es().search(index=_COMPLAINT_ES_INDEX,
                                        body=date_bucket_body)

    res_trends = process_trends_response(res_trends)
    res_trends['aggregations']['dateRangeBuckets'] = \
        res_date_buckets['aggregations']['dateRangeBuckets']

    res_trends['aggregations']['dateRangeBuckets']['body'] = date_bucket_body

    return res_trends
