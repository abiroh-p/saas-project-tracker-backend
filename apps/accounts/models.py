from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        PROJECT_MANAGER = "PROJECT_MANAGER", "Project Manager"
        TEAM_MEMBER = "TEAM_MEMBER", "Team Member"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.TEAM_MEMBER,
    )

    def __str__(self):
        return self.username