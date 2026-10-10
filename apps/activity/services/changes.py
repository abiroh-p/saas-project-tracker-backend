from datetime import date, datetime


def json_safe(value):
    """Convert a model value into something a JSONField can store."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value


def build_changes(instance, validated_data, *, redact=()):
    """Compare validated input with the persisted values.

    Call this *before* applying the input to the instance. Fields whose value
    is unchanged are left out, so an empty result means a no-op update.

    Fields named in ``redact`` (long free text such as descriptions) are
    recorded as ``{"changed": True}`` instead of storing the old and new text.
    """
    changes = {}

    for field, new_value in validated_data.items():
        old_value = getattr(instance, field)

        if old_value == new_value:
            continue

        if field in redact:
            changes[field] = {'changed': True}
        else:
            changes[field] = {
                'from': json_safe(old_value),
                'to': json_safe(new_value),
            }

    return changes
