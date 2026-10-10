from django.db import connection

from ..exceptions import ActivityError
from ..models import Activity

# Metadata must never carry credentials or unnecessary personal data.
FORBIDDEN_METADATA_KEYS = frozenset({
    'password',
    'passwd',
    'token',
    'access',
    'refresh',
    'access_token',
    'refresh_token',
    'secret',
    'authorization',
    'email',
})


def user_ref(user):
    """The minimal user snapshot used in metadata: id and username only."""
    if user is None:
        return None

    return {
        'id': user.pk,
        'username': user.username,
    }


def _check_metadata(value, path='metadata'):
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_METADATA_KEYS:
                raise ActivityError(
                    f'{path}.{key} must not be stored in activity metadata.'
                )

            _check_metadata(nested, f'{path}.{key}')
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _check_metadata(nested, f'{path}[{index}]')


def record_activity(
    *,
    project,
    user,
    action,
    entity_type,
    entity_id,
    description,
    metadata=None,
):
    """Write one activity event. The single entry point for all workflows.

    Must be called inside the same ``transaction.atomic()`` block as the
    business change it describes, so both succeed or roll back together.
    Failures raise ``ActivityError`` (or a database error) and are never
    swallowed.

    ``user`` must be the authenticated request user, never a client-supplied
    id.
    """
    if not connection.in_atomic_block:
        raise ActivityError(
            'Activity must be recorded inside the transaction of the '
            'change it describes.'
        )

    if user is None or not getattr(user, 'is_authenticated', False):
        raise ActivityError(
            'Activity requires an authenticated user as the actor.'
        )

    if action not in Activity.Action.values:
        raise ActivityError(f'Unknown activity action: {action!r}.')

    if entity_type not in Activity.EntityType.values:
        raise ActivityError(f'Unknown entity type: {entity_type!r}.')

    if (
        isinstance(entity_id, bool)
        or not isinstance(entity_id, int)
        or entity_id < 1
    ):
        raise ActivityError('entity_id must be a positive integer.')

    if not description:
        raise ActivityError('Activity requires a description.')

    metadata = {} if metadata is None else metadata

    if not isinstance(metadata, dict):
        raise ActivityError('Activity metadata must be a dict.')

    _check_metadata(metadata)

    return Activity.objects.create(
        project=project,
        user=user,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        metadata=metadata,
    )
