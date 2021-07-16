import abc
import copy
import re
from collections import OrderedDict, defaultdict

from complaint_search.defaults import (
    DATA_SUB_LENS_MAP,
    DELIMITER,
    EXCLUDE_PREFIX,
    EXPORT_FORMATS,
    PARAMS,
    SOURCE_FIELDS,
)


def is_all_field(field):
    return field in ['all', '_all']


def build_search_terms(search_term, field):
    has_symbols = re.match(r"^[A-Za-z\d\s]+$", search_term) is None
    has_keywords = any(
        keyword in search_term for keyword in ("AND", "OR", "NOT", "TO")
    )
    all_fields = is_all_field(field)

    if has_symbols or has_keywords:
        return {
            "query_string": {
                "query": search_term,
                "default_field": '*' if all_fields else field
            }
        }

    elif all_fields:
        return {
            "query_string": {
                "query": search_term,
                "default_field": '*',
                "default_operator": "AND"
            }
        }

    # Specific field with no keywords
    return {
        "match": {
            field: {
                "query": search_term,
                "operator": "and"
            }
        }
    }


class BaseBuilder(object):
    __metaclass__ = abc.ABCMeta

    # Filters for those with string type
    _OPTIONAL_FILTERS = (
        "company",
        "company_public_response",
        "company_response",
        "consumer_consent_provided",
        "consumer_disputed",
        "has_narrative",
        "issue",
        "product",
        "state",
        "submitted_via",
        "tags",
        "timely",
        "zip_code",
    )

    # Filters that use different names in Elasticsearch
    _OPTIONAL_FILTERS_PARAM_TO_ES_MAP = {
        "company_public_response": "company_public_response.raw",
        "company": "company.raw",
        "consumer_consent_provided": "consumer_consent_provided.raw",
        "consumer_disputed": "consumer_disputed.raw",
        "issue": "issue.raw",
        "product": "product.raw",
        "sub_issue": "sub_issue.raw",
        "sub_product": "sub_product.raw",
    }

    # Filters that have a child and this maps to their child's name
    _OPTIONAL_FILTERS_CHILD_MAP = {
        "issue": "sub_issue",
        "product": "sub_product",
    }

    def _get_es_name(self, field):
        return self._OPTIONAL_FILTERS_PARAM_TO_ES_MAP.get(field, field)

    def _has_child(self, field):
        return field in self._OPTIONAL_FILTERS_CHILD_MAP

    def _get_child(self, field):
        return self._OPTIONAL_FILTERS_CHILD_MAP.get(field)

    def __init__(self):
        self.params = {}

    def add(self, **kwargs):
        self.params.update(**kwargs)

    @abc.abstractmethod
    def build(self):
        """Method that will build the body dictionary."""

    # This creates all the bool should filter clauses for a field
    def _build_bool_clauses(self, field, value_list):
        assert value_list

        es_field_name = self._get_es_name(field)

        # The most common property for data is to not have a child element
        if not self._has_child(field):
            return {
                "terms": {
                    es_field_name: value_list
                }}

        else:
            item_dict = defaultdict(list)
            for v in value_list:
                v_pair = v.split(DELIMITER)
                # No child specified
                if len(v_pair) == 1:
                    # This will initialize empty list for item if not in
                    # item_dict yet
                    item_dict[v_pair[0]]
                elif len(v_pair) == 2:
                    # put subproduct into list
                    item_dict[v_pair[0]].append(v_pair[1])

            # Go through item_dict to create filters
            f_list = []
            for item, child in item_dict.items():
                # Always append the item to list
                parent_term = {"term": {es_field_name: item}}
                if not child:
                    f_list.append(parent_term)
                else:
                    child_field = self._get_es_name(self._get_child(field))
                    child_term = {
                        "terms": {
                            child_field: child
                        }
                    }
                    parent_child_bool_structure = {
                        "bool": {
                            "must": [
                                parent_term,
                                child_term
                            ],
                        }
                    }

                    f_list.append(parent_child_bool_structure)

            return f_list

    # This creates two dictionaries where the keys are the field name
    # dictionary 1: the conditions for including a record in the query
    # dictionary 2: the conditions for excluding a record in the query

    def _build_clauses_dictionary(self):
        include_clauses = OrderedDict()
        exclude_clauses = OrderedDict()
        for item in self._OPTIONAL_FILTERS:
            values = self.params.get(item)
            if values:
                include_clauses[item] = self._build_bool_clauses(item, values)

            # handle the not item case
            values = self.params.get(EXCLUDE_PREFIX + item)
            if values:
                exclude_clauses[item] = self._build_bool_clauses(item, values)

        return include_clauses, exclude_clauses

    def _build_date_range_filter(self, date_min, date_max, es_field_name):
        # 2019-10-17 JMF - Tests fails when using "from builtins import str"
        # The result gets flagged as "bad type" since type = future.types. ...
        try:
            _fn = unicode  # PY2
        except NameError:
            _fn = str  # PY3

        date_clause = {}
        if date_min or date_max:
            date_clause = {"range": {es_field_name: {}}}
            if date_min:
                date_clause["range"][es_field_name]["from"] = _fn(date_min)
            if date_max:
                date_clause["range"][es_field_name]["to"] = _fn(date_max)

        return date_clause

    def _build_dsl_filter(self, include_clauses, exclude_clauses,
                          include_dates=True, single_not_clause=True):
        and_clauses = []

        # date_received
        date_received = self._build_date_range_filter(
            self.params.get("date_received_min"),
            self.params.get("date_received_max"),
            "date_received")

        if date_received and include_dates:
            and_clauses.append(date_received)

        company_filter = self._build_date_range_filter(
            self.params.get("company_received_min"),
            self.params.get("company_received_max"), "date_sent_to_company")

        if company_filter:
            and_clauses.append(company_filter)

        # Create filter clauses for all other filters
        for item, clauses in include_clauses.items():
            if not self._has_child(item):
                # Create the field level AND query that must match
                and_clauses.append(clauses)
            else:
                # These get added as compound OR clauses
                or_clause = {"bool": {"should": clauses}}
                and_clauses.append(or_clause)

        not_clauses = []
        for item, clauses in exclude_clauses.items():
            if not self._has_child(item):
                # Create the field level AND query that must match
                not_clauses.append(clauses)
            else:
                # These get added as compound OR clauses
                or_clause = {"bool": {"should": clauses}}
                not_clauses.append(or_clause)

        # if there are multiple not clauses, they need to be grouped
        # ~A AND ~B AND ~C is not the same as ~(A AND B AND C)
        if len(not_clauses) > 1 and single_not_clause:
            grouping = {"bool": {"must": not_clauses}}
            not_clauses = [grouping]

        return {"bool": {"must": and_clauses, "must_not": not_clauses}}


class CountBuilder(BaseBuilder):
    def __init__(self):
        self.params = copy.deepcopy(PARAMS)

    def build(self):
        include_clauses, exclude_clauses = self._build_clauses_dictionary()
        query_body = self._build_dsl_filter(include_clauses, exclude_clauses)
        query = {"query": query_body}
        return query


class SearchBuilder(BaseBuilder):
    def __init__(self):
        self.params = copy.deepcopy(PARAMS)

    def _build_highlight(self):
        highlight = {
            "require_field_match": False,
            "number_of_fragments": 1,
            "fragment_size": 500
        }
        if is_all_field(self.params.get("field")):
            highlight["fields"] = {"*": {}}
        else:
            highlight["fields"] = {self.params.get("field"): {}}

        return highlight

    def _build_sort(self):
        sort_field_mapping = {
            "relevance": "_score",
            "created_date": "date_received"
        }
        sort_field, sort_order = self.params.get("sort").rsplit("_", 1)
        sort_field = sort_field_mapping.get(sort_field, "_score")
        return [{sort_field: {"order": sort_order}}, {"_id": sort_order}]

    def _build_source(self):
        source = list(SOURCE_FIELDS)
        if self.params.get("format") in EXPORT_FORMATS:
            source.remove('has_narrative')
        if self.params.get("format") == 'csv':
            source.remove('date_received')
            source.remove('date_sent_to_company')
            source.append('date_received_formatted')
            source.append('date_sent_to_company_formatted')
        return source

    def build(self):
        search = {
            "size": self.params.get("size"),
            "_source": self._build_source()
        }
        # Highlight
        if not self.params.get("no_highlight") and \
                not self.params.get("size") == 0:
            search["highlight"] = self._build_highlight()

        # sort
        if not self.params.get("size") == 0:
            search["sort"] = self._build_sort()

        # query
        search_term = self.params.get("search_term")
        if search_term:
            search["query"] = build_search_terms(
                search_term, self.params.get("field"))

        # pagination
        search_after = self.params.get("search_after")
        if search_after:
            search["search_after"] = search_after

        return search


class PostFilterBuilder(BaseBuilder):

    def build(self):
        include_clauses, exclude_clauses = self._build_clauses_dictionary()
        return self._build_dsl_filter(include_clauses, exclude_clauses)


class AggregationBuilder(BaseBuilder):
    _AGG_FIELDS = (
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

    def __init__(self):
        BaseBuilder.__init__(self)
        self.include_clauses = None
        self.exclude_clauses = None
        self.exclude = []

    def add_exclude(self, field_name_list):
        self.exclude += field_name_list

    def build_parent_child_field_agg(
        self, agg_heading_name, es_parent_name, es_child_name
    ):
        return {
            agg_heading_name: {
                "terms": {
                    "field": es_parent_name
                },
                "aggs": {
                    es_child_name: {
                        "terms": {
                            "field": es_child_name
                        }
                    }
                }
            }
        }

    def build_one(self, field_name):
        # Lazy initialization
        if not self.include_clauses:
            self.include_clauses, self.exclude_clauses = \
                self._build_clauses_dictionary()

        field_aggs = {}

        es_field_name = self._OPTIONAL_FILTERS_PARAM_TO_ES_MAP.get(
            field_name, field_name
        )
        es_child_name = None

        if field_name in self._OPTIONAL_FILTERS_CHILD_MAP:
            es_child_name = self._OPTIONAL_FILTERS_PARAM_TO_ES_MAP.get(
                self._OPTIONAL_FILTERS_CHILD_MAP.get(field_name))
            field_aggs["aggs"] = self.build_parent_child_field_agg(
                field_name,
                es_field_name,
                es_child_name
            )
        else:
            field_aggs["aggs"] = {
                field_name: {
                    "terms": {
                        "field": es_field_name
                    }
                }
            }

        # Create a subset of the filters
        incl_subset = {
            k: v
            for k, v in self.include_clauses.items()
            if k != field_name
        }

        # Add the aggregation filters
        field_aggs['filter'] = self._build_dsl_filter(incl_subset,
                                                      self.exclude_clauses)
        return field_aggs

    def build(self):
        aggs = {}

        agg_fields = self._AGG_FIELDS
        if self.exclude:
            agg_fields = [
                field_name for field_name in self._AGG_FIELDS
                if field_name not in self.exclude or field_name in self.params
            ]
        for field_name in agg_fields:
            aggs[field_name] = self.build_one(field_name)

        return aggs


class StateAggregationBuilder(BaseBuilder):
    _AGG_FIELDS = (
        'issue',
        'product',
        'state',
    )

    _AGG_SIZES = {
        'state': 100,
        'product.raw': 5,
        'issue.raw': 5
    }

    _ES_CHILD_AGG_MAP = {
        'product.raw': 'sub-product',
        'sub_product.raw': 'product',
        'issue.raw': 'sub-issue',
        'sub_issue.raw': 'issue',
        'tags': 'tags'
    }

    def __init__(self):
        BaseBuilder.__init__(self)
        self.include_clauses = None
        self.exclude_clauses = None
        self.exclude = []

    def add_exclude(self, field_name_list):
        self.exclude += field_name_list

    def build_one(self, field_name):
        # Lazy initialization
        if not self.include_clauses:
            self.include_clauses, self.exclude_clauses = \
                self._build_clauses_dictionary()

        field_aggs = {
            "filter": {

            }
        }

        es_field_name = self._OPTIONAL_FILTERS_PARAM_TO_ES_MAP.get(
            field_name, field_name
        )
        es_child_name = self._OPTIONAL_FILTERS_PARAM_TO_ES_MAP.get(
            self._OPTIONAL_FILTERS_CHILD_MAP.get(field_name))

        field_aggs["aggs"] = {
            field_name: {
                "terms": {
                    "field": es_field_name,
                    "size": self._AGG_SIZES.get(es_field_name)
                },
                "aggs": {
                    self._ES_CHILD_AGG_MAP.get(es_child_name): {
                        "terms": {
                            "field": es_child_name
                        }
                    }
                }
            }
        }

        # Get top product & issue for each state. Don't apply state filter
        # to itself
        if field_name == 'state':
            field_aggs["aggs"]["state"]["aggs"] = {
                "product": {
                    "terms": {
                        "field": "product.raw"
                    }
                },
                "issue": {
                    "terms": {
                        "field": "issue.raw"
                    }
                }
            }

            filtered_includes = copy.deepcopy(self.include_clauses)
            if 'state' in filtered_includes:
                del filtered_includes['state']

            field_aggs['filter'] = self._build_dsl_filter(filtered_includes,
                                                          self.exclude_clauses)
        else:
            field_aggs['filter'] = self._build_dsl_filter(self.include_clauses,
                                                          self.exclude_clauses)

        return field_aggs

    def build(self):
        aggs = {}

        agg_fields = self._AGG_FIELDS
        if self.exclude:
            agg_fields = [field_name for field_name in self._AGG_FIELDS
                          if field_name not in self.exclude]
        for field_name in agg_fields:
            aggs[field_name] = self.build_one(field_name)

        return aggs


class LensAggregationBuilder(BaseBuilder):
    _ES_CHILD_AGG_MAP = {
        'product.raw': 'sub-product',
        'sub_product.raw': 'product',
        'issue.raw': 'sub-issue',
        'sub_issue.raw': 'issue',
        'tags': 'tags'
    }

    def __init__(self):
        super(LensAggregationBuilder, self).__init__()
        self._include_clauses = None
        self.exclude_clauses = None
        self.exclude = []

    @property
    def include_clauses(self):
        if not self._include_clauses:
            self._include_clauses, self.exclude_clauses = \
                self._build_clauses_dictionary()
        return self._include_clauses

    def add_exclude(self, field_name_list):
        self.exclude += field_name_list

    def build_histogram(self, agg_name, interval, include_date_filter):
        agg = {
            "aggs": {
                agg_name: {
                    "date_histogram": {
                        "field": "date_received",
                        "interval": interval
                    }
                }
            }
        }

        # Add filter clauses
        agg['filter'] = self._build_dsl_filter(
            self.include_clauses, self.exclude_clauses,
            include_dates=include_date_filter,
            single_not_clause=False
        )

        return agg

    def date_extreme(self, extreme):
        return {
            extreme: {
                "field": "date_received",
                "format": "yyyy-MM-dd'T'12:00:00-05:00"
            }
        }


class TrendsAggregationBuilder(LensAggregationBuilder):
    _AGG_FIELDS = (
        'issue',
        'tags',
        'product'
    )

    _AGG_HEADING_MAP = {
        'issue': 'issue',
        'product': 'product',
        'sub_product': 'sub-product',
        'sub_issue': 'sub-issue',
        'tags': 'tags',
    }

    def __init__(self):
        super(TrendsAggregationBuilder, self).__init__()

    def percent_change_agg(self, es_field_name, interval, trend_depth):
        return {
            "terms": {
                "field": es_field_name
            },
            "aggs": {
                "trend_period": {
                    "date_histogram": {
                        "field": "date_received",
                        "interval": interval
                    },
                    "aggs": {
                        "interval_diff": {
                            "serial_diff": {"buckets_path": "_count"}
                        }
                    }
                }
            }
        }

    def get_agg_heading(self, field_name):
        return self._AGG_HEADING_MAP.get(field_name, field_name)

    def agg_setup(self, field_name, agg_heading_name, interval):
        field_aggs = {
            "aggs": {}
        }

        es_field_name = self._OPTIONAL_FILTERS_PARAM_TO_ES_MAP.get(
            field_name, field_name
        )

        field_aggs["aggs"][agg_heading_name] = self.percent_change_agg(
            es_field_name, interval, self.params['trend_depth'])

        # Add the filters
        field_aggs['filter'] = self._build_dsl_filter(
            self.include_clauses, self.exclude_clauses, single_not_clause=False
        )

        return field_aggs

    def build_one_overview(self, field_name, agg_heading_name, interval):
        field_aggs = self.agg_setup(field_name, agg_heading_name, interval)

        if field_name in self._OPTIONAL_FILTERS_CHILD_MAP:
            es_child_name = self._OPTIONAL_FILTERS_PARAM_TO_ES_MAP.get(
                self._OPTIONAL_FILTERS_CHILD_MAP.get(field_name))
            child_agg_name = self._ES_CHILD_AGG_MAP.get(es_child_name)
            field_aggs["aggs"][agg_heading_name]["aggs"][child_agg_name] = \
                self.percent_change_agg(es_child_name, interval, 0)

        return field_aggs

    def build_one_lens(self, field_name, agg_heading_name, interval, sub_lens):
        field_aggs = self.agg_setup(field_name, agg_heading_name, interval)

        es_child_name = self._OPTIONAL_FILTERS_PARAM_TO_ES_MAP.get(
            sub_lens)
        child_agg_name = self._ES_CHILD_AGG_MAP.get(es_child_name)
        field_aggs["aggs"][agg_heading_name]["aggs"][child_agg_name] = \
            self.percent_change_agg(es_child_name, interval,
                                    self.params['sub_lens_depth'])

        return field_aggs

    def focus_filter(self):
        return {
            'term': {
                self._OPTIONAL_FILTERS_PARAM_TO_ES_MAP.get(
                    self.params['lens']): self.params['focus']
            }
        }

    def build_one_focus(self, field_name, agg_heading_name, interval):
        field_aggs = self.agg_setup(field_name, agg_heading_name, interval)

        field_aggs['filter']['bool']['must'].append(self.focus_filter())

        return field_aggs

    def build(self):
        # AZ - Only include a company aggregation if at least one company
        # filter is selected
        if 'company' in self.params and 'company' in self.exclude:
            self.exclude.remove('company')
            self._AGG_FIELDS + ('company',)
            self._AGG_HEADING_MAP['company'] = 'company'

        aggs = {}

        aggs['dateRangeArea'] = self.build_histogram(
            'dateRangeArea', self.params['trend_interval'], True)
        aggs['dateRangeBrush'] = self.build_histogram(
            'dateRangeBrush', self.params['trend_interval'], False)

        if self.params['lens'] == 'overview':
            # Reset default for overview row charts
            self.params['trend_depth'] = 5

            for field_name in self._AGG_FIELDS:
                if field_name not in self.exclude:
                    agg_heading_name = self.get_agg_heading(field_name)

                    aggs[agg_heading_name] = self.build_one_overview(
                        field_name,
                        agg_heading_name,
                        self.params['trend_interval']
                    )
        elif 'focus' in self.params:
            for field_name in DATA_SUB_LENS_MAP.get(self.params['lens']) \
                    + (self.params['lens'], ):
                if field_name == 'company' and 'company' not in self.params:
                    # Do not include company agg unless there is a company
                    # filter
                    continue
                agg_heading_name = self.get_agg_heading(field_name)

                aggs[agg_heading_name] = self.build_one_focus(
                    field_name,
                    agg_heading_name,
                    self.params['trend_interval']
                )

            aggs['dateRangeArea']['filter']['bool']['must']\
                .append(self.focus_filter())
            aggs['dateRangeBrush']['filter']['bool']['must']\
                .append(self.focus_filter())

        else:
            agg_heading_name = self.get_agg_heading(self.params['lens'])

            aggs[agg_heading_name] = self.build_one_lens(
                self.params['lens'],
                agg_heading_name,
                self.params['trend_interval'],
                self.params['sub_lens']
            )

        aggs['min_date'] = self.date_extreme('min')
        aggs['max_date'] = self.date_extreme('max')
        return aggs


class DateRangeBucketsBuilder(BaseBuilder):
    def build(self):
        agg = {
            'dateRangeBuckets': {
                'aggs': {
                    'dateRangeBuckets': {
                        "date_histogram": {
                            "field": "date_received",
                            "calendar_interval": self.params.get(
                                'trend_interval', 5)
                        }
                    }
                }
            }
        }

        # Add date filter clause
        agg['dateRangeBuckets']['filter'] = self._build_dsl_filter(
            {}, {}, include_dates=True, single_not_clause=False
        )

        return agg
