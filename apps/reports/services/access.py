"""Who may run reports for a project.

Reports follow the rule the rest of the project API uses: a user can see a
project only while they are a member of it and it is not archived. Any role
(including viewer) may read; reports never change data.
"""
from django.db.models import Exists, OuterRef

from apps.projects.models import Project, ProjectMember


def get_reportable_project(project_id, user):
    """Return the project, or ``None`` when ``user`` may not report on it.

    A missing project, an archived project and a project the user is not a
    member of are deliberately indistinguishable, so a report endpoint can
    never be used to discover which project ids exist.

    Membership is an ``EXISTS`` subquery rather than a join, so a project with
    many members cannot multiply rows or need ``distinct()``.
    """
    is_member = ProjectMember.objects.filter(
        project=OuterRef('pk'),
        user=user,
    )

    return (
        Project.objects
        .filter(id=project_id, is_archived=False)
        .filter(Exists(is_member))
        .only('id', 'key')
        .first()
    )
