from collections import OrderedDict


DEFAULT_PAGINATION_DEPTH = 10000
RESULT_SIZE_DEFAULT = 25
RESULT_SIZE_OPTIONS = [10, 50, 100]

PARAMS = {
    "format": "default",
    "field": "complaint_what_happened",
    "frm": 0,
    "search_after": "",
    "page": 1,
    "no_aggs": False,
    "no_highlight": False,
    "size": RESULT_SIZE_DEFAULT,
    "sort": "relevance_desc",
}

# -*- coding: utf-8 -*-
DELIMITER = '\u2022'

SOURCE_FIELDS = (
    "company",
    "company_public_response",
    "company_response",
    "complaint_id",
    "complaint_what_happened",
    "consumer_consent_provided",
    "consumer_disputed",
    "date_received",
    "date_sent_to_company",
    "has_narrative",
    "issue",
    "product",
    "state",
    "submitted_via",
    "sub_issue",
    "sub_product",
    "tags",
    "timely",
    "zip_code",
)

EXCLUDE_PREFIX = 'not_'

EXPORT_FORMATS = (
    'csv',
    'json',
)

CSV_ORDERED_HEADERS = OrderedDict([
    ("date_received_formatted", "Date received"),
    ("product", "Product"),
    ("sub_product", "Sub-product"),
    ("issue", "Issue"),
    ("sub_issue", "Sub-issue"),
    ("complaint_what_happened", "Consumer complaint narrative"),
    ("company_public_response", "Company public response"),
    ("company", "Company"),
    ("state", "State"),
    ("zip_code", "ZIP code"),
    ("tags", "Tags"),
    ("consumer_consent_provided", "Consumer consent provided?"),
    ("submitted_via", "Submitted via"),
    ("date_sent_to_company_formatted", "Date sent to company"),
    ("company_response", "Company response to consumer"),
    ("timely", "Timely response?"),
    ("consumer_disputed", "Consumer disputed?"),
    ("complaint_id", "Complaint ID")
])

AGG_EXCLUDE_FIELDS = ['company', 'zip_code']

CHUNK_SIZE = 512

FORMAT_CONTENT_TYPE_MAP = {
    "json": "application/json",
    "csv": "text/csv",
}

DATA_SUB_LENS_MAP = {
    'product': ('sub_product', 'issue', 'company', 'tags'),
    'issue': ('product', 'sub_issue', 'company', 'tags'),
    'company': ('product', 'issue', 'tags'),
    'tags': ('product', 'issue', 'company'),
}
