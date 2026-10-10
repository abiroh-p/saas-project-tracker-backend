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

| `ISSUE_CREATED` | ISSUE | `{"issue_key": "ACT-1", "title": "...", "issue_type": "BUG", "priority": "HIGH", "assignee": <user> or null}` |
| `ISSUE_UPDATED` | ISSUE | `{"changes": {"priority": {"from": "MEDIUM", "to": "HIGH"}}}` (a changed `description` is `{"changed": true}`; status and assignee are never in here) |
| `ISSUE_ASSIGNED` | ISSUE | `{"from": <user> or null, "to": <user>}` |
| `ISSUE_UNASSIGNED` | ISSUE | `{"from": <user>, "to": null}`, plus `"reason": "member_removed"` when a member's removal unassigned it |
| `ISSUE_STATUS_CHANGED` | ISSUE | `{"from": "TODO", "to": "IN_PROGRESS"}` |
| `ISSUE_ARCHIVED` | ISSUE | `{"issue_key": "ACT-1"}` |

`entity_id` is the membership id for membership events, even after the
membership row is deleted, and the issue id for issue events.

A request that changes the assignee and other fields produces separate events
(`ISSUE_UPDATED` plus `ISSUE_ASSIGNED` or `ISSUE_UNASSIGNED`). Status changes
only happen through the transition endpoint, so they never share an event with
a field update. An issue created with an assignee is one `ISSUE_CREATED` event.

## API

Authenticated project members can read the project activity feed:

`GET /api/v1/projects/<project_id>/activity/`

The response is paginated with `count`, `next`, `previous`, and `results`.
Each result contains `id`, the actor's `user` (`id` and `username`), action,
entity information, description, metadata, and `created_at`.

Optional query filters are `action`, `entity_type`, and `entity_id`.
The feed is ordered newest first. Non-members receive `404`.
