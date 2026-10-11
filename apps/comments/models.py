from django.conf import settings
from django.db import models

MAX_COMMENT_LENGTH = 5000


class Comment(models.Model):
    issue = models.ForeignKey(
        'issues.Issue',
        on_delete=models.CASCADE,
        related_name='comments',
    )

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='issue_comments',
    )

    # Empty only for deleted comments, whose text is erased.
    body = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    # Changes on any save, including deletion.
    updated_at = models.DateTimeField(
        auto_now=True,
    )

    # Set only when the author edits the text; drives the "edited" label.
    edited_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # Soft delete: the row stays so the discussion keeps its shape, but the
    # text is erased. `deleted_by` records who removed it (the author, or a
    # project manager moderating).
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='deleted_issue_comments',
    )

    # Project members mentioned in the text. Filled by the server from the
    # body (never from client input), so it only ever holds eligible users.
    mentions = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='mentioned_in_comments',
    )

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(
                fields=['issue', 'created_at'],
                name='comment_issue_created_idx',
            ),
        ]

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def __str__(self):
        return f'Comment #{self.pk} on issue {self.issue_id}'
