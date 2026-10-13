"""Settings for running the test suite (local and CI).

    python manage.py test --settings=config.test_settings

Identical to config.settings except for a fast password hasher: Django's default PBKDF2 hasher is
deliberately slow, which makes a suite that creates many users take close to an hour.
"""

from .settings import *  # noqa: F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Existing tests log in and register far more often than real clients would; the throttle itself is
# covered explicitly in config/test_production.py with a low rate patched in.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {"login": "1000/min", "register": "1000/min"},
}
