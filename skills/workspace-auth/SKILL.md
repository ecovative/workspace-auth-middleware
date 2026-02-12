---
name: workspace-auth
description: "Integrate Google Workspace authentication and group-based authorization into ASGI applications using workspace-auth-middleware. Use when the user asks to: (1) Add Google Workspace authentication to a FastAPI or Starlette app, (2) Protect routes with @require_auth, @require_group, @require_scope, or @requires decorators, (3) Set up group-based or scope-based RBAC with Google Workspace groups, (4) Write tests for authenticated/authorized routes using mock utilities, (5) Configure session-based auth with Authlib and OAuth2, (6) Set up caching for token verification and group fetching."
---

# workspace-auth-middleware

ASGI middleware for Google Workspace authentication with group-based RBAC built on Starlette's authentication system. Works with FastAPI, Starlette, and any ASGI framework.

## Installation

```bash
pip install workspace-auth-middleware
```

## Quick Setup

### 1. Determine the framework

- **FastAPI** or **Starlette** with `app.add_middleware()` pattern
- Bearer token (API) or session-based (web app with login pages)

### 2. Add middleware

**FastAPI:**
```python
from fastapi import FastAPI
from workspace_auth_middleware import WorkspaceAuthMiddleware

app = FastAPI()
app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="your-client-id.apps.googleusercontent.com",  # also accepts a list for multi-client
    required_domains=["example.com"],
    fetch_groups=True,
    # All backend params are supported: enable_token_cache, token_cache_ttl,
    # token_cache_maxsize, enable_group_cache, group_cache_ttl,
    # group_cache_maxsize, enable_session_auth, customer_id, credentials
)
```

**Starlette:**
```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from workspace_auth_middleware import WorkspaceAuthMiddleware

middleware = [
    Middleware(
        WorkspaceAuthMiddleware,
        client_id="your-client-id.apps.googleusercontent.com",
        required_domains=["example.com"],
        fetch_groups=True,
    )
]
app = Starlette(routes=routes, middleware=middleware)
```

**Alternative — use Starlette's AuthenticationMiddleware directly:**
```python
from starlette.middleware.authentication import AuthenticationMiddleware
from workspace_auth_middleware import WorkspaceAuthBackend

backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    fetch_groups=True,
)
app.add_middleware(AuthenticationMiddleware, backend=backend)
```

### 3. Protect routes

Four decorator approaches (pick one per route):

```python
from workspace_auth_middleware import require_auth, require_group, require_scope, requires

# Require authentication
@require_auth
async def protected(request):
    return {"user": request.user.email}

# Require group membership
@require_group("admins@example.com")
async def admin(request):
    return {"admin": True}

# Multiple groups — OR logic (default)
@require_group(["team-a@example.com", "team-b@example.com"])
async def team(request): ...

# Multiple groups — AND logic
@require_group(["managers@example.com", "leads@example.com"], require_all=True)
async def restricted(request): ...

# Require scopes — ALL required by default
@require_scope("authenticated")
async def scoped(request): ...

# Multiple scopes — AND logic (default)
@require_scope(["authenticated", "group:admins@example.com"])
async def admin_scoped(request): ...

# Multiple scopes — OR logic
@require_scope(["group:team-a@example.com", "group:team-b@example.com"], require_all=False)
async def any_team(request): ...

# Starlette scope-based (auto-populated by backend)
@requires("authenticated")
async def protected(request): ...

@requires("group:admins@example.com")
async def admin(request): ...
```

### 4. Access user data

```python
user = request.user
user.email              # "user@example.com"
user.user_id            # Google user ID
user.name               # Display name
user.domain             # "example.com"
user.groups             # ["admins@example.com", ...]
user.is_authenticated   # True
user.has_group("admins@example.com")       # bool
user.has_any_group(["a@x.com", "b@x.com"])  # bool
user.has_all_groups(["a@x.com", "b@x.com"]) # bool
```

## Testing

Use the built-in mock utilities — no Google credentials needed.

### Pytest fixtures (auto-discovered)

When `workspace-auth-middleware` is installed, these fixtures are available automatically:

```python
# override_workspace_auth — patches WorkspaceAuthMiddleware to use mock backend
def test_protected(override_workspace_auth):
    override_workspace_auth(email="user@example.com")
    app = create_my_app()  # uses WorkspaceAuthMiddleware internally
    client = TestClient(app)
    assert client.get("/protected").status_code == 200

def test_admin(override_workspace_auth):
    override_workspace_auth(email="admin@example.com", groups=["admins@example.com"])
    app = create_my_app()
    client = TestClient(app)
    assert client.get("/admin").status_code == 200

def test_anonymous(override_workspace_auth):
    override_workspace_auth()  # no user
    app = create_my_app()
    client = TestClient(app)
    assert client.get("/protected").json()["authenticated"] is False

def test_error(override_workspace_auth):
    override_workspace_auth(error="Token expired")
    app = create_my_app()
    client = TestClient(app)
    assert client.get("/protected").status_code == 401

# workspace_user — factory for WorkspaceUser instances
def test_user(workspace_user):
    user = workspace_user(email="dev@corp.com", groups=["devs@corp.com"])
    assert user.has_group("devs@corp.com")

# mock_workspace_backend — for direct Starlette AuthenticationMiddleware usage
def test_backend(mock_workspace_backend):
    backend = mock_workspace_backend(email="test@corp.com", groups=["team@corp.com"])
    app = Starlette(routes=[...])
    app.add_middleware(AuthenticationMiddleware, backend=backend)
```

### Direct mock classes

```python
from workspace_auth_middleware.testing import (
    MockWorkspaceAuthMiddleware,
    create_workspace_user,
)

# Drop-in replacement — no credentials needed
app.add_middleware(
    MockWorkspaceAuthMiddleware,
    user=create_workspace_user(email="dev@example.com", groups=["devs@example.com"]),
)
```

### Browser/Playwright testing (header mode)

```python
import json
from workspace_auth_middleware.testing import MockWorkspaceAuthMiddleware

# App reads user identity from X-Test-User header
app.add_middleware(MockWorkspaceAuthMiddleware, header_mode=True)

# In Playwright test
page.set_extra_http_headers({
    "X-Test-User": json.dumps({
        "email": "admin@example.com",
        "groups": ["admins@example.com"],
    })
})
page.goto("/dashboard")
```

Requests without the header are anonymous.

## Advanced Topics

- **Session-based auth with Authlib (OAuth2 login flow):** See [references/session-auth.md](references/session-auth.md)
- **Caching configuration and management:** See [references/caching.md](references/caching.md)

## Key Architecture Notes

- `WorkspaceAuthMiddleware` extends Starlette's `AuthenticationMiddleware` and forwards all params to `WorkspaceAuthBackend`
- `client_id` accepts `str` or `List[str]` (multi-client fallback validation)
- `WorkspaceAuthBackend` implements Starlette's `AuthenticationBackend`
- `WorkspaceUser` extends Starlette's `BaseUser`
- Scopes are auto-populated: `"authenticated"` + `"group:<email>"` per group
- `request.user` and `request.auth` are populated by the middleware
- `MockWorkspaceAuthBackend` auto-calculates scopes identically to the real backend
- `fetch_groups=True` requires a service account with Groups Reader role and Cloud Identity API enabled
- `fetch_groups=False` requires no credentials (token-only auth)
