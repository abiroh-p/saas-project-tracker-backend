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