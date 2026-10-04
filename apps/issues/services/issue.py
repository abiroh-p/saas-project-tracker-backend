from django.db import transaction

from apps.projects.models import Project, ProjectMember

from ..models import Issue


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

    return Issue.objects.create(
        project=project,
        issue_number=issue_number,
        reporter=user,
        **validated_data,
    )

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

    for field, value in validated_data.items():
        setattr(issue, field, value)

    issue.save()

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

    issue.status = new_status
    issue.save(
        update_fields=[
            'status',
            'updated_at',
        ]
    )

    return issue