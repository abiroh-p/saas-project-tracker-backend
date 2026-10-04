from django.db import transaction

from ..models import Project


from django.db import transaction

from ..models import Project, ProjectMember


@transaction.atomic
def create_project(*, validated_data, user):
    project = Project.objects.create(
        created_by=user,
        **validated_data,
    )

    ProjectMember.objects.create(
        project=project,
        user=user,
        role=ProjectMember.Role.PROJECT_MANAGER,
    )

    return project


@transaction.atomic
def update_project(*, project, validated_data):
    if (
        'key' in validated_data
        and validated_data['key'] != project.key
    ):
        raise ValueError(
            'Project key cannot be changed.'
        )

    for field, value in validated_data.items():
        setattr(project, field, value)

    project.save()

    return project


@transaction.atomic
def archive_project(*, project):
    project.is_archived = True
    project.save(update_fields=['is_archived', 'updated_at'])

    return project