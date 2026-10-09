import re
import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

User = get_user_model()

USERNAME_MAX_LENGTH = User._meta.get_field("username").max_length
# Leave room for a numeric suffix such as "john.doe123".
USERNAME_BASE_MAX_LENGTH = USERNAME_MAX_LENGTH - 8
MAX_CREATE_ATTEMPTS = 5


class EmailAlreadyRegistered(Exception):
    pass


def username_base_from_email(email):
    """Turn the local part of an email into a safe username stem."""
    local_part = email.split("@", 1)[0].lower()
    stem = re.sub(r"[^a-z0-9._-]", "", local_part).strip("._-")

    return (stem or "user")[:USERNAME_BASE_MAX_LENGTH]


def generate_username(base):
    """Return `base`, or `base` plus a number, that no user has yet.

    Uniqueness is checked case-insensitively so "John" and "john" never
    coexist, even though the database column itself is case-sensitive.
    """
    taken = {
        username.lower()
        for username in User.objects.filter(
            username__istartswith=base,
        ).values_list("username", flat=True)
    }

    if base not in taken:
        return base

    for number in range(2, 10_000):
        candidate = f"{base}{number}"
        if candidate not in taken:
            return candidate

    return f"{base}{secrets.token_hex(3)}"


def register_user(*, full_name, email, password):
    email = email.strip().lower()
    base = username_base_from_email(email)

    for _ in range(MAX_CREATE_ATTEMPTS):
        username = generate_username(base)

        try:
            with transaction.atomic():
                return User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    full_name=full_name,
                )
        except IntegrityError:
            # Either the email was taken by a concurrent request, or the
            # generated username was. Only the second case is worth retrying.
            if User.objects.filter(email__iexact=email).exists():
                raise EmailAlreadyRegistered(email)

    raise RuntimeError("Could not generate a unique username.")
