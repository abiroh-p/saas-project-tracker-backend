from django.db import transaction

from ..models import ProjectMember


def get_project_membership(*, project, user):
    return ProjectMember.objects.filter(
        project=project,
        user=user,
    ).first()


def is_project_manager(*, project, user):
    membership = get_project_membership(
        project=project,
        user=user,
    )

    return (
        membership is not None
        and membership.role == ProjectMember.Role.PROJECT_MANAGER
    )


def ensure_not_last_project_manager(*, membership):
    if membership.role != ProjectMember.Role.PROJECT_MANAGER:
        return

    manager_count = ProjectMember.objects.filter(
        project=membership.project,
        role=ProjectMember.Role.PROJECT_MANAGER,
    ).count()

    if manager_count <= 1:
        raise ValueError(
            'A project must have at least one project manager.'
        )


@transaction.atomic
def add_project_member(*, project, user_id, role):
    if ProjectMember.objects.filter(
        project=project,
        user_id=user_id,
    ).exists():
        raise ValueError('User is already a member of this project.')

    return ProjectMember.objects.create(
        project=project,
        user_id=user_id,
        role=role,
    )


@transaction.atomic
def change_member_role(*, membership, role):
    if membership.role == role:
        return membership

    if role != ProjectMember.Role.PROJECT_MANAGER:
        ensure_not_last_project_manager(membership=membership)

    membership.role = role
    membership.save(update_fields=['role'])

    return membership


@transaction.atomic
def remove_project_member(*, membership):
    from apps.issues.models import Issue

    ensure_not_last_project_manager(membership=membership)

    Issue.objects.filter(
        project=membership.project,
        assignee=membership.user,
    ).update(assignee=None)

    membership.delete()
