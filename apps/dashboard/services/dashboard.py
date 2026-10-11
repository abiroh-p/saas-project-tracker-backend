"""Read-only aggregation behind ``GET /api/v1/dashboard/``.

Nothing is stored here: every figure is computed from Projects and Issues on
each request, so it can never drift from the source of truth.

Visibility follows the rules the rest of the API already uses: a user can see
a project only while they are a member of it and it is not archived, and the
issues of an inaccessible project are inaccessible too. Those rules are applied
to the queryset first, and every metric below is derived from it.
"""
from django.db.models import Count, Exists, OuterRef
from django.utils import timezone

from apps.issues.models import Issue
from apps.projects.models import Project, ProjectMember

RECENT_ISSUES_LIMIT = 5


def get_projects_count(user):
    """Non-archived projects the user is currently a member of.

    ``(project, user)`` is unique on ``ProjectMember``, so filtering on one
    user yields at most one row per project and the count cannot be inflated
    by other members of the same project.
    """
    return Project.objects.filter(
        members__user=user,
        is_archived=False,
    ).count()


def get_assigned_issues(user):
    """Issues assigned to ``user`` that they may still see.

    The membership check is an ``EXISTS`` subquery rather than a join, so a
    project with many members can never multiply the rows of this queryset.
    """
    is_member = ProjectMember.objects.filter(
        project=OuterRef('project'),
        user=user,
    )

    return (
        Issue.objects
        .filter(
            assignee=user,
            is_archived=False,
            project__is_archived=False,
        )
        .filter(Exists(is_member))
    )


def count_by_status(issues):
    """Raw ``{status: count}`` for every status present in ``issues``.

    One grouped query. Statuses with no issues are absent, and a value outside
    the declared choices (for example a legacy row) is kept as it is.
    """
    rows = (
        issues
        .order_by()
        .values('status')
        .annotate(total=Count('id'))
    )

    return {row['status']: row['total'] for row in rows}


def fill_status_counts(raw_counts):
    """Every declared status, zero filled, in the order of the choices.

    A value outside the declared choices is left out, so it can never change
    the shape of the response.
    """
    return {value: raw_counts.get(value, 0) for value in Issue.Status.values}


def get_issues_by_status(issues):
    """Count per declared status, with every status present."""
    return fill_status_counts(count_by_status(issues))


def get_overdue_count(issues, today):
    """Incomplete issues whose due date is strictly before ``today``.

    ``due_date`` is a ``DateField``, so the comparison is by calendar day: an
    issue due today is not overdue until tomorrow. Issues without a due date
    and completed issues never count.
    """
    return (
        issues
        .filter(due_date__lt=today)
        .exclude(status=Issue.Status.DONE)
        .count()
    )


def get_recent_issues(issues, limit=RECENT_ISSUES_LIMIT):
    """Most recently updated issues, newest first, with ``id`` as tie-breaker.

    Only the columns the dashboard serializes are loaded; ``project`` is
    joined because ``issue_key`` is built from the project key.
    """
    return list(
        issues
        .select_related('project')
        .only(
            'id',
            'issue_number',
            'title',
            'status',
            'priority',
            'due_date',
            'updated_at',
            'project_id',
            'project__key',
        )
        .order_by('-updated_at', '-id')[:limit]
    )


def get_dashboard_summary(user, *, today=None):
    """Everything the dashboard shows for ``user``.

    ``today`` can be passed in for deterministic tests; by default it is the
    current date in the project's configured timezone.
    """
    if today is None:
        today = timezone.localdate()

    issues = get_assigned_issues(user)
    raw_counts = count_by_status(issues)
    issues_by_status = fill_status_counts(raw_counts)

    return {
        'summary': {
            'projects_count': get_projects_count(user),
            # Every issue in the authorized queryset, taken from the same
            # grouped query as the breakdown (no extra query). It equals the
            # sum of issues_by_status unless a record carries a status
            # outside the declared choices.
            'assigned_issues_count': sum(raw_counts.values()),
            'in_progress_count': issues_by_status[Issue.Status.IN_PROGRESS],
            'completed_count': issues_by_status[Issue.Status.DONE],
            'overdue_count': get_overdue_count(issues, today),
        },
        'issues_by_status': issues_by_status,
        'recent_issues': get_recent_issues(issues),
    }
