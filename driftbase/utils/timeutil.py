import datetime

from dateutil import parser as dateutil_parser
from drift.timeutil import ensure_utc, parse_utc as parse_iso_utc


def parse_utc(value: str) -> datetime.datetime:
    """
    Parse a timestamp sent by a client into an aware UTC datetime.
    Falls back to dateutil for the lenient formats clients could send before.
    """
    try:
        return parse_iso_utc(value)
    except ValueError:
        return ensure_utc(dateutil_parser.parse(value))
