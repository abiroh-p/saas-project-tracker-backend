"""Issues created and completed over time, for ``reports/trends/``.

Both series come from trustworthy sources only:

* ``created_count`` counts issues by ``Issue.created_at``.
* ``completed_count`` counts ``ISSUE_STATUS_CHANGED`` activity events whose
  new status is DONE, by the time the event was recorded. Status only changes
  through ``transition_issue``, which writes that event in the same
  transaction, and DONE is a terminal status, so each completion is recorded
  exactly once at the moment it happened. ``updated_at`` is never used: it
  moves on every unrelated edit. An issue that was put into DONE some other
  way (a data import, the admin) has no event and is therefore not counted.

Both series use the population of the other reports: non-archived issues of
the project. Calendar dates are interpreted in the configured timezone.
"""
from datetime import datetime, time, timedelta

from django.db.models import Count, Exists, OuterRef
from django.db.models.functions import TruncDate, TruncWeek
from django.utils import timezone

from apps.activity.models import Activity
from apps.issues.models import Issue

from .reports import get_report_issues

INTERVAL_DAY = 'day'
INTERVAL_WEEK = 'week'
INTERVALS = (INTERVAL_DAY, INTERVAL_WEEK)

# Inclusive number of calendar days one request may cover.
MAX_RANGE_DAYS = 366


def _bounds(date_from, date_to, tz):
    """``[start, end)`` datetimes covering both dates in full, in ``tz``."""
    start = datetime.combine(date_from, time.min, tzinfo=tz)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)

    return start, end


def _bucket(interval, tz):
    """Expression that maps a timestamp to its period in ``tz``."""
    if interval == INTERVAL_WEEK:
        return TruncWeek('created_at', tzinfo=tz)

    return TruncDate('created_at', tzinfo=tz)


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date()

    return value


def _count_by_period(queryset, interval, tz):
    rows = (
        queryset
        .annotate(period=_bucket(interval, tz))
        .values('period')
        .annotate(count=Count('id'))
    )

    return {_as_date(row['period'], tz): row['count'] for row in rows}


def _periods(date_from, date_to, interval):
    """Every period start between the dates, so empty periods are present.

    Weeks start on Monday and are labelled by that Monday, which can be before
    ``date_from`` for the first week; its counts still only cover the
    requested dates.
    """
    if interval == INTERVAL_WEEK:
        current = date_from - timedelta(days=date_from.weekday())
        step = timedelta(days=7)
    else:
        current = date_from
        step = timedelta(days=1)

    while current <= date_to:
        yield current
        current += step


def get_trends(project, *, date_from, date_to, interval=INTERVAL_DAY):
    """Created and completed counts per ``interval``, oldest period first.

    ``date_from`` and ``date_to`` are inclusive calendar dates. The caller
    validates them (see ``apps.reports.params``).
    """
    tz = timezone.get_current_timezone()
    start, end = _bounds(date_from, date_to, tz)

    created = _count_by_period(
        get_report_issues(project).filter(
            created_at__gte=start,
            created_at__lt=end,
        ),
        interval,
        tz,
    )

    # ``entity_id`` is not a foreign key, so the visibility of the issue
    # (still in the project, not archived) is checked with a subquery.
    is_reportable_issue = Issue.objects.filter(
        pk=OuterRef('entity_id'),
        project=project,
        is_archived=False,
    )
    completed = _count_by_period(
        Activity.objects
        .filter(
            project=project,
            entity_type=Activity.EntityType.ISSUE,
            action=Activity.Action.ISSUE_STATUS_CHANGED,
            metadata__to=Issue.Status.DONE,
            created_at__gte=start,
            created_at__lt=end,
        )
        .filter(Exists(is_reportable_issue))
        .order_by(),
        interval,
        tz,
    )

    return {
        'project_id': project.pk,
        'interval': interval,
        'date_from': date_from,
        'date_to': date_to,
        'results': [
            {
                'period': period,
                'created_count': created.get(period, 0),
                'completed_count': completed.get(period, 0),
            }
            for period in _periods(date_from, date_to, interval)
        ],
    }
