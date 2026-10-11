"""Read-only aggregation behind the project report endpoints.

Nothing is stored: every figure is computed from Issues on each request, in the
database, so it can never drift from the source of truth.

Every report starts from ``get_report_issues``, so all of them share one
population: the non-archived issues of the requested project. Access to the
project itself is decided before any function here is called (see
``services.access``).
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Q
from django.utils import timezone

from apps.issues.models import Issue

Status = Issue.Status

# How declared statuses roll up into the three progress categories the reports
# expose. This is the single place that decides it. A new status must be added
# here (a test fails until it is), so a report can never silently drop it.
OPEN_STATUSES = frozenset({Status.TODO})
IN_PROGRESS_STATUSES = frozenset({Status.IN_PROGRESS, Status.IN_REVIEW})
COMPLETED_STATUSES = frozenset({Status.DONE})


def get_report_issues(project):
    """The issues every report counts: not archived, in ``project``.

    ``order_by()`` clears the model's default ordering, which would otherwise
    leak into the ``GROUP BY`` of the grouped queries below.
    """
    return Issue.objects.filter(project=project, is_archived=False).order_by()


def completion_rate(completed, total):
    """``completed / total`` as a percentage with one decimal place.

    Rounded half-up on exact decimals (12.25 -> 12.3), not with float
    ``round``, and ``0.0`` for an empty population.
    """
    if not total:
        return 0.0

    rate = Decimal(completed) * 100 / Decimal(total)

    return float(rate.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def _category_counts(today):
    """Conditional counts shared by the overview and assignee workload.

    ``overdue`` mirrors the dashboard: not completed and due strictly before
    ``today``. ``due_date`` is a ``DateField``, so an issue due today is not
    overdue, and an issue without a due date never is.
    """
    return {
        'open_issues': Count('id', filter=Q(status__in=OPEN_STATUSES)),
        'in_progress_issues': Count(
            'id', filter=Q(status__in=IN_PROGRESS_STATUSES),
        ),
        'completed_issues': Count(
            'id', filter=Q(status__in=COMPLETED_STATUSES),
        ),
        'overdue_issues': Count(
            'id',
            filter=Q(due_date__lt=today) & ~Q(status__in=COMPLETED_STATUSES),
        ),
    }


def get_project_overview(project, *, today=None):
    """High-level progress metrics for ``project`` in a single query.

    ``today`` can be passed in for deterministic tests; by default it is the
    current date in the configured timezone.

    ``open + in_progress + completed`` equals ``total_issues`` unless a record
    carries a status outside the declared choices (a legacy row), which is
    counted in the total only.
    """
    if today is None:
        today = timezone.localdate()

    counts = get_report_issues(project).aggregate(
        total_issues=Count('id'),
        unassigned_issues=Count('id', filter=Q(assignee__isnull=True)),
        **_category_counts(today),
    )

    return {
        'project_id': project.pk,
        'project_key': project.key,
        'total_issues': counts['total_issues'],
        'open_issues': counts['open_issues'],
        'in_progress_issues': counts['in_progress_issues'],
        'completed_issues': counts['completed_issues'],
        'overdue_issues': counts['overdue_issues'],
        'unassigned_issues': counts['unassigned_issues'],
        'completion_rate': completion_rate(
            counts['completed_issues'], counts['total_issues'],
        ),
    }


def _get_distribution(project, field, choices):
    """Issue counts per declared choice of ``field``, in the choices' order.

    One grouped query. Every declared value is present (zero filled) so the
    response has a stable shape. A value outside the declared choices is never
    exposed as a normal entry; it is reported in ``other_count`` instead, so
    ``total_issues`` always equals the sum of ``results`` plus ``other_count``.
    """
    rows = (
        get_report_issues(project)
        .values(field)
        .annotate(count=Count('id'))
    )
    raw = {row[field]: row['count'] for row in rows}
    declared = {value for value, _ in choices}

    return {
        'project_id': project.pk,
        'results': [
            {field: value, 'label': str(label), 'count': raw.get(value, 0)}
            for value, label in choices
        ],
        'other_count': sum(
            count for value, count in raw.items() if value not in declared
        ),
        'total_issues': sum(raw.values()),
    }


def get_status_distribution(project):
    return _get_distribution(project, 'status', Issue.Status.choices)


def get_priority_distribution(project):
    return _get_distribution(project, 'priority', Issue.Priority.choices)


def get_assignee_workload(project, *, today=None):
    """Issue counts per assignee, plus an explicit unassigned group.

    One grouped query that joins the assignee's ``username`` and
    ``full_name`` only, so there is no N+1 and no other user field (email
    included) is ever read. The number of groups is bounded by the project's
    members, so the result is not paginated.

    Busiest assignee first; ties by username, then id. The unassigned group
    (``assignee_id`` ``None``) is present only when such issues exist, and is
    always last.
    """
    if today is None:
        today = timezone.localdate()

    rows = (
        get_report_issues(project)
        .values('assignee_id', 'assignee__username', 'assignee__full_name')
        .annotate(assigned_issues=Count('id'), **_category_counts(today))
    )

    results = [
        {
            'assignee_id': row['assignee_id'],
            'username': row['assignee__username'],
            'full_name': row['assignee__full_name'],
            'assigned_issues': row['assigned_issues'],
            'open_issues': row['open_issues'],
            'in_progress_issues': row['in_progress_issues'],
            'completed_issues': row['completed_issues'],
            'overdue_issues': row['overdue_issues'],
        }
        for row in rows
    ]
    results.sort(
        key=lambda item: (
            item['assignee_id'] is None,
            -item['assigned_issues'],
            (item['username'] or '').lower(),
            item['assignee_id'] or 0,
        )
    )

    return {
        'project_id': project.pk,
        'results': results,
        'total_issues': sum(item['assigned_issues'] for item in results),
    }
