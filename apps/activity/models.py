from django.conf import settings
from django.db import models

from .exceptions import ImmutableActivityError


class ActivityQuerySet(models.QuerySet):
    """Blocks bulk changes so recorded activity stays append-only.

    This covers ``update()``, ``delete()`` and ``bulk_update()``. It is an
    application-level guard, not a database guarantee: raw SQL still bypasses
    it.
    """

    def update(self, **kwargs):
        raise ImmutableActivityError('Activity records cannot be updated.')

    def delete(self):
        raise ImmutableActivityError('Activity records cannot be deleted.')


class Activity(models.Model):

    class Action(models.TextChoices):
        PROJECT_CREATED = 'PROJECT_CREATED', 'Project created'
        PROJECT_UPDATED = 'PROJECT_UPDATED', 'Project updated'
        PROJECT_ARCHIVED = 'PROJECT_ARCHIVED', 'Project archived'
        MEMBER_ADDED = 'MEMBER_ADDED', 'Member added'
        MEMBER_REMOVED = 'MEMBER_REMOVED', 'Member removed'
        ROLE_CHANGED = 'ROLE_CHANGED', 'Role changed'
        ISSUE_CREATED = 'ISSUE_CREATED', 'Issue created'
        ISSUE_UPDATED = 'ISSUE_UPDATED', 'Issue updated'
        ISSUE_ASSIGNED = 'ISSUE_ASSIGNED', 'Issue assigned'
        ISSUE_UNASSIGNED = 'ISSUE_UNASSIGNED', 'Issue unassigned'
        ISSUE_STATUS_CHANGED = (
            'ISSUE_STATUS_CHANGED',
            'Issue status changed',
        )
        ISSUE_ARCHIVED = 'ISSUE_ARCHIVED', 'Issue archived'

    class EntityType(models.TextChoices):
        PROJECT = 'PROJECT', 'Project'
        MEMBERSHIP = 'MEMBERSHIP', 'Membership'
        ISSUE = 'ISSUE', 'Issue'

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.PROTECT,
        related_name='activities',
    )

    # The actor, always taken from the authenticated request user.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='activities',
    )

    action = models.CharField(
        max_length=30,
        choices=Action.choices,
    )

    entity_type = models.CharField(
        max_length=20,
        choices=EntityType.choices,
    )

    # Not a foreign key: the affected row may be gone (a removed membership).
    entity_id = models.PositiveBigIntegerField()

    # Human-readable snapshot. `metadata` is the structured source of truth.
    description = models.TextField()

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    objects = ActivityQuerySet.as_manager()

    class Meta:
        verbose_name_plural = 'activities'
        ordering = ['-created_at', '-id']
        indexes = [
            # Project feed.
            models.Index(
                fields=['project', '-created_at'],
                name='activity_project_created_idx',
            ),
            # Issue feed: filtered by entity, newest first.
            models.Index(
                fields=['entity_type', 'entity_id', '-created_at'],
                name='activity_entity_created_idx',
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableActivityError(
                'Activity records cannot be modified.'
            )

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableActivityError(
            'Activity records cannot be deleted.'
        )

    def __str__(self):
        return f'{self.action} #{self.entity_id} by {self.user_id}'
