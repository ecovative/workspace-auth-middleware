# Starlette Integration Guide

This guide provides comprehensive instructions for integrating `workspace-auth-middleware` with [Starlette](https://www.starlette.io/) applications.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration Options](#configuration-options)
- [Integration Methods](#integration-methods)
- [Route Protection](#route-protection)
- [Session-Based Authentication](#session-based-authentication)
- [Error Handling](#error-handling)
- [Complete Examples](#complete-examples)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- Python 3.12+
- Starlette 0.27.0+
- Google Workspace domain
- Google OAuth2 client ID (from Google Cloud Console)
- (Optional) Service account credentials for group fetching

## Installation

```bash
pip install workspace-auth-middleware
```

Or with Poetry:

```bash
poetry add workspace-auth-middleware
```

This installs all required dependencies including Starlette, google-auth, and cachetools.

## Quick Start

Here's a minimal Starlette application with Google Workspace authentication:

```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from workspace_auth_middleware import (
    WorkspaceAuthMiddleware,
    require_auth,
)

# Define routes
async def homepage(request: Request):
    return JSONResponse({"message": "Hello, World!"})

@require_auth
async def protected(request: Request):
    return JSONResponse({
        "user": request.user.email,
        "groups": request.user.groups,
    })

# Configure middleware
middleware = [
    Middleware(
        WorkspaceAuthMiddleware,
        client_id="your-client-id.apps.googleusercontent.com",
        required_domains=["example.com"],
    )
]

# Create application
routes = [
    Route("/", homepage),
    Route("/protected", protected),
]

app = Starlette(routes=routes, middleware=middleware)
```

## Configuration Options

### Middleware Options

The `WorkspaceAuthMiddleware` accepts the following parameters:

```python
from starlette.middleware import Middleware
from workspace_auth_middleware import WorkspaceAuthMiddleware

middleware = [
    Middleware(
        WorkspaceAuthMiddleware,
        # Required parameters
        client_id="your-client-id.apps.googleusercontent.com",

        # Optional parameters
        required_domains=["example.com", "partner.com"],  # Restrict to specific domains
        fetch_groups=True,                                 # Fetch user's Google Workspace groups
        credentials=None,                                  # Custom credentials (default: ADC)
        delegated_admin="admin@example.com",              # Admin email for delegation
        on_error=None,                                    # Custom error handler
    )
]
```

### Backend Options (Advanced)

When using `WorkspaceAuthBackend` directly, you have access to caching options:

```python
from starlette.middleware.authentication import AuthenticationMiddleware
from workspace_auth_middleware import WorkspaceAuthBackend

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

middleware = [
    Middleware(AuthenticationMiddleware, backend=backend)
]
```

## Integration Methods

### Method 1: Using WorkspaceAuthMiddleware (Recommended)

The simplest approach is to use `WorkspaceAuthMiddleware`:

```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from workspace_auth_middleware import WorkspaceAuthMiddleware

middleware = [
    Middleware(
        WorkspaceAuthMiddleware,
        client_id="your-client-id.apps.googleusercontent.com",
        required_domains=["example.com"],
    )
]

app = Starlette(routes=routes, middleware=middleware)
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
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from workspace_auth_middleware import WorkspaceAuthBackend

backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    # Full control over caching, credentials, etc.
    enable_token_cache=True,
    token_cache_ttl=120,  # 2 minutes
)

middleware = [
    Middleware(AuthenticationMiddleware, backend=backend)
]

app = Starlette(routes=routes, middleware=middleware)
```

**Pros**:
- Full control over backend configuration
- Direct access to Starlette's authentication features
- Custom caching policies

**Cons**:
- More verbose
- Need to understand Starlette's authentication system

### Method 3: add_middleware() (Runtime)

You can also add middleware at runtime:

```python
from starlette.applications import Starlette
from workspace_auth_middleware import WorkspaceAuthMiddleware

app = Starlette(routes=routes)

# Add middleware after app creation
app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
)
```

**Note**: Middleware added with `add_middleware()` is applied in reverse order (LIFO).

## Route Protection

### Using Decorators

The package provides custom decorators for route protection:

#### @require_auth

Requires user to be authenticated:

```python
from starlette.responses import JSONResponse
from workspace_auth_middleware import require_auth

@require_auth
async def protected_endpoint(request):
    return JSONResponse({
        "user": request.user.email,
        "name": request.user.name,
    })
```

#### @require_group

Requires user to belong to specific Google Workspace group(s):

```python
from workspace_auth_middleware import require_group

# Single group
@require_group("admins@example.com")
async def admin_endpoint(request):
    return JSONResponse({"message": "Admin access"})

# Multiple groups (OR logic - user needs at least one)
@require_group(["team-a@example.com", "team-b@example.com"])
async def team_endpoint(request):
    return JSONResponse({"message": "Team access"})

# Multiple groups (AND logic - user needs all)
@require_group(
    ["managers@example.com", "department-leads@example.com"],
    require_all=True
)
async def restricted_endpoint(request):
    return JSONResponse({"message": "Restricted access"})
```

#### @require_scope

Requires specific authentication scope(s):

```python
from workspace_auth_middleware import require_scope

@require_scope("authenticated")
async def data_endpoint(request):
    return JSONResponse({"data": "sensitive information"})
```

### Using Starlette's @requires Decorator

You can also use Starlette's built-in `@requires` decorator with scopes populated by `WorkspaceAuthBackend`:

```python
from workspace_auth_middleware import requires  # Re-exported from Starlette

# Require authentication
@requires("authenticated")
async def protected_endpoint(request):
    return JSONResponse({"user": request.user.email})

# Require specific group membership
@requires("group:admins@example.com")
async def admin_endpoint(request):
    return JSONResponse({"message": "Admin access"})

# Require multiple scopes (user needs ALL)
@requires(["authenticated", "group:team-leads@example.com"])
async def team_lead_endpoint(request):
    return JSONResponse({"message": "Team lead access"})
```

**Available Scopes**:
- `"authenticated"` - User is authenticated
- `"group:<group_email>"` - User belongs to specific group (e.g., `"group:admins@example.com"`)

### Manual Checks in Route Handlers

You can also check authentication manually:

```python
from starlette.responses import JSONResponse
from workspace_auth_middleware import PermissionDenied

async def custom_endpoint(request):
    # Check if authenticated
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required")

    # Check group membership
    if not request.user.has_group("admins@example.com"):
        raise PermissionDenied("Admin access required")

    # Custom logic
    if not custom_permission_check(request.user):
        raise PermissionDenied("Custom permission check failed")

    return JSONResponse({"message": "Access granted"})
```

## Session-Based Authentication

For web applications with login pages, you can combine session-based authentication with the middleware:

```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware
from workspace_auth_middleware import WorkspaceAuthBackend, require_auth

# Configure middleware - ORDER MATTERS!
middleware = [
    # SessionMiddleware MUST come FIRST
    Middleware(SessionMiddleware, secret_key="your-secret-key"),
    # AuthenticationMiddleware with session support
    Middleware(
        AuthenticationMiddleware,
        backend=WorkspaceAuthBackend(
            client_id="your-client-id.apps.googleusercontent.com",
            required_domains=["example.com"],
            enable_session_auth=True,  # Enable session support
        ),
    ),
]

app = Starlette(routes=routes, middleware=middleware)
```

### OAuth2 Login Flow with Authlib

For a complete OAuth2 implementation with session-based authentication, see the [Session Authentication Guide](./SESSION_AUTHENTICATION.md) or check out the example:

- [examples/authlib_starlette_example.py](../examples/authlib_starlette_example.py)

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
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.middleware import Middleware
from workspace_auth_middleware import WorkspaceAuthMiddleware

def custom_error_handler(conn, exc):
    """Custom authentication error handler."""
    return PlainTextResponse(
        f"Access denied: {exc}",
        status_code=403,
    )

middleware = [
    Middleware(
        WorkspaceAuthMiddleware,
        client_id="...",
        on_error=custom_error_handler,
    )
]
```

### Exception Handling in Routes

The decorators raise `PermissionDenied` exceptions that you can catch:

```python
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from workspace_auth_middleware import PermissionDenied

async def permission_denied_handler(request: Request, exc: PermissionDenied):
    return JSONResponse(
        {"error": "Permission denied", "detail": str(exc)},
        status_code=403,
    )

# Register exception handler
app = Starlette(
    routes=routes,
    middleware=middleware,
    exception_handlers={
        PermissionDenied: permission_denied_handler,
    }
)
```

## Complete Examples

### Example 1: Basic API with Group-Based Access

```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from workspace_auth_middleware import (
    WorkspaceAuthMiddleware,
    require_auth,
    require_group,
)

# Route handlers
async def homepage(request: Request):
    return JSONResponse({"message": "Public homepage"})

@require_auth
async def profile(request: Request):
    user = request.user
    return JSONResponse({
        "email": user.email,
        "name": user.name,
        "domain": user.domain,
        "groups": user.groups,
    })

@require_group("admins@example.com")
async def admin_panel(request: Request):
    return JSONResponse({"message": "Admin panel"})

@require_group(["support@example.com", "admins@example.com"])
async def support_tickets(request: Request):
    return JSONResponse({"tickets": [...]})

# Configure middleware
middleware = [
    Middleware(
        WorkspaceAuthMiddleware,
        client_id="your-client-id.apps.googleusercontent.com",
        required_domains=["example.com"],
        fetch_groups=True,
    )
]

# Create app
routes = [
    Route("/", homepage),
    Route("/profile", profile),
    Route("/admin", admin_panel),
    Route("/support", support_tickets),
]

app = Starlette(routes=routes, middleware=middleware)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Example 2: Advanced Configuration with Caching

```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from google.oauth2 import service_account

from workspace_auth_middleware import (
    WorkspaceAuthBackend,
    require_auth,
    require_group,
)

# Load custom credentials
credentials = service_account.Credentials.from_service_account_file(
    'service-account-key.json',
    scopes=['https://www.googleapis.com/auth/admin.directory.group.readonly']
)

# Configure backend with custom caching
backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    fetch_groups=True,
    credentials=credentials,
    delegated_admin="admin@example.com",
    # Custom cache settings
    enable_token_cache=True,
    token_cache_ttl=120,        # 2 minutes
    token_cache_maxsize=5000,   # 5000 tokens
    enable_group_cache=True,
    group_cache_ttl=300,        # 5 minutes
    group_cache_maxsize=2000,   # 2000 users
)

# Route handlers
@require_auth
async def profile(request: Request):
    return JSONResponse({"user": request.user.email})

@require_group("admins@example.com")
async def cache_stats(request: Request):
    """Admin endpoint to view cache statistics."""
    stats = backend.get_cache_stats()
    return JSONResponse(stats)

@require_group("admins@example.com")
async def clear_cache(request: Request):
    """Admin endpoint to clear caches."""
    backend.clear_caches()
    return JSONResponse({"message": "Caches cleared"})

# Configure middleware
middleware = [
    Middleware(AuthenticationMiddleware, backend=backend)
]

# Create app
routes = [
    Route("/profile", profile),
    Route("/admin/cache/stats", cache_stats),
    Route("/admin/cache/clear", clear_cache, methods=["POST"]),
]

app = Starlette(routes=routes, middleware=middleware)
```

### Example 3: Session-Based Web Application

```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route
from authlib.integrations.starlette_client import OAuth

from workspace_auth_middleware import (
    WorkspaceAuthBackend,
    require_auth,
    require_group,
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

# Route handlers
async def homepage(request: Request):
    return JSONResponse({"message": "Welcome!"})

async def login(request: Request):
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get('userinfo')

    # Store in session
    request.session['user'] = {
        'email': user_info['email'],
        'user_id': user_info['sub'],
        'name': user_info.get('name'),
        'domain': user_info['email'].split('@')[-1],
    }
    return RedirectResponse(url='/')

async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url='/')

@require_auth
async def profile(request: Request):
    return JSONResponse({
        "email": request.user.email,
        "groups": request.user.groups,
    })

@require_group('admins@example.com')
async def admin(request: Request):
    return JSONResponse({"message": "Admin panel"})

# Configure middleware - ORDER MATTERS!
middleware = [
    Middleware(SessionMiddleware, secret_key="your-secret-key"),
    Middleware(
        AuthenticationMiddleware,
        backend=WorkspaceAuthBackend(
            client_id="your-client-id.apps.googleusercontent.com",
            required_domains=["example.com"],
            enable_session_auth=True,
        ),
    ),
]

# Create app
routes = [
    Route("/", homepage),
    Route("/login", login),
    Route("/auth/callback", auth_callback),
    Route("/logout", logout),
    Route("/profile", profile),
    Route("/admin", admin),
]

app = Starlette(routes=routes, middleware=middleware)
```

See the complete example: [examples/authlib_starlette_example.py](../examples/authlib_starlette_example.py)

## Best Practices

### 1. Middleware Order

When combining multiple middleware, order matters:

```python
middleware = [
    Middleware(SessionMiddleware, ...),       # First
    Middleware(AuthenticationMiddleware, ...), # Second
    Middleware(OtherMiddleware, ...),          # Third
]
```

**Rule**: Session middleware must come before authentication middleware.

### 2. Domain Restrictions

Always restrict to your organization's domains:

```python
Middleware(
    WorkspaceAuthMiddleware,
    client_id="...",
    required_domains=["example.com", "partner.com"],  # Explicitly list domains
)
```

**Don't** leave `required_domains=None` in production (allows any domain).

### 3. Group Fetching

Enable group fetching for RBAC:

```python
Middleware(
    WorkspaceAuthMiddleware,
    client_id="...",
    fetch_groups=True,  # Enable for group-based authorization
    delegated_admin="admin@example.com",
)
```

### 4. Cache Configuration

Adjust cache TTLs based on your security requirements:

```python
# Security-sensitive application
backend = WorkspaceAuthBackend(
    client_id="...",
    token_cache_ttl=60,   # 1 minute
    group_cache_ttl=120,  # 2 minutes
)

# Performance-focused application
backend = WorkspaceAuthBackend(
    client_id="...",
    token_cache_ttl=600,  # 10 minutes
    group_cache_ttl=900,  # 15 minutes
)
```

### 5. Error Handling

Always implement proper error handling:

```python
from workspace_auth_middleware import PermissionDenied

app = Starlette(
    routes=routes,
    middleware=middleware,
    exception_handlers={
        PermissionDenied: permission_denied_handler,
    }
)
```

### 6. Testing

Use environment variables for configuration:

```python
import os

middleware = [
    Middleware(
        WorkspaceAuthMiddleware,
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        required_domains=os.getenv("ALLOWED_DOMAINS", "example.com").split(","),
    )
]
```

## Troubleshooting

### Problem: 401 Unauthorized on all requests

**Cause**: Missing or invalid Authorization header.

**Solution**: Ensure clients send `Authorization: Bearer <google_id_token>` header:

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/protected
```

### Problem: "Token verification failed"

**Cause**: Invalid or expired Google ID token.

**Solution**:
1. Verify token is valid: Use [Google's token info endpoint](https://www.googleapis.com/oauth2/v3/tokeninfo?id_token=TOKEN)
2. Ensure `client_id` matches the one in the token's `aud` claim
3. Check token hasn't expired (`exp` claim)

### Problem: Groups are empty

**Cause**: Group fetching not configured or credentials missing.

**Solution**:
1. Set `GOOGLE_APPLICATION_CREDENTIALS` environment variable
2. Ensure service account has domain-wide delegation
3. Verify `delegated_admin` email is correct
4. Check Admin SDK API is enabled in Google Cloud Console

### Problem: "User domain not in allowed domains"

**Cause**: User's email domain doesn't match `required_domains`.

**Solution**:
1. Verify user's email domain
2. Update `required_domains` to include the domain
3. Or set `required_domains=None` to allow all domains (not recommended for production)

### Problem: Middleware not executing

**Cause**: Middleware not properly registered or incorrect order.

**Solution**:
1. Check middleware is in the `middleware` list
2. Verify middleware order (session before authentication)
3. Use `Middleware()` wrapper when declaring middleware

### Problem: request.user is always anonymous

**Cause**: AuthenticationMiddleware not installed or authentication failed silently.

**Solution**:
1. Verify middleware is registered
2. Check for authentication errors in logs
3. Ensure valid token is being sent

## Related Documentation

- [Architecture and Code Structure](./ARCHITECTURE.md)
- [FastAPI Integration Guide](./FASTAPI_INTEGRATION.md)
- [Session Authentication Guide](./SESSION_AUTHENTICATION.md)
- [Testing Guide](./TESTING_GUIDE.md)

## External References

- [Starlette Documentation](https://www.starlette.io/)
- [Starlette Authentication](https://www.starlette.io/authentication/)
- [Starlette Middleware](https://www.starlette.dev/middleware/)
- [Google ID Token Verification](https://developers.google.com/identity/sign-in/web/backend-auth)
- [Authlib Starlette Integration](https://docs.authlib.org/en/latest/client/starlette.html)
