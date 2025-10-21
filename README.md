# workspace-auth-middleware

ASGI middleware for authentication against Google Workspace with role-based access control (RBAC) using Google Workspace groups.

Built on top of [Starlette's authentication system](https://www.starlette.io/authentication/) with Google Workspace-specific features.

## Features

- **Starlette-Based**: Extends Starlette's AuthenticationMiddleware for maximum compatibility
- **Google Workspace Authentication**: Validates Google OAuth2 ID tokens
- **Group-Based RBAC**: Authorization based on Google Workspace group memberships
- **High Performance**: Optional caching reduces response time from 100-700ms to <5ms
- **Flexible Decorators**: Use custom `@require_group()` or Starlette's `@requires()` decorator
- **Type Hints**: Full type annotations for better IDE support
- **Async First**: Built for async Python applications
- **Framework Agnostic**: Works with FastAPI, Starlette, and any ASGI framework

## Installation

```bash
pip install workspace-auth-middleware
```

Or with Poetry:

```bash
poetry add workspace-auth-middleware
```

This includes everything you need:
- Google Workspace authentication (OAuth2 ID tokens)
- Group-based authorization (Admin SDK)
- High-performance caching (cachetools)

## Quick Start

### FastAPI Example

```python
from fastapi import FastAPI, Request
from workspace_auth_middleware import (
    WorkspaceAuthMiddleware,
    require_auth,
    require_group,
)

app = FastAPI()

# Add the middleware
app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    fetch_groups=True,
)

# Public endpoint - no authentication required
@app.get("/")
async def public_route():
    return {"message": "Hello, World!"}

# Protected endpoint - authentication required
@app.get("/profile")
@require_auth
async def profile_route(request: Request):
    user = request.user
    return {
        "email": user.email,
        "name": user.name,
        "groups": user.groups,
    }

# Admin-only endpoint - requires specific group
@app.get("/admin")
@require_group("admins@example.com")
async def admin_route(request: Request):
    return {"message": "Admin access granted"}

# Multi-group endpoint - user must be in at least one group
@app.get("/teams")
@require_group(["team-a@example.com", "team-b@example.com"])
async def team_route(request: Request):
    return {"message": "Team access granted"}

# Restricted endpoint - user must be in ALL specified groups
@app.get("/restricted")
@require_group(
    ["managers@example.com", "leads@example.com"],
    require_all=True
)
async def restricted_route(request: Request):
    return {"message": "Restricted access granted"}
```

### Starlette Example

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

# Define routes with decorators
@require_auth
async def protected_endpoint(request: Request):
    return JSONResponse({
        "user": request.user.email,
        "groups": request.user.groups,
    })

@require_group("admins@example.com")
async def admin_endpoint(request: Request):
    return JSONResponse({"message": "Admin access"})

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
    Route("/protected", protected_endpoint),
    Route("/admin", admin_endpoint),
]

app = Starlette(routes=routes, middleware=middleware)
```

## Authentication Flow

1. Client sends request with `Authorization: Bearer <google_id_token>` header
2. Middleware extracts and validates the Google ID token
3. User information is extracted from the token
4. User's Google Workspace groups are fetched (optional)
5. `request.user` and `request.auth` are populated
6. Request continues to route handler

### Getting Google ID Tokens

Clients must obtain a Google ID token and include it in the Authorization header:

```javascript
// Example: Frontend JavaScript using Google Sign-In
function onSignIn(googleUser) {
  const id_token = googleUser.getAuthResponse().id_token;

  // Make API request with token
  fetch('/api/protected', {
    headers: {
      'Authorization': `Bearer ${id_token}`
    }
  });
}
```

## Configuration

### Middleware Options

```python
WorkspaceAuthMiddleware(
    app,                                    # ASGI application
    client_id: str,                         # Google OAuth2 client ID (required)
    required_domains: List[str] = None,     # List of allowed domains (e.g., ["example.com", "partner.com"])
                                            # If None, users from any domain are allowed
    fetch_groups: bool = True,              # Fetch user's group memberships
    on_error: Callable = None,              # Custom error handler
)
```

### Custom Error Handler

```python
async def custom_error_handler(scope, receive, send, exc):
    """Custom authentication error handler."""
    import json

    error_body = json.dumps({
        "error": "Unauthorized",
        "message": str(exc),
    }).encode()

    await send({
        "type": "http.response.start",
        "status": 403,
        "headers": [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(error_body)).encode()],
        ],
    })
    await send({
        "type": "http.response.body",
        "body": error_body,
    })

app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="...",
    on_error=custom_error_handler,
)
```

## Using Starlette's AuthenticationMiddleware Directly

For maximum flexibility, you can use Starlette's `AuthenticationMiddleware` directly with the `WorkspaceAuthBackend`:

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

This gives you access to all of Starlette's authentication features while using Google Workspace for authentication.

## Decorators

This package provides two approaches for protecting routes:

### 1. Custom Decorators (Google Workspace-Specific)

#### `@require_auth`

Requires user to be authenticated. Anonymous users are denied access.

```python
@app.get("/protected")
@require_auth
async def protected_route(request: Request):
    return {"user": request.user.email}
```

#### `@require_group(group, require_all=False)`

Requires user to belong to specific Google Workspace group(s).

```python
# Single group
@app.get("/admin")
@require_group("admins@example.com")
async def admin_route(request: Request):
    return {"message": "Admin access"}

# Multiple groups (user needs at least one)
@app.get("/teams")
@require_group(["team-a@example.com", "team-b@example.com"])
async def team_route(request: Request):
    return {"message": "Team access"}

# Multiple groups (user needs all)
@app.get("/restricted")
@require_group(
    ["managers@example.com", "department-leads@example.com"],
    require_all=True
)
async def restricted_route(request: Request):
    return {"message": "Restricted access"}
```

#### `@require_scope(scope)`

Requires specific authentication scope(s).

```python
@app.get("/data")
@require_scope("authenticated")
async def data_route(request: Request):
    return {"data": "sensitive"}
```

### 2. Starlette's `@requires` Decorator (Scope-Based)

You can also use Starlette's built-in `@requires` decorator for scope-based authorization. The `WorkspaceAuthBackend` automatically populates these scopes:

- `"authenticated"` - User is authenticated
- `"group:<group_email>"` - User belongs to a specific group

```python
from workspace_auth_middleware import requires  # Re-exported from Starlette

@app.get("/protected")
@requires("authenticated")
async def protected_route(request: Request):
    return {"user": request.user.email}

@app.get("/admin")
@requires("group:admins@example.com")
async def admin_route(request: Request):
    return {"message": "Admin access"}

# Multiple scopes (user needs ALL of them)
@app.get("/special")
@requires(["authenticated", "group:team-leads@example.com"])
async def special_route(request: Request):
    return {"message": "Team lead access"}
```

**When to use which:**
- Use `@require_group()` for: More readable group-based logic, OR/AND logic between groups
- Use `@requires()` for: Standard Starlette patterns, scope-based logic

## User Object

The `request.user` object provides access to user information:

```python
@app.get("/me")
@require_auth
async def get_current_user(request: Request):
    user = request.user

    return {
        "email": user.email,           # User's email address
        "user_id": user.user_id,       # Google user ID
        "name": user.name,             # Display name
        "domain": user.domain,         # Workspace domain
        "groups": user.groups,         # List of group emails
        "is_authenticated": user.is_authenticated,  # Always True for authenticated users
    }

# Check group membership
@app.get("/check-access")
@require_auth
async def check_access(request: Request):
    user = request.user

    return {
        "is_admin": user.has_group("admins@example.com"),
        "is_in_team": user.has_any_group(["team-a@example.com", "team-b@example.com"]),
        "is_manager": user.has_all_groups(["managers@example.com", "leads@example.com"]),
    }
```

## Google Workspace Groups Setup

To enable group fetching, you need to:

1. **Create a Service Account** in Google Cloud Console

2. **Enable Domain-Wide Delegation** for the service account

3. **Grant API Scopes**:
   - `https://www.googleapis.com/auth/admin.directory.group.readonly`

4. **Configure credentials** in your application

### Using Default Application Credentials

The easiest approach is to use Application Default Credentials (ADC):

```bash
# Set the environment variable to your service account key
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

Then configure the middleware:

```python
from workspace_auth_middleware import WorkspaceAuthMiddleware

app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    fetch_groups=True,
    delegated_admin="admin@example.com",  # Admin for domain-wide delegation
)
```

The middleware will automatically use the default credentials.

### Using Explicit Credentials

You can also pass credentials explicitly:

```python
from google.oauth2 import service_account
from workspace_auth_middleware import WorkspaceAuthMiddleware

# Load service account credentials
credentials = service_account.Credentials.from_service_account_file(
    'service-account-key.json',
    scopes=['https://www.googleapis.com/auth/admin.directory.group.readonly']
)

app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    fetch_groups=True,
    credentials=credentials,
    delegated_admin="admin@example.com",
)
```

### Using with Starlette's AuthenticationMiddleware

```python
from starlette.middleware.authentication import AuthenticationMiddleware
from google.oauth2 import service_account
from workspace_auth_middleware import WorkspaceAuthBackend

credentials = service_account.Credentials.from_service_account_file(
    'service-account-key.json',
    scopes=['https://www.googleapis.com/auth/admin.directory.group.readonly']
)

backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    fetch_groups=True,
    credentials=credentials,
    delegated_admin="admin@example.com",
)

app.add_middleware(AuthenticationMiddleware, backend=backend)
```

## Performance Optimization with Caching

The middleware includes built-in caching to significantly improve performance by reducing API calls to Google's services.

### Why Caching Matters

Without caching:
- **Token verification**: Each request hits Google's token verification endpoint (~50-200ms)
- **Group fetching**: Each request queries the Admin SDK (~100-500ms)

With caching:
- **Token verification**: Cached for 5 minutes (default), < 1ms for cache hits
- **Group fetching**: Cached for 5 minutes (default), < 1ms for cache hits

For a user making multiple requests, this can reduce response time from 100-700ms to < 5ms!

### Basic Usage

Caching is **enabled by default**:

```python
backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    # Caching is enabled by default with these settings:
    enable_token_cache=True,      # Cache token verification results
    token_cache_ttl=300,           # 5 minutes
    token_cache_maxsize=1000,      # Max 1000 tokens cached
    enable_group_cache=True,       # Cache group memberships
    group_cache_ttl=300,           # 5 minutes
    group_cache_maxsize=500,       # Max 500 users' groups cached
)
```

### Configuration Options

```python
# Disable caching entirely
backend = WorkspaceAuthBackend(
    client_id="...",
    enable_token_cache=False,
    enable_group_cache=False,
)

# Custom TTL (Time To Live)
backend = WorkspaceAuthBackend(
    client_id="...",
    token_cache_ttl=60,    # 1 minute (more aggressive)
    group_cache_ttl=900,   # 15 minutes (less aggressive)
)

# Larger caches for high-traffic applications
backend = WorkspaceAuthBackend(
    client_id="...",
    token_cache_maxsize=10000,  # 10k tokens
    group_cache_maxsize=5000,   # 5k users
)
```

### Cache Management

Monitor and manage caches programmatically:

```python
# Get cache statistics
stats = backend.get_cache_stats()
print(f"Token cache hit rate: {stats['token_cache']['hit_rate']:.2%}")
print(f"Group cache hit rate: {stats['group_cache']['hit_rate']:.2%}")
print(f"Token cache size: {stats['token_cache']['size']}/{stats['token_cache']['maxsize']}")

# Clear all caches
backend.clear_caches()

# Invalidate specific entries
backend.invalidate_token("specific_token_to_invalidate")
backend.invalidate_user_groups("user@example.com")
```

### Cache Considerations

**Advantages:**
- **Massive performance improvement**: 10-100x faster for repeated requests
- **Reduced API costs**: Fewer calls to Google's APIs
- **Better user experience**: Sub-millisecond authentication checks
- **Automatic TTL management**: Caches expire automatically

**Trade-offs:**
- **Slightly stale data**: Group membership changes take up to TTL to reflect
- **Memory usage**: Caches consume memory (configurable via maxsize)
- **Token revocation delay**: Revoked tokens remain valid until cache expires

**Best Practices:**
- Use shorter TTLs (60-120s) for security-sensitive applications
- Use longer TTLs (300-900s) for better performance in trusted environments
- Monitor cache hit rates and adjust sizes accordingly
- Implement webhook-based cache invalidation for immediate group updates

### Example: Monitoring Cache Performance

```python
from starlette.responses import JSONResponse

@app.get("/cache/stats")
@require_group("admins@example.com")
async def cache_stats(request: Request):
    """Admin endpoint to monitor cache performance."""
    stats = backend.get_cache_stats()
    return JSONResponse(stats)
```

See `examples/caching_example.py` for a complete working example.

### Without Group Fetching

If you don't need group-based authorization, you can disable group fetching:

```python
app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    fetch_groups=False,  # No credentials needed
)
```

## Error Handling

The middleware handles authentication errors automatically:

- **401 Unauthorized**: Invalid or missing authentication token
- **403 Forbidden**: Valid token but insufficient permissions (when using decorators)

Use `PermissionDenied` exception in your code:

```python
from workspace_auth_middleware import PermissionDenied

@app.get("/custom-check")
@require_auth
async def custom_check(request: Request):
    if not some_custom_condition(request.user):
        raise PermissionDenied("Custom permission check failed")

    return {"message": "Access granted"}
```

## Development

### Setup

```bash
# Install dependencies
poetry install

# Install pre-commit hooks
poetry run pre-commit install
```

### Testing

```bash
# Run tests
poetry run pytest -n 4 tests

# Run tests with coverage
poetry run pytest --cov=workspace_auth_middleware tests
```

### Testing with Real Credentials

Want to test with your actual Google Workspace credentials? See the **[Testing Guide](./TESTING_GUIDE.md)** for complete instructions.

Quick start:
```bash
# 1. Run interactive setup
cd examples && ./setup_env.sh

# 2. Load environment variables
source .env

# 3. Start test server
poetry run python examples/manual_testing.py

# 4. Get a token and test
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/me
```

### Code Quality

```bash
# Format code
poetry run ruff format

# Lint code
poetry run ruff check

# Type check
poetry run mypy workspace_auth_middleware

# Run all checks
poetry run pre-commit run --all-files
```

## License

See LICENSE.txt

## Documentation

- **[README.md](./README.md)** - This file, complete package documentation
- **[TESTING_GUIDE.md](./TESTING_GUIDE.md)** - Complete guide for testing with real Google credentials
- **[CLAUDE.md](./CLAUDE.md)** - Architecture and development guide for Claude Code
- **[examples/README.md](./examples/README.md)** - Examples and setup instructions
- **[examples/caching_example.py](./examples/caching_example.py)** - Caching configuration examples
- **[examples/manual_testing.py](./examples/manual_testing.py)** - Interactive test server

## Contributing

Contributions are welcome! Please ensure:

1. All tests pass
2. Code is formatted with Ruff
3. Type hints are included
4. Documentation is updated
