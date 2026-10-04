from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Project(models.Model):
    key = models.CharField(
        max_length=20,
        unique=True,
    )

    issue_counter = models.PositiveIntegerField(
        default=0,
    )

    name = models.CharField(
        max_length=255,
    )

    description = models.TextField(
        blank=True,
    )

    start_date = models.DateField(
        null=True,
        blank=True,
    )

    end_date = models.DateField(
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_projects',
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

    def save(self, *args, **kwargs):
        if self.pk:
            old_key = type(self).objects.only('key').get(
                pk=self.pk
            ).key

            if old_key != self.key:
                raise ValidationError(
                    {
                        'key': 'Project key cannot be changed.'
                    }
                )

        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.key} - {self.name}'


class ProjectMember(models.Model):

    class Role(models.TextChoices):
        PROJECT_MANAGER = (
            'PROJECT_MANAGER',
            'Project Manager',
        )
        TEAM_MEMBER = (
            'TEAM_MEMBER',
            'Team Member',
        )
        VIEWER = (
            'VIEWER',
            'Viewer',
        )

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name='members',
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='project_memberships',
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'user'],
                name='unique_project_member',
            ),
        ]

    def __str__(self):
        return (
            f'{self.project.key} - '
            f'{self.user.username} - '
            f'{self.role}'
        )