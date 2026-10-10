from django.db import transaction

from apps.activity.models import Activity
from apps.activity.services.activity import record_activity
from apps.activity.services.changes import build_changes

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

    record_activity(
        project=project,
        user=user,
        action=Activity.Action.PROJECT_CREATED,
        entity_type=Activity.EntityType.PROJECT,
        entity_id=project.id,
        description=f'{user.username} created project {project.key}',
        metadata={
            'key': project.key,
            'name': project.name,
        },
    )

    return project


@transaction.atomic
def update_project(*, project, validated_data, actor):
    if (
        'key' in validated_data
        and validated_data['key'] != project.key
    ):
        raise ValueError(
            'Project key cannot be changed.'
        )

    # Compare against the persisted values before applying anything.
    changes = build_changes(
        project,
        validated_data,
        redact={'description'},
    )

    for field, value in validated_data.items():
        setattr(project, field, value)

    project.save()

    if changes:
        record_activity(
            project=project,
            user=actor,
            action=Activity.Action.PROJECT_UPDATED,
            entity_type=Activity.EntityType.PROJECT,
            entity_id=project.id,
            description=(
                f'{actor.username} updated project {project.key} '
                f'({", ".join(changes)})'
            ),
            metadata={'changes': changes},
        )

    return project


@transaction.atomic
def archive_project(*, project, actor):
    project.is_archived = True
    project.save(update_fields=['is_archived', 'updated_at'])

    record_activity(
        project=project,
        user=actor,
        action=Activity.Action.PROJECT_ARCHIVED,
        entity_type=Activity.EntityType.PROJECT,
        entity_id=project.id,
        description=f'{actor.username} archived project {project.key}',
        metadata={'key': project.key},
    )

    return project
