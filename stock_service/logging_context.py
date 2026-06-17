from __future__ import annotations

import contextvars
import logging


_REQUEST_CONTEXT = contextvars.ContextVar("request_log_context", default={})
DEFAULT_LOG_FIELDS = {
    "request_id": "-",
    "user_id": "-",
    "method": "-",
    "path": "-",
    "event": "-",
    "holding_id": "-",
    "stock_code": "-",
    "command": "-",
    "source": "-",
    "status_code": "-",
    "duration_ms": "-",
    "error_type": "-",
}


def set_request_context(**values):
    context = dict(_REQUEST_CONTEXT.get())
    for key, value in values.items():
        if value is None:
            continue
        context[key] = str(value)
    _REQUEST_CONTEXT.set(context)


def clear_request_context():
    _REQUEST_CONTEXT.set({})


def get_request_context():
    return dict(_REQUEST_CONTEXT.get())


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        context = get_request_context()
        for key, default_value in DEFAULT_LOG_FIELDS.items():
            value = context.get(key, default_value)
            if not hasattr(record, key):
                setattr(record, key, value)
            elif getattr(record, key) in (None, ""):
                setattr(record, key, default_value)
        return True
