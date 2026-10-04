from django.conf import settings
from django.db import models


class Issue(models.Model):

    class IssueType(models.TextChoices):
        TASK = 'TASK', 'Task'
        BUG = 'BUG', 'Bug'
        STORY = 'STORY', 'Story'
        EPIC = 'EPIC', 'Epic'

    class Priority(models.TextChoices):
        LOW = 'LOW', 'Low'
        MEDIUM = 'MEDIUM', 'Medium'
        HIGH = 'HIGH', 'High'
        URGENT = 'URGENT', 'Urgent'

    class Status(models.TextChoices):
        TODO = 'TODO', 'To Do'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        IN_REVIEW = 'IN_REVIEW', 'In Review'
        DONE = 'DONE', 'Done'

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.PROTECT,
        related_name='issues',
    )

    issue_number = models.PositiveIntegerField()

    title = models.CharField(
        max_length=255,
    )

    description = models.TextField(
        blank=True,
    )

    issue_type = models.CharField(
        max_length=10,
        choices=IssueType.choices,
        default=IssueType.TASK,
    )

    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.TODO,
    )

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reported_issues',
    )

    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='assigned_issues',
        null=True,
        blank=True,
    )

    due_date = models.DateField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    is_archived = models.BooleanField(
        default=False,
    )

    class Meta:
        ordering = ['-created_at' , '-id']

        constraints = [
            models.UniqueConstraint(
                fields=['project', 'issue_number'],
                name='unique_issue_number_per_project',
            ),
        ]

        indexes = [
            models.Index(
                fields=['project', 'status'],
                name='issue_project_status_idx',
    ),
]

    @property
    def issue_key(self):
        return f'{self.project.key}-{self.issue_number}'

    def __str__(self):
        return f'{self.issue_key} - {self.title}'