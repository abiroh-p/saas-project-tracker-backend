"""Search, filtering and ordering for the project issue list.

The caller passes in a queryset that is already limited to what the requester
may see (their project, not archived). Everything here only narrows it, and
different parameters combine with AND.

Unknown query parameters are ignored, as they were before this module existed.
"""
import re
from datetime import date

from django.db.models import Case, F, IntegerField, Q, Value, When
from django.db.models.functions import Lower

from config.query_params import QueryParamError, get_search_term

from .models import Issue

# Largest value a PositiveIntegerField / integer primary key can hold. Larger
# numbers can never match a row (Django would just return nothing), so they
# are treated as invalid ids instead of being sent to the database.
MAX_DB_INTEGER = 2_147_483_647

_ISSUE_KEY_PATTERN = re.compile(r'^([A-Za-z0-9]+)-([0-9]+)$')
_ISO_DATE_PATTERN = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')

# Rank so that priority sorts by urgency rather than alphabetically.
_PRIORITY_RANK = Case(
    When(priority=Issue.Priority.LOW, then=Value(1)),
    When(priority=Issue.Priority.MEDIUM, then=Value(2)),
    When(priority=Issue.Priority.HIGH, then=Value(3)),
    When(priority=Issue.Priority.URGENT, then=Value(4)),
    default=Value(0),
    output_field=IntegerField(),
)

ORDERING_FIELDS = (
    'created_at',
    'updated_at',
    'title',
    'priority',
    'due_date',
    'issue_number',
)

# Accepted `ordering` values: each field, ascending or (with '-') descending.
ORDERING_CHOICES = [
    value
    for field in ORDERING_FIELDS
    for value in (field, f'-{field}')
]

DEFAULT_ORDERING = ('-created_at', '-id')


def issue_number_from_key(term, project_key):
    """Return the issue number if `term` is a full issue key of this project.

    `issue_key` is a property (`<project key>-<issue number>`), not a column,
    so it cannot be queried directly. Because the search is already scoped to
    one project, a key is matched by checking the prefix and querying the
    number. Matching is case-insensitive and exact: `API-1` does not match
    `API-10`.
    """
    match = _ISSUE_KEY_PATTERN.match(term)

    if match is None:
        return None

    prefix, number = match.groups()

    if prefix.upper() != project_key.upper():
        return None

    number = int(number)

    if not 1 <= number <= MAX_DB_INTEGER:
        return None

    return number


def _parse_iso_date(name, value):
    if not _ISO_DATE_PATTERN.match(value):
        raise QueryParamError(
            f'Invalid {name} filter. Use the format YYYY-MM-DD.'
        )

    try:
        return date.fromisoformat(value)
    except ValueError:
        raise QueryParamError(
            f'Invalid {name} filter. Use the format YYYY-MM-DD.'
        )


def _parse_assignee(value):
    try:
        assignee_id = int(value)
    except (TypeError, ValueError):
        raise QueryParamError('Invalid assignee filter.')

    if not 1 <= assignee_id <= MAX_DB_INTEGER:
        raise QueryParamError('Invalid assignee filter.')

    return assignee_id


def _ordering_expressions(value):
    descending = value.startswith('-')
    field = value[1:] if descending else value

    if field not in ORDERING_FIELDS:
        allowed = ', '.join(ORDERING_CHOICES)
        raise QueryParamError(f'Invalid ordering. Allowed values: {allowed}.')

    if field == 'priority':
        expression = _PRIORITY_RANK
    elif field == 'title':
        expression = Lower('title')
    else:
        expression = F(field)

    if field == 'due_date':
        # Issues without a due date always come last, in either direction.
        primary = (
            expression.desc(nulls_last=True)
            if descending
            else expression.asc(nulls_last=True)
        )
    else:
        primary = expression.desc() if descending else expression.asc()

    # Unique tie-breaker so equal values keep a stable order across pages.
    tie_breaker = F('id').desc() if descending else F('id').asc()

    return (primary, tie_breaker)


def apply_issue_filters(issues, params, project):
    """Return `issues` narrowed and ordered by the query parameters.

    Raises QueryParamError (a 400 for the client) for any invalid value.
    """
    status_value = params.get('status')
    priority_value = params.get('priority')
    issue_type_value = params.get('issue_type')
    assignee_value = params.get('assignee')
    due_before_value = params.get('due_before')
    due_after_value = params.get('due_after')
    ordering_value = params.get('ordering')

    # Validate everything first so a bad request never half-applies.
    if status_value and status_value not in Issue.Status.values:
        raise QueryParamError('Invalid status filter.')

    if priority_value and priority_value not in Issue.Priority.values:
        raise QueryParamError('Invalid priority filter.')

    if issue_type_value and issue_type_value not in Issue.IssueType.values:
        raise QueryParamError('Invalid issue type filter.')

    assignee_id = _parse_assignee(assignee_value) if assignee_value else None

    search = get_search_term(params)

    due_before = (
        _parse_iso_date('due_before', due_before_value)
        if due_before_value
        else None
    )
    due_after = (
        _parse_iso_date('due_after', due_after_value)
        if due_after_value
        else None
    )

    if due_before and due_after and due_after > due_before:
        raise QueryParamError('due_after cannot be later than due_before.')

    ordering = (
        _ordering_expressions(ordering_value)
        if ordering_value
        else None
    )

    if search:
        match = Q(title__icontains=search) | Q(description__icontains=search)
        number = issue_number_from_key(search, project.key)

        if number is not None:
            match |= Q(issue_number=number)

        issues = issues.filter(match)

    if status_value:
        issues = issues.filter(status=status_value)

    if priority_value:
        issues = issues.filter(priority=priority_value)

    if issue_type_value:
        issues = issues.filter(issue_type=issue_type_value)

    if assignee_id is not None:
        issues = issues.filter(assignee_id=assignee_id)

    if due_before:
        issues = issues.filter(due_date__lte=due_before)

    if due_after:
        issues = issues.filter(due_date__gte=due_after)

    if ordering:
        return issues.order_by(*ordering)

    return issues.order_by(*DEFAULT_ORDERING)
