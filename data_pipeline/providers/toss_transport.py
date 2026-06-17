import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from .toss_exceptions import TossOpenApiError


class SimpleTossResponse:
    def __init__(self, status_code: int, data: Any, headers: Mapping[str, str] | None = None):
        self.status_code = status_code
        self._data = data
        self.headers = dict(headers or {})

    def json(self):
        return self._data


def urllib_form_transport(method, url, *, headers=None, data=None, json=None, params=None, timeout=None):
    if method.upper() != "POST":
        raise TossOpenApiError("Toss form transport only supports POST requests.")
    if json is not None:
        raise TossOpenApiError("Toss form transport does not send JSON request bodies.")

    request_url = _build_url(url, params=params)
    request_data = urllib.parse.urlencode(data or {}).encode("utf-8")
    request = urllib.request.Request(
        request_url,
        data=request_data,
        headers=dict(headers or {}),
        method=method.upper(),
    )
    return _open_json_request(request, timeout=timeout)


def urllib_json_transport(method, url, *, headers=None, params=None, data=None, json=None, timeout=None):
    if method.upper() != "GET":
        raise TossOpenApiError("Toss JSON transport only supports GET requests.")
    if data is not None or json is not None:
        raise TossOpenApiError("Toss JSON transport does not send request bodies for GET requests.")

    request_url = _build_url(url, params=params)
    request = urllib.request.Request(
        request_url,
        headers=dict(headers or {}),
        method=method.upper(),
    )
    return _open_json_request(request, timeout=timeout)


def _build_url(url, *, params=None):
    parsed_url = urllib.parse.urlparse(str(url))
    query = urllib.parse.urlencode(params or {})
    return urllib.parse.urlunparse(parsed_url._replace(query=query))


def _open_json_request(request, *, timeout=None):
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return SimpleTossResponse(
                response.getcode(),
                _load_response_json(response.read()),
                headers=dict(response.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        return SimpleTossResponse(
            exc.code,
            _load_response_json(exc.read()),
            headers=dict(exc.headers.items()) if exc.headers else {},
        )
    except urllib.error.URLError as exc:
        raise TossOpenApiError("Toss endpoint request failed.") from exc


def _load_response_json(raw_body):
    if not raw_body:
        return {}
    try:
        return json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"error": "invalid_json_response"}
