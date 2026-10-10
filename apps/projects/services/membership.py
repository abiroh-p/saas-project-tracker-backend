from django.db import transaction

from apps.activity.models import Activity
from apps.activity.services.activity import record_activity, user_ref

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
def add_project_member(*, project, user_id, role, actor):
    if ProjectMember.objects.filter(
        project=project,
        user_id=user_id,
    ).exists():
        raise ValueError('User is already a member of this project.')

    membership = ProjectMember.objects.create(
        project=project,
        user_id=user_id,
        role=role,
    )

    record_activity(
        project=project,
        user=actor,
        action=Activity.Action.MEMBER_ADDED,
        entity_type=Activity.EntityType.MEMBERSHIP,
        entity_id=membership.id,
        description=(
            f'{actor.username} added {membership.user.username} '
            f'to project {project.key} as {membership.get_role_display()}'
        ),
        metadata={
            'member': user_ref(membership.user),
            'role': membership.role,
        },
    )

    return membership


@transaction.atomic
def change_member_role(*, membership, role, actor):
    if membership.role == role:
        return membership

    if role == ProjectMember.Role.VIEWER:
        from apps.issues.models import Issue

        # A viewer cannot work on issues, so don't leave open ones assigned
        # to them. Archived issues are read-only history and can stay.
        has_open_issues = Issue.objects.filter(
            project=membership.project,
            assignee=membership.user,
            is_archived=False,
        ).exists()

        if has_open_issues:
            raise ValueError(
                'This member has issues assigned to them. Reassign or '
                'unassign those issues before making them a viewer.'
            )

    if role != ProjectMember.Role.PROJECT_MANAGER:
        ensure_not_last_project_manager(membership=membership)

    old_role = membership.role

    membership.role = role
    membership.save(update_fields=['role'])

    record_activity(
        project=membership.project,
        user=actor,
        action=Activity.Action.ROLE_CHANGED,
        entity_type=Activity.EntityType.MEMBERSHIP,
        entity_id=membership.id,
        description=(
            f"{actor.username} changed {membership.user.username}'s role "
            f'in project {membership.project.key} from '
            f'{ProjectMember.Role(old_role).label} to '
            f'{membership.get_role_display()}'
        ),
        metadata={
            'member': user_ref(membership.user),
            'from': old_role,
            'to': membership.role,
        },
    )

    return membership


@transaction.atomic
def remove_project_member(*, membership, actor):
    from apps.issues.models import Issue

    ensure_not_last_project_manager(membership=membership)

    project = membership.project
    member = membership.user

    # Snapshot everything before the row is deleted.
    membership_id = membership.id
    member_ref = user_ref(member)
    role = membership.role
    self_removed = actor.pk == member.pk

    # Removing a member silently unassigns their issues. Record each one so
    # the trail explains why an issue lost its assignee.
    unassigned = list(
        Issue.objects.filter(
            project=project,
            assignee=member,
        ).select_related('project')
    )

    Issue.objects.filter(
        pk__in=[issue.pk for issue in unassigned],
    ).update(assignee=None)

    for issue in unassigned:
        record_activity(
            project=project,
            user=actor,
            action=Activity.Action.ISSUE_UNASSIGNED,
            entity_type=Activity.EntityType.ISSUE,
            entity_id=issue.id,
            description=(
                f'{actor.username} unassigned {issue.issue_key} '
                f'(removed {member.username} from the project)'
            ),
            metadata={
                'from': member_ref,
                'to': None,
                'reason': 'member_removed',
            },
        )

    membership.delete()

    record_activity(
        project=project,
        user=actor,
        action=Activity.Action.MEMBER_REMOVED,
        entity_type=Activity.EntityType.MEMBERSHIP,
        entity_id=membership_id,
        description=(
            f'{actor.username} left project {project.key}'
            if self_removed
            else (
                f'{actor.username} removed {member.username} '
                f'from project {project.key}'
            )
        ),
        metadata={
            'member': member_ref,
            'role': role,
            'self_removed': self_removed,
        },
    )
