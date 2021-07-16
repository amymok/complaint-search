import logging

from elasticsearch7 import TransportError
from rest_framework import status
from rest_framework.response import Response


log = logging.getLogger(__name__)


def catch_es_error(function):
    def wrap(request, *args, **kwargs):
        try:
            return function(request, *args, **kwargs)
        except TransportError as te:
            log.error(te)

            status_code = 424  # HTTP_424_FAILED_DEPENDENCY
            res = {
                "error": 'There was an error calling Elasticsearch'
            }
            return Response(res, status=status_code)
        except Exception as e:
            log.error(e)

            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            res = {
                "error": 'There was a problem retrieving your request'
            }
            return Response(res, status=status_code)
    wrap.__doc__ = function.__doc__
    wrap.__name__ = function.__name__
    return wrap
