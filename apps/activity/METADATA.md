# Activity metadata

`metadata` is the structured source of truth; `description` is a readable
snapshot. Metadata stores raw values (`MEDIUM`, `IN_PROGRESS`, ISO dates), never
display labels. It never holds credentials, emails or long free text.

Single-subject actions use a top-level `from` / `to`. Multi-field updates use
`changes`. Users are always `{"id": 1, "username": "sam"}`.

| Action | Entity | Metadata |
| --- | --- | --- |
| `PROJECT_CREATED` | PROJECT | `{"key": "ACT", "name": "..."}` |
| `PROJECT_UPDATED` | PROJECT | `{"changes": {"name": {"from": "A", "to": "B"}}}` (a changed `description` is `{"changed": true}`) |
| `PROJECT_ARCHIVED` | PROJECT | `{"key": "ACT"}` |
| `MEMBER_ADDED` | MEMBERSHIP | `{"member": <user>, "role": "VIEWER"}` |
| `ROLE_CHANGED` | MEMBERSHIP | `{"member": <user>, "from": "TEAM_MEMBER", "to": "VIEWER"}` |
| `MEMBER_REMOVED` | MEMBERSHIP | `{"member": <user>, "role": "VIEWER", "self_removed": false}` |
| `ISSUE_UNASSIGNED` (member removed) | ISSUE | `{"from": <user>, "to": null, "reason": "member_removed"}` |

`entity_id` is the membership id for membership events, even after the
membership row is deleted.

Issue events (`ISSUE_*`) are added with the issue integration step.
