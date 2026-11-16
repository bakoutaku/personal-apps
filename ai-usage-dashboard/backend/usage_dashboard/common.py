import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone

API_VERSION = '0.2.0'
MAX_INTEGER = 9007199254740991
COMPONENTS = ('uncached_input_tokens', 'cache_read_input_tokens', 'cache_write_input_tokens', 'output_tokens')
EPOCH = datetime(1970,1,1,tzinfo=timezone.utc)
PRODUCTS = {'gpt': ('chat', 'work', 'codex'), 'claude': ('chat', 'code', 'cowork')}


class APIError(Exception):
    def __init__(self, status, code, message, field=None, headers=None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details = [] if field is None else [{'field': field, 'reason': message}]
        self.headers = headers or {}


def now_ms():
    return time.time_ns() // 1000000


def parse_time(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?(?:Z|[+-]\d\d:\d\d)', value):
        raise ValueError('RFC3339 with timezone and at most millisecond precision required')
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    delta = d.astimezone(timezone.utc)-EPOCH
    return delta.days*86400000+delta.seconds*1000+delta.microseconds//1000


def iso(value):
    return None if value is None else (EPOCH+timedelta(milliseconds=value)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def ident(prefix, *values):
    return prefix + '_' + hashlib.sha256(canonical(values).encode()).hexdigest()[:32]


def token_int(value):
    return value if type(value) is int and 0 <= value <= MAX_INTEGER else None


def empty_components():
    return dict.fromkeys(COMPONENTS)
