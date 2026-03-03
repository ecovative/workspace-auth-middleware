# Session-Based Authentication with Authlib

Use this approach for web applications with browser-based login pages. Authlib handles the OAuth2 authorization code flow; workspace-auth-middleware handles Google Workspace features (domain validation, group fetching, authorization).

## Middleware Order

SessionMiddleware MUST come before AuthenticationMiddleware:

```python
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware
from workspace_auth_middleware import WorkspaceAuthBackend

middleware = [
    Middleware(SessionMiddleware, secret_key="your-secret-key", max_age=86400),
    Middleware(
        AuthenticationMiddleware,
        backend=WorkspaceAuthBackend(
            client_id="your-client-id.apps.googleusercontent.com",
            required_domains=["example.com"],
            fetch_groups=True,
            enable_session_auth=True,
        ),
    ),
]
```

## FastAPI + Authlib Example

```python
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware
from authlib.integrations.starlette_client import OAuth
from workspace_auth_middleware import WorkspaceAuthBackend, require_auth, require_group

oauth = OAuth()
oauth.register(
    name="google",
    client_id="your-client-id.apps.googleusercontent.com",
    client_secret="your-client-secret",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

app = FastAPI(
    middleware=[
        Middleware(SessionMiddleware, secret_key="your-secret-key", max_age=86400),
        Middleware(
            AuthenticationMiddleware,
            backend=WorkspaceAuthBackend(
                client_id="your-client-id.apps.googleusercontent.com",
                required_domains=["example.com"],
                fetch_groups=True,
                enable_session_auth=True,
            ),
        ),
    ],
)

@app.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo")
    request.session["user"] = {
        "email": user_info["email"],
        "user_id": user_info["sub"],
        "name": user_info.get("name"),
        "domain": user_info["email"].split("@")[-1],
        "groups": [],
    }
    return RedirectResponse(url="/")

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@app.get("/profile")
@require_auth
async def profile(request: Request):
    return {"email": request.user.email, "groups": request.user.groups}

@app.get("/admin")
@require_group("admins@example.com")
async def admin(request: Request):
    return {"message": "Admin access granted"}
```

## Session Data Format

The backend reads `request.session["user"]` with these fields:

| Field | Required | Description |
|-------|----------|-------------|
| `email` | Yes | User's email address |
| `user_id` | Yes | Google user ID (from `sub` claim) |
| `name` | No | Display name (defaults to email) |
| `domain` | No | Workspace domain (derived from email if absent) |
| `groups` | No | List of group emails (defaults to `[]`). Ignored when `fetch_groups=True` — groups are fetched from the API instead. |

## Group Fetching for Session Auth

When `fetch_groups=True` (default), the backend fetches groups from the Google API (Cloud Identity or Admin SDK) for session-authenticated users, just like it does for bearer token auth. The group cache is shared between both auth paths.

- `fetch_groups=True`: groups fetched from API on each request (cached), session `groups` field ignored
- `fetch_groups=False`: session `groups` field used as-is

## Authentication Priority

When `enable_session_auth=True`, the backend checks in this order:

1. Session data (`request.session["user"]`) → fetch groups from API if `fetch_groups=True`
2. Bearer token (`Authorization: Bearer <token>`) → verify token, fetch groups if `fetch_groups=True`
3. Neither present -> anonymous user
