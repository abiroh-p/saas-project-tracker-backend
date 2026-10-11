"""Small helpers for validating list-endpoint query parameters.

Views translate a `QueryParamError` into the project's standard 400 response:

    try:
        ...
    except QueryParamError as exc:
        return api_error(str(exc), 'bad_request', status.HTTP_400_BAD_REQUEST)
"""

SEARCH_MAX_LENGTH = 100


class QueryParamError(Exception):
    """A query parameter is present but invalid. `str(exc)` is client-safe."""


def get_search_term(params):
    """Return the cleaned `search` term, or None when none was supplied.

    A missing, empty or whitespace-only `search` means "no search" so that a
    frontend can send an empty search box without special-casing it.
    """
    raw = params.get('search')

    if raw is None:
        return None

    term = raw.strip()

    if not term:
        return None

    # PostgreSQL cannot store or compare NUL characters; without this check
    # `?search=%00` would surface as a 500 from the database driver.
    if '\x00' in term:
        raise QueryParamError('Invalid search term.')

    if len(term) > SEARCH_MAX_LENGTH:
        raise QueryParamError(
            f'Search term must be at most {SEARCH_MAX_LENGTH} characters.'
        )

    return term
