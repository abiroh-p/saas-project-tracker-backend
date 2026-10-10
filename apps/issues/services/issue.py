from django.db import transaction

from apps.activity.models import Activity
from apps.activity.services.activity import record_activity, user_ref
from apps.activity.services.changes import build_changes
from apps.projects.models import Project, ProjectMember

from ..models import Issue


def _record_issue_event(*, issue, user, action, description, metadata):
    record_activity(
        project=issue.project,
        user=user,
        action=action,
        entity_type=Activity.EntityType.ISSUE,
        entity_id=issue.id,
        description=description,
        metadata=metadata,
    )


@transaction.atomic
def create_issue(*, project, validated_data, user):
    project = Project.objects.select_for_update().get(
        pk=project.pk
    )

    assignee = validated_data.get('assignee')

    if assignee is not None:
        is_member = ProjectMember.objects.filter(
            project=project,
            user=assignee,
        ).exists()

        if not is_member:
            raise ValueError(
                'Assignee must be a member of the project.'
            )

    project.issue_counter += 1
    issue_number = project.issue_counter

    project.save(
        update_fields=[
            'issue_counter',
            'updated_at',
        ]
    )

    issue = Issue.objects.create(
        project=project,
        issue_number=issue_number,
        reporter=user,
        **validated_data,
    )

    # One event, even when the issue is created with an assignee: the assignee
    # is part of the creation snapshot.
    _record_issue_event(
        issue=issue,
        user=user,
        action=Activity.Action.ISSUE_CREATED,
        description=f'{user.username} created {issue.issue_key}: {issue.title}',
        metadata={
            'issue_key': issue.issue_key,
            'title': issue.title,
            'issue_type': issue.issue_type,
            'priority': issue.priority,
            'assignee': user_ref(issue.assignee),
        },
    )

    return issue

@transaction.atomic
def update_issue(*, issue, validated_data, user):
    if issue.is_archived:
        raise ValueError(
            'Archived issues cannot be edited.'
        )

    membership = ProjectMember.objects.filter(
        project=issue.project,
        user=user,
    ).first()

    if membership is None:
        raise PermissionError(
            'You are not a member of this project.'
        )

    is_manager = (
        membership.role
        == ProjectMember.Role.PROJECT_MANAGER
    )

    if 'assignee' in validated_data and not is_manager:
        raise PermissionError(
            'Only project managers can change the assignee.'
        )

    if not is_manager:
        is_reporter = issue.reporter_id == user.id
        is_assignee = issue.assignee_id == user.id

        if not (is_reporter or is_assignee):
            raise PermissionError(
                'Only the reporter or assignee can edit this issue.'
            )

    assignee = validated_data.get(
        'assignee',
        issue.assignee,
    )

    if assignee is not None:
        is_member = ProjectMember.objects.filter(
            project=issue.project,
            user=assignee,
        ).exists()

        if not is_member:
            raise ValueError(
                'Assignee must be a member of the project.'
            )

    # Compare against the persisted values before applying anything.
    # Assignment is recorded as its own event, so it is kept out of `changes`.
    old_assignee = issue.assignee
    assignee_changed = (
        'assignee' in validated_data
        and validated_data['assignee'] != old_assignee
    )

    changes = build_changes(
        issue,
        {
            field: value
            for field, value in validated_data.items()
            if field != 'assignee'
        },
        redact={'description'},
    )

    for field, value in validated_data.items():
        setattr(issue, field, value)

    issue.save()

    if changes:
        _record_issue_event(
            issue=issue,
            user=user,
            action=Activity.Action.ISSUE_UPDATED,
            description=(
                f'{user.username} updated {issue.issue_key} '
                f'({", ".join(changes)})'
            ),
            metadata={'changes': changes},
        )

    if assignee_changed:
        new_assignee = issue.assignee

        if new_assignee is None:
            _record_issue_event(
                issue=issue,
                user=user,
                action=Activity.Action.ISSUE_UNASSIGNED,
                description=(
                    f'{user.username} unassigned {issue.issue_key} '
                    f'(was {old_assignee.username})'
                ),
                metadata={
                    'from': user_ref(old_assignee),
                    'to': None,
                },
            )
        else:
            _record_issue_event(
                issue=issue,
                user=user,
                action=Activity.Action.ISSUE_ASSIGNED,
                description=(
                    f'{user.username} assigned {issue.issue_key} '
                    f'to {new_assignee.username}'
                    if old_assignee is None
                    else (
                        f'{user.username} reassigned {issue.issue_key} '
                        f'from {old_assignee.username} '
                        f'to {new_assignee.username}'
                    )
                ),
                metadata={
                    'from': user_ref(old_assignee),
                    'to': user_ref(new_assignee),
                },
            )

    return issue


@transaction.atomic
def archive_issue(*, issue, user):
    membership = ProjectMember.objects.filter(
        project=issue.project,
        user=user,
    ).first()

    if membership is None:
        raise PermissionError(
            'You are not a member of this project.'
        )

    if membership.role != ProjectMember.Role.PROJECT_MANAGER:
        raise PermissionError(
            'Only project managers can archive issues.'
        )

    if issue.is_archived:
        raise ValueError('Issue is already archived.')

    issue.is_archived = True
    issue.save(update_fields=['is_archived', 'updated_at'])

    _record_issue_event(
        issue=issue,
        user=user,
        action=Activity.Action.ISSUE_ARCHIVED,
        description=f'{user.username} archived {issue.issue_key}',
        metadata={'issue_key': issue.issue_key},
    )

    return issue


@transaction.atomic
def transition_issue(*, issue, user, new_status):
    membership = ProjectMember.objects.filter(
        project=issue.project,
        user=user,
    ).first()

    if membership is None:
        raise PermissionError(
            'You are not a member of this project.'
        )

    if membership.role == ProjectMember.Role.VIEWER:
        raise PermissionError(
            'Viewers cannot transition issues.'
        )

    is_manager = (
        membership.role
        == ProjectMember.Role.PROJECT_MANAGER
    )

    is_assignee = issue.assignee_id == user.id

    if not is_manager and not is_assignee:
        raise PermissionError(
            'Only the project manager or assigned member '
            'can transition this issue.'
        )

    if issue.is_archived:
        raise ValueError(
            'Archived issues cannot be transitioned.'
        )

    valid_statuses = {
        choice[0]
        for choice in Issue.Status.choices
    }

    if new_status not in valid_statuses:
        raise ValueError('Invalid issue status.')

    if issue.status == new_status:
        raise ValueError('Issue is already in this status.')

    allowed_transitions = {
        Issue.Status.TODO: {
            Issue.Status.IN_PROGRESS,
        },
        Issue.Status.IN_PROGRESS: {
            Issue.Status.IN_REVIEW,
        },
        Issue.Status.IN_REVIEW: {
            Issue.Status.DONE,
        },
        Issue.Status.DONE: set(),
    }

    if new_status not in allowed_transitions[issue.status]:
        raise ValueError(
            f'Cannot transition issue from '
            f'{issue.status} to {new_status}.'
        )

    old_status = issue.status

    issue.status = new_status
    issue.save(
        update_fields=[
            'status',
            'updated_at',
        ]
    )

    _record_issue_event(
        issue=issue,
        user=user,
        action=Activity.Action.ISSUE_STATUS_CHANGED,
        description=(
            f'{user.username} moved {issue.issue_key} from '
            f'{Issue.Status(old_status).label} to '
            f'{issue.get_status_display()}'
        ),
        metadata={
            'from': old_status,
            'to': issue.status,
        },
    )

    return issue
