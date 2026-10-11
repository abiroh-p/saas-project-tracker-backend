from django.db import transaction
from django.utils import timezone

from apps.projects.models import ProjectMember
from apps.projects.services.membership import get_project_membership

from ..models import Comment
from .mentions import resolve_mentioned_users


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

    comment = Comment.objects.create(
        issue=issue,
        author=user,
        body=body,
    )

    comment.mentions.set(
        resolve_mentioned_users(project=issue.project, body=body)
    )

    return comment


def _lock(comment):
    """Re-read the comment under a row lock, so two concurrent edits or
    deletes cannot both act on a stale copy."""
    return (
        Comment.objects
        .select_for_update()
        .select_related('issue__project', 'author')
        .get(pk=comment.pk)
    )


def _ensure_writable(comment):
    if comment.is_deleted:
        raise ValueError(
            'Deleted comments cannot be changed.'
        )

    if comment.issue.is_archived:
        raise ValueError(
            'Comments on archived issues are read-only.'
        )


@transaction.atomic
def update_comment(*, comment, user, body):
    comment = _lock(comment)

    _require_participant(
        issue=comment.issue,
        user=user,
        action='edit comments',
    )

    # Nobody edits someone else's words, whatever their role.
    if comment.author_id != user.pk:
        raise PermissionError(
            'You can only edit your own comments.'
        )

    _ensure_writable(comment)

    if body == comment.body:
        return comment

    comment.body = body
    comment.edited_at = timezone.now()
    comment.save(update_fields=['body', 'edited_at', 'updated_at'])

    comment.mentions.set(
        resolve_mentioned_users(project=comment.issue.project, body=body)
    )

    return comment


@transaction.atomic
def delete_comment(*, comment, user):
    """Soft delete: the comment keeps its place in the discussion but its
    text is erased. Authors may delete their own comments, and project
    managers may delete any (moderation); `deleted_by` records who did."""
    comment = _lock(comment)

    membership = _require_participant(
        issue=comment.issue,
        user=user,
        action='delete comments',
    )

    is_author = comment.author_id == user.pk
    is_manager = membership.role == ProjectMember.Role.PROJECT_MANAGER

    if not (is_author or is_manager):
        raise PermissionError(
            'You can only delete your own comments.'
        )

    if comment.is_deleted:
        raise ValueError(
            'Comment is already deleted.'
        )

    _ensure_writable(comment)

    comment.body = ''
    comment.deleted_at = timezone.now()
    comment.deleted_by = user
    comment.save(
        update_fields=['body', 'deleted_at', 'deleted_by', 'updated_at'],
    )

    comment.mentions.clear()

    return comment
