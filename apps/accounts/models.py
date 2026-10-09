from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class User(AbstractUser):

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        PROJECT_MANAGER = "PROJECT_MANAGER", "Project Manager"
        TEAM_MEMBER = "TEAM_MEMBER", "Team Member"

    full_name = models.CharField(
        max_length=150,
        blank=True,
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.TEAM_MEMBER,
    )

    class Meta(AbstractUser.Meta):
        constraints = [
            # Email is a login identifier, so it must be unique regardless of
            # case. Accounts without an email (e.g. created by createsuperuser)
            # are exempt.
            models.UniqueConstraint(
                Lower("email"),
                name="unique_user_email_ci",
                condition=~models.Q(email=""),
            ),
        ]

    def __str__(self):
        return self.username
