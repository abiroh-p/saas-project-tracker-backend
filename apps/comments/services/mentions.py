import re

# "@name" where the "@" starts the text or follows whitespace or punctuation,
# so email addresses ("a@b.com") and "@@x" are not mentions. The name cannot
# end with "." or "-", so "thanks @sam." mentions "sam".
MENTION_PATTERN = re.compile(
    r'(?<![\w@.])@([A-Za-z0-9_](?:[A-Za-z0-9._-]*[A-Za-z0-9_])?)'
)

# Bounds the work for a pathological comment.
MAX_MENTIONS = 20


def extract_mentioned_usernames(text):
    """Usernames mentioned in `text`, lowercased, in order of first
    appearance, without duplicates."""
    usernames = []

    for match in MENTION_PATTERN.finditer(text or ''):
        username = match.group(1).lower()

        if username not in usernames:
            usernames.append(username)

        if len(usernames) == MAX_MENTIONS:
            break

    return usernames
