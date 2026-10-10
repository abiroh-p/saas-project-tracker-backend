class ActivityError(Exception):
    """Base class for activity-log failures.

    Deliberately not a ``ValueError`` or ``PermissionError``: the views turn
    those into 400/403 responses, and a failure to write the audit trail must
    never be reported as a client error. It propagates as a server error and
    rolls back the surrounding transaction.
    """


class ImmutableActivityError(ActivityError):
    """Raised when something tries to change or delete recorded activity."""
