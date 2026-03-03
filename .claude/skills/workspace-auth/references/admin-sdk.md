# Admin SDK Directory API (Business Standard)

Use the Admin SDK path when your Google Workspace edition is **Business Standard** (or any edition without Cloud Identity Premium). The default Cloud Identity Groups API (`searchTransitiveGroups`) requires Enterprise or Cloud Identity Premium and returns `403 PERMISSION_DENIED` on lower-tier plans.

## When to Use

| Workspace Edition | API | Parameter |
|---|---|---|
| Enterprise / Cloud Identity Premium | Cloud Identity (default) | No extra params needed |
| Business Standard / Business Plus | Admin SDK Directory | `delegated_admin="admin@example.com"` |

## Prerequisites

1. **Service account** with domain-wide delegation enabled
2. **Admin Console** > Security > API Controls > Domain-wide delegation:
   - Add the service account's client ID
   - Grant scopes: `https://www.googleapis.com/auth/admin.directory.group.readonly`, `https://www.googleapis.com/auth/admin.directory.group.member.readonly`
3. **Delegated admin email** — any Workspace admin account (the service account impersonates this user)

## Configuration

```python
from workspace_auth_middleware import WorkspaceAuthMiddleware

app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    fetch_groups=True,
    delegated_admin="admin@example.com",  # triggers Admin SDK path
    target_groups=[                        # recommended for efficiency
        "admins@example.com",
        "developers@example.com",
        "team-leads@example.com",
    ],
)
```

Or via backend directly:

```python
from workspace_auth_middleware import WorkspaceAuthBackend

backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    delegated_admin="admin@example.com",
    target_groups=["admins@example.com", "developers@example.com"],
)
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `delegated_admin` | `Optional[str]` | `None` | Workspace admin email. When set, uses Admin SDK instead of Cloud Identity. |
| `target_groups` | `Optional[List[str]]` | `None` | Specific groups to check membership for. Dramatically improves efficiency. Also filters Cloud Identity results when set. |

## How target_groups Works

Without `target_groups`, Admin SDK returns only **direct** group memberships (no transitive resolution).

With `target_groups`, the backend uses an efficient BFS algorithm:

1. Fetch user's direct groups (1 paginated API call)
2. Instant match: `direct_groups ∩ target_groups`
3. For each remaining target, BFS top-down through `members.list()`:
   - Check if any GROUP-type member is in user's direct groups
   - Queue nested GROUP-type members for deeper check (max depth: 5)
   - Stop per target as soon as a match is found

**Typical cost:** 1 call (direct groups) + 1-2 calls per non-direct target = ~4-7 total API calls.

## target_groups with Cloud Identity

When `target_groups` is set without `delegated_admin`, it filters the Cloud Identity `searchTransitiveGroups` results to only return matching groups. This can be useful for limiting the scopes generated.

## Credential Requirements

**With `delegated_admin`:**
- Service account key file (set `GOOGLE_APPLICATION_CREDENTIALS`)
- Domain-wide delegation configured
- Compute Engine default credentials will NOT work (no `with_subject` support)

**Without `delegated_admin` (Cloud Identity):**
- Service account with Groups Reader role
- No domain-wide delegation needed
- Compute Engine credentials work

## Error Handling

- If credentials lack `with_subject` (e.g., Compute Engine), a clear error is logged and `credentials` is set to `None`
- API errors return empty group list (authentication still succeeds, just without groups)
- Invalid email addresses are rejected before API calls

## Environment Variables

```bash
# Service account key (required for Admin SDK path)
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"

# Optional: used for delegated admin in integration tests
export GOOGLE_DELEGATED_ADMIN="admin@example.com"
```
