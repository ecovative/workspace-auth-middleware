# FastAPI Integration Guide

This guide provides comprehensive instructions for integrating `workspace-auth-middleware` with [FastAPI](https://fastapi.tiangolo.com/) applications.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration Options](#configuration-options)
- [Integration Methods](#integration-methods)
- [Route Protection](#route-protection)
- [Dependency Injection](#dependency-injection)
- [Session-Based Authentication](#session-based-authentication)
- [Error Handling](#error-handling)
- [OpenAPI Integration](#openapi-integration)
- [Complete Examples](#complete-examples)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- Python 3.12+
- FastAPI 0.100.0+
- Starlette 0.27.0+ (installed with FastAPI)
- Google Workspace domain
- Google OAuth2 client ID (from Google Cloud Console)
- (Optional) Service account credentials for group fetching

## Installation

```bash
pip install workspace-auth-middleware fastapi uvicorn
```

Or with Poetry:

```bash
poetry add workspace-auth-middleware fastapi uvicorn
```

This installs all required dependencies including FastAPI, Starlette, google-auth, and cachetools.

## Quick Start

Here's a minimal FastAPI application with Google Workspace authentication:

```python
from fastapi import FastAPI, Request
from workspace_auth_middleware import (
    WorkspaceAuthMiddleware,
    require_auth,
    require_group,
)

app = FastAPI()

# Add middleware
app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
)

# Public endpoint
@app.get("/")
async def homepage():
    return {"message": "Hello, World!"}

# Protected endpoint
@app.get("/profile")
@require_auth
async def profile(request: Request):
    user = request.user
    return {
        "email": user.email,
        "name": user.name,
        "groups": user.groups,
    }

# Admin-only endpoint
@app.get("/admin")
@require_group("admins@example.com")
async def admin_panel(request: Request):
    return {"message": "Admin access granted"}
```

Run the application:

```bash
uvicorn main:app --reload
```

Test with curl:

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/profile
```

## Configuration Options

### Middleware Options

The `WorkspaceAuthMiddleware` accepts the following parameters:

```python
from fastapi import FastAPI
from workspace_auth_middleware import WorkspaceAuthMiddleware

app = FastAPI()

app.add_middleware(
    WorkspaceAuthMiddleware,
    # Required parameters
    client_id="your-client-id.apps.googleusercontent.com",

    # Optional parameters
    required_domains=["example.com", "partner.com"],  # Restrict to specific domains
    fetch_groups=True,                                 # Fetch user's Google Workspace groups
    credentials=None,                                  # Custom credentials (default: ADC)
    on_error=None,                                    # Custom error handler
)
```

### Backend Options (Advanced)

When using `WorkspaceAuthBackend` directly, you have access to caching options:

```python
from fastapi import FastAPI
from starlette.middleware.authentication import AuthenticationMiddleware
from workspace_auth_middleware import WorkspaceAuthBackend

app = FastAPI()

backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    fetch_groups=True,

    # Cache configuration
    enable_token_cache=True,       # Enable token verification cache
    token_cache_ttl=300,            # Token cache TTL (seconds)
    token_cache_maxsize=1000,       # Max cached tokens
    enable_group_cache=True,        # Enable group cache
    group_cache_ttl=300,            # Group cache TTL (seconds)
    group_cache_maxsize=500,        # Max cached users
    enable_session_auth=True,       # Enable session-based auth
)

app.add_middleware(AuthenticationMiddleware, backend=backend)
```

## Integration Methods

### Method 1: Using WorkspaceAuthMiddleware (Recommended)

The simplest approach is to use `WorkspaceAuthMiddleware` with `app.add_middleware()`:

```python
from fastapi import FastAPI
from workspace_auth_middleware import WorkspaceAuthMiddleware

app = FastAPI()

app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
)
```

**Pros**:
- Simple and concise
- Sensible defaults
- Automatic backend configuration

**Cons**:
- Less control over caching and advanced options

### Method 2: Using Starlette's AuthenticationMiddleware

For more control, use Starlette's `AuthenticationMiddleware` directly:

```python
from fastapi import FastAPI
from starlette.middleware.authentication import AuthenticationMiddleware
from workspace_auth_middleware import WorkspaceAuthBackend

app = FastAPI()

backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    # Full control over caching, credentials, etc.
    enable_token_cache=True,
    token_cache_ttl=120,  # 2 minutes
)

app.add_middleware(AuthenticationMiddleware, backend=backend)
```

**Pros**:
- Full control over backend configuration
- Direct access to Starlette's authentication features
- Custom caching policies

**Cons**:
- More verbose
- Need to understand Starlette's authentication system

### Method 3: Using Middleware List

You can also configure middleware using FastAPI's startup:

```python
from fastapi import FastAPI
from starlette.middleware import Middleware
from workspace_auth_middleware import WorkspaceAuthMiddleware

middleware = [
    Middleware(
        WorkspaceAuthMiddleware,
        client_id="your-client-id.apps.googleusercontent.com",
        required_domains=["example.com"],
    )
]

app = FastAPI(middleware=middleware)
```

**Note**: Middleware added this way is applied in declaration order.

## Route Protection

### Using Decorators

The package provides custom decorators for route protection:

#### @require_auth

Requires user to be authenticated:

```python
from fastapi import FastAPI, Request
from workspace_auth_middleware import require_auth

app = FastAPI()

@app.get("/profile")
@require_auth
async def profile(request: Request):
    return {
        "email": request.user.email,
        "name": request.user.name,
        "groups": request.user.groups,
    }
```

#### @require_group

Requires user to belong to specific Google Workspace group(s):

```python
from workspace_auth_middleware import require_group

# Single group
@app.get("/admin")
@require_group("admins@example.com")
async def admin_panel(request: Request):
    return {"message": "Admin access"}

# Multiple groups (OR logic - user needs at least one)
@app.get("/teams")
@require_group(["team-a@example.com", "team-b@example.com"])
async def team_access(request: Request):
    return {"message": "Team access"}

# Multiple groups (AND logic - user needs all)
@app.get("/restricted")
@require_group(
    ["managers@example.com", "department-leads@example.com"],
    require_all=True
)
async def restricted_access(request: Request):
    return {"message": "Restricted access"}
```

#### @require_scope

Requires specific authentication scope(s):

```python
from workspace_auth_middleware import require_scope

@app.get("/data")
@require_scope("authenticated")
async def get_data(request: Request):
    return {"data": "sensitive information"}
```

### Using Starlette's @requires Decorator

You can also use Starlette's built-in `@requires` decorator:

```python
from workspace_auth_middleware import requires  # Re-exported from Starlette

# Require authentication
@app.get("/protected")
@requires("authenticated")
async def protected_route(request: Request):
    return {"user": request.user.email}

# Require specific group membership
@app.get("/admin")
@requires("group:admins@example.com")
async def admin_route(request: Request):
    return {"message": "Admin access"}

# Require multiple scopes (user needs ALL)
@app.get("/special")
@requires(["authenticated", "group:team-leads@example.com"])
async def special_route(request: Request):
    return {"message": "Team lead access"}
```

**Available Scopes**:
- `"authenticated"` - User is authenticated
- `"group:<group_email>"` - User belongs to specific group (e.g., `"group:admins@example.com"`)

### Manual Checks in Route Handlers

You can also check authentication manually:

```python
from fastapi import FastAPI, Request, HTTPException
from workspace_auth_middleware import PermissionDenied

app = FastAPI()

@app.get("/custom")
async def custom_endpoint(request: Request):
    # Check if authenticated
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required")

    # Check group membership
    if not request.user.has_group("admins@example.com"):
        raise PermissionDenied("Admin access required")

    # Custom logic
    if not custom_permission_check(request.user):
        raise HTTPException(status_code=403, detail="Custom check failed")

    return {"message": "Access granted"}
```

## Dependency Injection

FastAPI's dependency injection system works seamlessly with the middleware:

### Getting Current User

Create a dependency to get the current authenticated user:

```python
from fastapi import Depends, FastAPI, Request
from workspace_auth_middleware import WorkspaceUser, PermissionDenied

app = FastAPI()

def get_current_user(request: Request) -> WorkspaceUser:
    """Dependency to get the current authenticated user."""
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required")
    return request.user

@app.get("/profile")
async def profile(user: WorkspaceUser = Depends(get_current_user)):
    return {
        "email": user.email,
        "name": user.name,
        "groups": user.groups,
    }
```

### Group-Based Dependencies

Create dependencies for specific group requirements:

```python
from fastapi import Depends, Request
from workspace_auth_middleware import WorkspaceUser, PermissionDenied

def get_current_user(request: Request) -> WorkspaceUser:
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required")
    return request.user

def require_admin(user: WorkspaceUser = Depends(get_current_user)) -> WorkspaceUser:
    """Dependency that requires admin group membership."""
    if not user.has_group("admins@example.com"):
        raise PermissionDenied("Admin access required")
    return user

def require_team_member(user: WorkspaceUser = Depends(get_current_user)) -> WorkspaceUser:
    """Dependency that requires team membership."""
    if not user.has_any_group(["team-a@example.com", "team-b@example.com"]):
        raise PermissionDenied("Team membership required")
    return user

# Use in routes
@app.get("/admin/dashboard")
async def admin_dashboard(user: WorkspaceUser = Depends(require_admin)):
    return {"message": f"Welcome, admin {user.email}"}

@app.get("/team/board")
async def team_board(user: WorkspaceUser = Depends(require_team_member)):
    return {"message": f"Welcome, team member {user.email}"}
```

### Composing Dependencies

Dependencies can be composed for complex authorization logic:

```python
from typing import List
from fastapi import Depends, Request
from workspace_auth_middleware import WorkspaceUser, PermissionDenied

def get_current_user(request: Request) -> WorkspaceUser:
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required")
    return request.user

def require_groups(required_groups: List[str], require_all: bool = False):
    """Dependency factory for group-based authorization."""
    def _check_groups(user: WorkspaceUser = Depends(get_current_user)) -> WorkspaceUser:
        if require_all:
            if not user.has_all_groups(required_groups):
                raise PermissionDenied(f"Must belong to all groups: {required_groups}")
        else:
            if not user.has_any_group(required_groups):
                raise PermissionDenied(f"Must belong to at least one group: {required_groups}")
        return user
    return _check_groups

# Use the factory
@app.get("/managers")
async def managers_only(
    user: WorkspaceUser = Depends(require_groups(["managers@example.com"]))
):
    return {"message": f"Welcome, manager {user.email}"}

@app.get("/senior-team")
async def senior_team(
    user: WorkspaceUser = Depends(
        require_groups(["managers@example.com", "senior@example.com"], require_all=True)
    )
):
    return {"message": f"Welcome, senior team member {user.email}"}
```

## Session-Based Authentication

For web applications with login pages, you can combine session-based authentication with the middleware:

```python
from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware
from authlib.integrations.starlette_client import OAuth
from workspace_auth_middleware import WorkspaceAuthBackend, require_auth

app = FastAPI()

# Add SessionMiddleware FIRST
app.add_middleware(SessionMiddleware, secret_key="your-secret-key")

# Add AuthenticationMiddleware with session support
app.add_middleware(
    AuthenticationMiddleware,
    backend=WorkspaceAuthBackend(
        client_id="your-client-id.apps.googleusercontent.com",
        required_domains=["example.com"],
        enable_session_auth=True,  # Enable session support
    ),
)

# Initialize OAuth
oauth = OAuth()
oauth.register(
    name='google',
    client_id='your-client-id.apps.googleusercontent.com',
    client_secret='your-client-secret',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

# OAuth routes
@app.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get('userinfo')

    # Store in session for WorkspaceAuthMiddleware
    request.session['user'] = {
        'email': user_info['email'],
        'user_id': user_info['sub'],
        'name': user_info.get('name'),
        'domain': user_info['email'].split('@')[-1],
    }
    return {"message": "Logged in successfully"}

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out"}

# Protected routes
@app.get("/profile")
@require_auth
async def profile(request: Request):
    return {
        "email": request.user.email,
        "groups": request.user.groups,
    }
```

**Important**: Middleware order matters! `SessionMiddleware` must be added **before** `AuthenticationMiddleware`.

See the complete example: [examples/authlib_fastapi_example.py](../examples/authlib_fastapi_example.py)

## Error Handling

### Default Error Handler

By default, the middleware returns a 401 JSON response for authentication failures:

```json
{
  "error": "Authentication failed",
  "detail": "Token verification failed: ..."
}
```

### Custom Error Handler

You can provide a custom error handler:

```python
from fastapi import FastAPI
from starlette.responses import PlainTextResponse
from workspace_auth_middleware import WorkspaceAuthMiddleware

app = FastAPI()

def custom_error_handler(conn, exc):
    """Custom authentication error handler."""
    return PlainTextResponse(
        f"Access denied: {exc}",
        status_code=403,
    )

app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="...",
    on_error=custom_error_handler,
)
```

### Exception Handlers

Register exception handlers for `PermissionDenied`:

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from workspace_auth_middleware import PermissionDenied

app = FastAPI()

@app.exception_handler(PermissionDenied)
async def permission_denied_handler(request: Request, exc: PermissionDenied):
    return JSONResponse(
        status_code=403,
        content={
            "error": "Permission denied",
            "detail": str(exc),
        },
    )
```

### HTTPException for Custom Errors

You can also use FastAPI's `HTTPException`:

```python
from fastapi import HTTPException, Request

@app.get("/custom")
async def custom_endpoint(request: Request):
    if not request.user.is_authenticated:
        raise HTTPException(status_code=401, detail="Authentication required")

    if not request.user.has_group("admins@example.com"):
        raise HTTPException(status_code=403, detail="Admin access required")

    return {"message": "Access granted"}
```

## OpenAPI Integration

### Document Authentication in OpenAPI

FastAPI's automatic OpenAPI schema generation can document your authentication:

```python
from fastapi import FastAPI, Depends, Request
from fastapi.security import HTTPBearer
from workspace_auth_middleware import WorkspaceUser, PermissionDenied

app = FastAPI()

# Define security scheme for OpenAPI
security = HTTPBearer()

def get_current_user(request: Request) -> WorkspaceUser:
    """Get the current authenticated user."""
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required")
    return request.user

@app.get(
    "/profile",
    summary="Get user profile",
    description="Returns the authenticated user's profile information",
    responses={
        200: {"description": "User profile"},
        401: {"description": "Not authenticated"},
    },
    dependencies=[Depends(security)],  # Document authentication requirement
)
async def profile(user: WorkspaceUser = Depends(get_current_user)):
    return {
        "email": user.email,
        "name": user.name,
        "groups": user.groups,
    }
```

### Custom OpenAPI Schema

Customize the OpenAPI schema to include Google OAuth2:

```python
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

app = FastAPI()

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="My API",
        version="1.0.0",
        description="API with Google Workspace authentication",
        routes=app.routes,
    )

    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "GoogleWorkspace": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Google ID Token from OAuth2 authentication",
        }
    }

    # Apply security globally
    openapi_schema["security"] = [{"GoogleWorkspace": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
```

## Complete Examples

### Example 1: Basic API with Group-Based Access

```python
from fastapi import FastAPI, Request
from workspace_auth_middleware import (
    WorkspaceAuthMiddleware,
    require_auth,
    require_group,
)

app = FastAPI(title="Google Workspace API")

# Add middleware
app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    fetch_groups=True,
)

# Public endpoint
@app.get("/")
async def homepage():
    return {"message": "Welcome to the API"}

# Protected endpoint
@app.get("/profile")
@require_auth
async def get_profile(request: Request):
    user = request.user
    return {
        "email": user.email,
        "name": user.name,
        "domain": user.domain,
        "groups": user.groups,
    }

# Admin-only endpoint
@app.get("/admin/users")
@require_group("admins@example.com")
async def list_users(request: Request):
    return {"users": [...]}

# Multi-group endpoint
@app.get("/support/tickets")
@require_group(["support@example.com", "admins@example.com"])
async def support_tickets(request: Request):
    return {"tickets": [...]}

# Restricted endpoint
@app.get("/restricted/data")
@require_group(
    ["managers@example.com", "leads@example.com"],
    require_all=True
)
async def restricted_data(request: Request):
    return {"data": "highly restricted"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Example 2: Using Dependencies

```python
from fastapi import Depends, FastAPI, Request
from workspace_auth_middleware import (
    WorkspaceAuthMiddleware,
    WorkspaceUser,
    PermissionDenied,
)

app = FastAPI()

app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
)

# Dependencies
def get_current_user(request: Request) -> WorkspaceUser:
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required")
    return request.user

def require_admin(user: WorkspaceUser = Depends(get_current_user)) -> WorkspaceUser:
    if not user.has_group("admins@example.com"):
        raise PermissionDenied("Admin access required")
    return user

# Routes using dependencies
@app.get("/profile")
async def profile(user: WorkspaceUser = Depends(get_current_user)):
    return {
        "email": user.email,
        "name": user.name,
    }

@app.get("/admin/dashboard")
async def admin_dashboard(admin: WorkspaceUser = Depends(require_admin)):
    return {
        "message": f"Welcome, admin {admin.email}",
        "stats": {...},
    }

@app.post("/admin/users")
async def create_user(
    user_data: dict,
    admin: WorkspaceUser = Depends(require_admin),
):
    return {"message": "User created", "created_by": admin.email}
```

### Example 3: Advanced with Caching and Monitoring

```python
from fastapi import Depends, FastAPI, Request
from starlette.middleware.authentication import AuthenticationMiddleware
from google.oauth2 import service_account
from workspace_auth_middleware import (
    WorkspaceAuthBackend,
    WorkspaceUser,
    require_auth,
    require_group,
    PermissionDenied,
)

app = FastAPI(title="Advanced API")

# Load credentials
credentials = service_account.Credentials.from_service_account_file(
    'service-account-key.json',
    scopes=['https://www.googleapis.com/auth/cloud-identity.groups.readonly']
)

# Configure backend
backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    fetch_groups=True,
    credentials=credentials,
    # Custom caching
    enable_token_cache=True,
    token_cache_ttl=120,
    token_cache_maxsize=5000,
    enable_group_cache=True,
    group_cache_ttl=300,
    group_cache_maxsize=2000,
)

# Add middleware
app.add_middleware(AuthenticationMiddleware, backend=backend)

# Dependencies
def get_current_user(request: Request) -> WorkspaceUser:
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required")
    return request.user

# Routes
@app.get("/profile")
async def profile(user: WorkspaceUser = Depends(get_current_user)):
    return {
        "email": user.email,
        "groups": user.groups,
    }

@app.get("/admin/cache/stats")
@require_group("admins@example.com")
async def cache_stats(request: Request):
    """View cache statistics (admin only)."""
    stats = backend.get_cache_stats()
    return stats

@app.post("/admin/cache/clear")
@require_group("admins@example.com")
async def clear_cache(request: Request):
    """Clear all caches (admin only)."""
    backend.clear_caches()
    return {"message": "Caches cleared"}

@app.post("/admin/cache/invalidate/token")
@require_group("admins@example.com")
async def invalidate_token(token: str, request: Request):
    """Invalidate specific token (admin only)."""
    removed = backend.invalidate_token(token)
    return {"removed": removed}

@app.post("/admin/cache/invalidate/user")
@require_group("admins@example.com")
async def invalidate_user_groups(email: str, request: Request):
    """Invalidate user's cached groups (admin only)."""
    removed = backend.invalidate_user_groups(email)
    return {"removed": removed}
```

## Best Practices

### 1. Middleware Order

When combining multiple middleware, order matters:

```python
# Correct order
app.add_middleware(SessionMiddleware, secret_key="...")    # First
app.add_middleware(WorkspaceAuthMiddleware, client_id="...") # Second
```

**Rule**: Session middleware must come before authentication middleware.

### 2. Domain Restrictions

Always restrict to your organization's domains:

```python
app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="...",
    required_domains=["example.com", "partner.com"],  # Explicitly list
)
```

**Don't** leave `required_domains=None` in production.

### 3. Use Dependencies

Prefer FastAPI's dependency injection over decorators for better testability:

```python
# Good: Using dependencies
@app.get("/profile")
async def profile(user: WorkspaceUser = Depends(get_current_user)):
    return {"email": user.email}

# Also good: Using decorators
@app.get("/profile")
@require_auth
async def profile(request: Request):
    return {"email": request.user.email}
```

### 4. Environment Variables

Use environment variables for configuration:

```python
import os

app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    required_domains=os.getenv("ALLOWED_DOMAINS", "example.com").split(","),
)
```

### 5. Error Handling

Implement proper exception handlers:

```python
from workspace_auth_middleware import PermissionDenied

@app.exception_handler(PermissionDenied)
async def permission_denied_handler(request: Request, exc: PermissionDenied):
    return JSONResponse(
        status_code=403,
        content={"error": str(exc)},
    )
```

### 6. OpenAPI Documentation

Document authentication requirements in OpenAPI:

```python
from fastapi.security import HTTPBearer

security = HTTPBearer()

@app.get("/protected", dependencies=[Depends(security)])
async def protected_route(user: WorkspaceUser = Depends(get_current_user)):
    return {"user": user.email}
```

## Troubleshooting

### Problem: 401 Unauthorized on all requests

**Cause**: Missing or invalid Authorization header.

**Solution**: Ensure clients send `Authorization: Bearer <google_id_token>`:

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/profile
```

### Problem: "Token verification failed"

**Cause**: Invalid or expired Google ID token.

**Solution**:
1. Verify token is valid
2. Ensure `client_id` matches token's `aud` claim
3. Check token hasn't expired

### Problem: Groups are empty

**Cause**: Group fetching not configured.

**Solution**:
1. Set `GOOGLE_APPLICATION_CREDENTIALS`
2. Enable `fetch_groups=True`
3. Verify service account has Groups Reader role in Google Workspace Admin
4. Ensure Cloud Identity API is enabled in Google Cloud Console

### Problem: Dependencies not working

**Cause**: Middleware not properly installed.

**Solution**:
1. Verify middleware is added via `app.add_middleware()`
2. Check middleware order
3. Ensure `request.user` is populated

### Problem: request.user is always anonymous

**Cause**: Authentication failed silently or middleware not registered.

**Solution**:
1. Check middleware is registered
2. Verify valid token is sent
3. Check logs for errors

## Related Documentation

- [Architecture and Code Structure](./ARCHITECTURE.md)
- [Starlette Integration Guide](./STARLETTE_INTEGRATION.md)
- [Session Authentication Guide](./SESSION_AUTHENTICATION.md)
- [Testing Guide](./TESTING_GUIDE.md)

## External References

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [FastAPI Middleware](https://fastapi.tiangolo.com/advanced/middleware/)
- [FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Starlette Authentication](https://www.starlette.io/authentication/)
- [Google ID Token Verification](https://developers.google.com/identity/sign-in/web/backend-auth)
- [Authlib FastAPI Integration](https://docs.authlib.org/en/latest/client/fastapi.html)
