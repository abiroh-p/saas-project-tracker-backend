from django.db import transaction

from ..models import Project


@transaction.atomic
def create_project(*, validated_data, user):
    return Project.objects.create(
        created_by=user,
        **validated_data,
    )


@transaction.atomic
def update_project(*, project, validated_data):
    for field, value in validated_data.items():
        setattr(project, field, value)

    project.save()

    return project


@transaction.atomic
def archive_project(*, project):
    project.is_archived = True
    project.save(update_fields=['is_archived', 'updated_at'])

    return project