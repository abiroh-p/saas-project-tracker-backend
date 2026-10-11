from django.db import transaction

from apps.projects.models import ProjectMember
from apps.projects.services.membership import get_project_membership

from ..models import Comment


def _require_participant(*, issue, user, action):
    """Return the user's membership, or raise if they may not write."""
    membership = get_project_membership(
        project=issue.project,
        user=user,
    )

    if membership is None:
        raise PermissionError(
            'You are not a member of this project.'
        )

    if membership.role == ProjectMember.Role.VIEWER:
        raise PermissionError(
            f'Viewers cannot {action}.'
        )

    return membership


@transaction.atomic
def create_comment(*, issue, user, body):
    _require_participant(
        issue=issue,
        user=user,
        action='comment on issues',
    )

    if issue.is_archived:
        raise ValueError(
            'Comments on archived issues are read-only.'
        )

    return Comment.objects.create(
        issue=issue,
        author=user,
        body=body,
    )
