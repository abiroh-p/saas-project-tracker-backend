"""Validation of the report query parameters.

Raises ``QueryParamError``; views translate it into the project's standard 400
response (see ``config.query_params``).
"""
import re
from dataclasses import dataclass
from datetime import date, datetime

from config.query_params import QueryParamError

from .services.trends import INTERVAL_DAY, INTERVALS, MAX_RANGE_DAYS

# Strict ``YYYY-MM-DD`` in ASCII digits. ``date.fromisoformat`` alone would
# also accept other ISO 8601 spellings such as ``20260901``, and ``\d`` would
# accept digits from other scripts (for example full-width ``２０２６``).
_DATE_RE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')

# Dates outside this window cannot hold real data. They are rejected up front
# because the range arithmetic below adds a day to ``date_to`` (and steps
# periods forward), which overflows at ``date.max`` and would be a 500.
MIN_REPORT_DATE = date(1970, 1, 1)
MAX_REPORT_DATE = date(2100, 12, 31)


@dataclass(frozen=True)
class TrendParams:
    date_from: date
    date_to: date
    interval: str


def _get_date(params, name):
    raw = params.get(name)

    if raw is None or not raw.strip():
        raise QueryParamError(f'`{name}` is required (format YYYY-MM-DD).')

    raw = raw.strip()

    if not _DATE_RE.match(raw):
        raise QueryParamError(f'`{name}` must be a date in YYYY-MM-DD format.')

    try:
        value = datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        raise QueryParamError(f'`{name}` is not a valid calendar date.')

    if not MIN_REPORT_DATE <= value <= MAX_REPORT_DATE:
        raise QueryParamError(
            f'`{name}` must be between {MIN_REPORT_DATE.isoformat()} '
            f'and {MAX_REPORT_DATE.isoformat()}.'
        )

    return value


def get_trend_params(params):
    """Validated ``date_from``, ``date_to`` and ``interval`` for trends."""
    date_from = _get_date(params, 'date_from')
    date_to = _get_date(params, 'date_to')

    if date_from > date_to:
        raise QueryParamError('`date_from` must not be after `date_to`.')

    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise QueryParamError(
            f'The date range must be at most {MAX_RANGE_DAYS} days.'
        )

    interval = (params.get('interval') or INTERVAL_DAY).strip()

    if interval not in INTERVALS:
        raise QueryParamError(
            f'`interval` must be one of: {", ".join(INTERVALS)}.'
        )

    return TrendParams(date_from, date_to, interval)
