# Comments

Discussion on an issue. Comments record what people *say*; the activity log
records what people *do*. The two are deliberately separate: comment changes
do not create activity events.

## Endpoints

| Method | URL | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/issues/{issue_id}/comments/` | List, oldest first, paginated (`page`, `page_size`; 20 per page, max 100) |
| `POST` | `/api/v1/issues/{issue_id}/comments/` | Add a comment (`{"body": "..."}`) |
| `GET` | `/api/v1/issues/{issue_id}/comments/{comment_id}/` | One comment |
| `PATCH` | `/api/v1/issues/{issue_id}/comments/{comment_id}/` | Edit the text (`{"body": "..."}`) |
| `DELETE` | `/api/v1/issues/{issue_id}/comments/{comment_id}/` | Delete; returns the tombstone |

Only `body` is writable. The author is always the authenticated user and the
issue comes from the URL; any other field in the request is ignored.

## Who can do what

| | Manager | Team member | Viewer |
| --- | --- | --- | --- |
| Read | yes | yes | yes |
| Add | yes | yes | no |
| Edit | own comments | own comments | no |
| Delete | any comment (moderation) | own comments | no |

- Nobody edits someone else's words, whatever their role.
- Non-members, and everyone for archived projects, get the same 404 as the
  issue endpoints. Comments on an archived issue can be read but not changed.
- A member who is later made a viewer can no longer edit or delete their old
  comments; a manager still can delete them.

## Response

```json
{
  "id": 501,
  "issue": 102,
  "author": {"id": 12, "username": "sam"},
  "body": "@priya could you check the token refresh?",
  "mentions": [{"id": 7, "username": "priya"}],
  "created_at": "2026-10-11T10:15:00Z",
  "updated_at": "2026-10-11T10:15:00Z",
  "edited_at": null,
  "is_deleted": false,
  "deleted_at": null
}
```

- `edited_at` is set only when the text actually changes (show an "edited"
  label when it is not null). Saving identical text is not an edit.
- `body` is plain text, stored exactly as written. **Escape it when rendering;
  never insert it as HTML.** Text is trimmed, must not be empty or whitespace
  only, and is limited to 5000 characters.

## Deleting

Deletion is soft. The comment stays in the discussion so replies keep their
context, but its text is erased from storage and the API returns
`"body": null, "is_deleted": true, "mentions": []`. The row records
`deleted_by` (the author, or the manager who moderated it). Show
"This comment was deleted." A deleted comment cannot be edited or deleted
again. Hard deletion is only available to site admins in the Django admin.

## Mentions

`@username` in the text is matched, case-insensitively, against the members
of the issue's project (viewers included). Matches are returned in
`mentions` in order of first appearance so the client can render them as
links. Unknown names, people outside the project and email addresses are left
as plain text. The server derives mentions from the text; user ids sent by the
client are ignored. Mentions are recomputed on every edit.

There are no notifications: a mention only records and links the person.
