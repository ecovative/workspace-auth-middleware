# Architecture and Code Structure

This document describes the internal architecture and code structure of `workspace-auth-middleware`.

## Table of Contents

- [Overview](#overview)
- [Architecture Diagram](#architecture-diagram)
- [Core Components](#core-components)
- [Authentication Flow](#authentication-flow)
- [Design Principles](#design-principles)
- [Module Reference](#module-reference)
- [Extension Points](#extension-points)

## Overview

`workspace-auth-middleware` is built on top of [Starlette's authentication system](https://www.starlette.io/authentication/) and provides Google Workspace-specific authentication and authorization for ASGI applications. The package follows Starlette's authentication patterns while adding Google Workspace group-based RBAC capabilities.

### Key Features

- **Starlette-Based**: Extends Starlette's `AuthenticationMiddleware` and `AuthenticationBackend`
- **Stateless Design**: Backend is immutable after initialization
- **High Performance**: Built-in TTL-based caching for token verification and group fetching
- **Type-Safe**: Full type annotations using Starlette's interfaces
- **Framework Agnostic**: Works with any ASGI framework (FastAPI, Starlette, Quart, etc.)

## Architecture Diagram

### Bearer Token Flow (API Authentication)

```
┌─────────────────────────────────────────────────────────────────┐
│                         ASGI Application                        │
│                      (FastAPI/Starlette)                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  WorkspaceAuthMiddleware                        │
│              (extends AuthenticationMiddleware)                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   WorkspaceAuthBackend                          │
│             (implements AuthenticationBackend)                  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  authenticate(conn) -> (AuthCredentials, WorkspaceUser) │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │  Token Cache     │  │  Group Cache     │                     │
│  │  (TTL-based)     │  │  (TTL-based)     │                     │
│  └──────────────────┘  └──────────────────┘                     │
│           │                      │                              │
│           ▼                      ▼                              │
│  ┌──────────────────┐  ┌──────────────────────────────────┐     │
│  │ Google ID Token  │  │ Cloud Identity Groups API        │     │
│  │  Verification    │  │  (Enterprise / Cloud ID Premium) │     │
│  └──────────────────┘  │         — OR —                   │     │
│                         │ Admin SDK Directory API          │     │
│                         │  (Business Standard via          │     │
│                         │   delegated_admin)               │     │
│                         └──────────────────────────────────┘     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Request Enrichment                           │
│                                                                 │
│  request.user  -> WorkspaceUser (email, groups, domain, ...)    │
│  request.auth  -> AuthCredentials (scopes: ["authenticated",    │
│                   "group:admins@example.com", ...])             │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Route Handlers                              │
│                  (with optional decorators)                     │
│                                                                 │
│  @require_auth                                                  │
│  @require_group("admins@example.com")                           │
│  @require_scope("authenticated")                                │
│  @requires("group:admins@example.com")  # Starlette's           │
└─────────────────────────────────────────────────────────────────┘
```

### Session-Based Flow (Web Application with Authlib)

```
┌─────────────────────────────────────────────────────────────────┐
│                         ASGI Application                        │
│                      (FastAPI/Starlette)                        │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Authlib OAuth2 Client                       │   │
│  │         (NOT part of this middleware)                    │   │
│  │                                                          │   │
│  │  /login  → Generate OAuth2 URL with PKCE                 │   │
│  │  /callback → Exchange code for tokens                    │   │
│  │           → Validate ID token                            │   │
│  │           → Store user in session                        │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────┬───────────────────────────────────────────────────────┬───┘
      │                                                       │
      │ Initial Login                              Subsequent │
      │                                             Requests  │
      ▼                                                       ▼
┌───────────────────┐                          ┌────────────────────┐
│  Google OAuth2    │                          │ SessionMiddleware  │
│  Authorization    │                          │  (Starlette)       │
│  Server           │                          └────────┬───────────┘
└─────┬─────────────┘                                   │
      │                                                 ▼
      │ code                              ┌──────────────────────────┐
      ▼                                   │ WorkspaceAuthMiddleware  │
┌───────────────────┐                     └────────┬─────────────────┘
│  Authlib Token    │                              │
│  Exchange & Store │                              ▼
│  in Session       │                  ┌─────────────────────────────┐
└───────────────────┘                  │  WorkspaceAuthBackend       │
                                       │                             │
                                       │  1. Check session["user"]   │
                                       │  2. Validate domain         │
                                       │  3. Fetch groups (cached)   │
                                       │  4. Create WorkspaceUser    │
                                       └────────┬────────────────────┘
                                                │
                                                ▼
                                ┌──────────────────────────────────┐
                                │     Request Enrichment           │
                                │                                  │
                                │  request.user = WorkspaceUser    │
                                │  request.auth = AuthCredentials  │
                                └────────┬─────────────────────────┘
                                         │
                                         ▼
                                ┌──────────────────────────────────┐
                                │       Route Handlers             │
                                │    (with decorators)             │
                                └──────────────────────────────────┘
```

**Key Differences:**
- **Bearer Token**: Client manages tokens, sends with each request
- **Session**: Authlib handles login once, session cookie authenticates subsequent requests
- **workspace-auth-middleware**: Works with BOTH patterns seamlessly

## Core Components

### 1. WorkspaceAuthMiddleware

**Location**: [`workspace_auth_middleware/middleware.py`](../workspace_auth_middleware/middleware.py)

**Purpose**: Convenience wrapper around Starlette's `AuthenticationMiddleware` that automatically configures the `WorkspaceAuthBackend`.

**Responsibilities**:
- Initialize `WorkspaceAuthBackend` with Google Workspace configuration
- Configure error handling for authentication failures
- Integrate with Starlette's middleware system

**Key Methods**:
- `__init__()`: Configure backend and pass to parent `AuthenticationMiddleware`

**Usage Pattern**:
```python
app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="...",
    required_domains=["example.com"],
)
```

### 2. WorkspaceAuthBackend

**Location**: [`workspace_auth_middleware/auth.py`](../workspace_auth_middleware/auth.py)

**Purpose**: Implements Starlette's `AuthenticationBackend` interface to authenticate users via Google OAuth2 ID tokens and fetch their Google Workspace groups.

**Responsibilities**:
- Extract and validate Google ID tokens from `Authorization` header
- Verify tokens against Google's public keys
- Fetch user's Google Workspace group memberships via Cloud Identity Groups API or Admin SDK Directory API
- Cache token verification and group fetching results
- Return `(AuthCredentials, WorkspaceUser)` or `None`

**Key Methods**:
- `authenticate(conn)`: Main authentication entry point (called by Starlette)
- `_verify_token(token)`: Verify Google ID token (with caching)
- `_fetch_user_groups(email)`: Fetch user's groups (dispatches to Cloud Identity or Admin SDK based on `delegated_admin`)
- `_fetch_groups_sync(creds, email)`: Cloud Identity `searchTransitiveGroups` (Enterprise / Cloud Identity Premium)
- `_fetch_groups_admin_sdk_sync(creds, email)`: Admin SDK Directory API (Business Standard, requires `delegated_admin`)
- `_resolve_targeted_groups(service, direct_groups, target_groups)`: BFS transitive resolution for `target_groups`
- `get_cache_stats()`: Return cache hit rates and statistics
- `clear_caches()`: Clear all caches
- `invalidate_token(token)`: Remove specific token from cache
- `invalidate_user_groups(email)`: Remove specific user's groups from cache

**Authentication Flow**:
1. Check for `Authorization: Bearer <token>` header
2. Extract token from header
3. Verify token (check cache first, then call Google API)
4. Extract user info from token claims
5. Validate domain restrictions (if configured)
6. Fetch user's groups (check cache first, then call Cloud Identity API or Admin SDK)
7. Create `WorkspaceUser` object
8. Populate scopes: `["authenticated", "group:<group1>", "group:<group2>", ...]`
9. Return `(AuthCredentials, WorkspaceUser)`

**Caching**:
- **Token Cache**: Caches verified token claims (TTL: 5 minutes by default)
- **Group Cache**: Caches user group memberships (TTL: 5 minutes by default)
- Both caches use `cachetools.TTLCache` for automatic expiration

### 3. WorkspaceUser

**Location**: [`workspace_auth_middleware/models.py`](../workspace_auth_middleware/models.py)

**Purpose**: Represents an authenticated Google Workspace user. Extends Starlette's `BaseUser` interface.

**Responsibilities**:
- Store user attributes (email, user_id, name, domain, groups)
- Provide Starlette-compatible interface (`is_authenticated`, `display_name`, `identity`)
- Helper methods for group membership checks

**Key Properties**:
- `email`: User's email address
- `user_id`: Google user ID (from `sub` claim)
- `name`: User's display name
- `domain`: Google Workspace domain
- `groups`: List of group email addresses user belongs to
- `is_authenticated`: Always `True` (Starlette interface)
- `display_name`: User's name (Starlette interface)
- `identity`: User's unique ID (Starlette interface)

**Key Methods**:
- `has_group(group)`: Check if user belongs to specific group
- `has_any_group(groups)`: Check if user belongs to any of the groups
- `has_all_groups(groups)`: Check if user belongs to all groups

### 4. Decorators

**Location**: [`workspace_auth_middleware/decorators.py`](../workspace_auth_middleware/decorators.py)

**Purpose**: Provide route protection decorators for authentication and authorization.

**Available Decorators**:

#### `@require_auth`
Requires user to be authenticated. Raises `PermissionDenied` if user is anonymous.

```python
@require_auth
async def protected_route(request):
    return {"user": request.user.email}
```

#### `@require_group(group, require_all=False)`
Requires user to belong to specific Google Workspace group(s).

```python
# Single group
@require_group("admins@example.com")
async def admin_route(request):
    return {"message": "Admin access"}

# Multiple groups (OR logic)
@require_group(["team-a@example.com", "team-b@example.com"])
async def team_route(request):
    return {"message": "Team access"}

# Multiple groups (AND logic)
@require_group(
    ["managers@example.com", "leads@example.com"],
    require_all=True
)
async def restricted_route(request):
    return {"message": "Restricted access"}
```

#### `@require_scope(scope)`
Requires specific authentication scope(s).

```python
@require_scope("authenticated")
async def data_route(request):
    return {"data": "sensitive"}
```

**Decorator Implementation**:
- Extracts `request` object from function arguments
- Checks `request.user` or `request.auth` for required attributes
- Raises `PermissionDenied` if requirements not met
- Supports both sync and async route handlers

### 5. AnonymousUser

**Location**: [`workspace_auth_middleware/models.py`](../workspace_auth_middleware/models.py)

**Purpose**: Represents an unauthenticated user. Re-exported from Starlette's `UnauthenticatedUser`.

**Key Properties**:
- `is_authenticated`: Always `False`
- `display_name`: Empty string

### 6. Testing Utilities

**Location**: [`workspace_auth_middleware/testing.py`](../workspace_auth_middleware/testing.py)

**Purpose**: Provide drop-in mock replacements for the middleware and backend so applications can be tested without Google credentials or API calls.

**Classes**:
- `MockWorkspaceAuthBackend` - Implements `AuthenticationBackend` with configurable behavior (fixed user, error mode, custom callback, header mode)
- `MockWorkspaceAuthMiddleware` - Extends `AuthenticationMiddleware`, wraps `MockWorkspaceAuthBackend`

**Functions**:
- `create_workspace_user()` - Factory function to create `WorkspaceUser` instances with sensible defaults

**Design**:
- No Google API imports or credentials required
- Auto-calculates scopes from user groups (matches real backend behavior)
- Header mode enables browser/Playwright testing by reading user data from an HTTP header

### 7. Pytest Plugin

**Location**: [`workspace_auth_middleware/pytest_plugin.py`](../workspace_auth_middleware/pytest_plugin.py)

**Purpose**: Provide auto-discovered pytest fixtures via the `pytest11` entry point.

**Fixtures**:
- `workspace_user` - Factory for creating `WorkspaceUser` instances
- `mock_workspace_backend` - Factory for creating `MockWorkspaceAuthBackend` instances
- `override_workspace_auth` - Monkeypatches `WorkspaceAuthMiddleware.__init__` to use a mock backend

### 8. Integration with Authlib (Optional)

**What is Authlib?**
[Authlib](https://docs.authlib.org/) is a comprehensive OAuth/OIDC library that handles the OAuth2 authorization code flow for web applications. It is **NOT** part of `workspace-auth-middleware` but works seamlessly alongside it.

**Why Use Authlib + workspace-auth-middleware?**

This combination provides a complete authentication solution:

| Component | Responsibility |
|-----------|---------------|
| **Authlib** | OAuth2 protocol implementation (login redirect, PKCE, token exchange, security) |
| **Starlette SessionMiddleware** | Session cookie management (sign, encrypt, verify) |
| **workspace-auth-middleware** | Google Workspace features (domain validation, group fetching, authorization) |

**How They Work Together:**

```python
# 1. Add SessionMiddleware (Starlette)
app.add_middleware(SessionMiddleware, secret_key="...")

# 2. Add WorkspaceAuthMiddleware (this package)
app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="...",
    enable_session_auth=True,  # Enable session support
)

# 3. Initialize Authlib OAuth client (separate library)
from authlib.integrations.starlette_client import OAuth
oauth = OAuth()
oauth.register(name='google', ...)

# 4. Implement login flow with Authlib
@app.get("/login")
async def login(request):
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/callback")
async def auth_callback(request):
    # Authlib handles token exchange and validation
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get('userinfo')

    # Store in session for WorkspaceAuthMiddleware to read
    request.session['user'] = {
        'email': user_info['email'],
        'user_id': user_info['sub'],
        'name': user_info.get('name'),
        'domain': user_info['email'].split('@')[-1],
    }
    return RedirectResponse(url='/')

# 5. Protected routes use workspace-auth-middleware decorators
@app.get("/admin")
@require_group("admins@example.com")
async def admin_panel(request):
    # WorkspaceAuthMiddleware read session, fetched groups, validated domain
    return {"admin": request.user.email}
```

**Authentication Flow with Authlib:**

1. **User clicks "Login"**
   - Authlib generates OAuth2 URL with PKCE, state, nonce
   - Browser redirects to Google

2. **User authenticates with Google**
   - Google validates credentials
   - Google redirects back with authorization code

3. **Authlib handles callback**
   - Validates state/nonce (CSRF protection)
   - Exchanges code for tokens
   - Validates ID token signature
   - Extracts user info

4. **Application stores in session**
   ```python
   request.session['user'] = {
       'email': 'user@example.com',
       'user_id': 'google-user-id',
       'name': 'User Name',
       'domain': 'example.com',
   }
   ```

5. **Subsequent requests**
   - SessionMiddleware extracts session from cookie
   - WorkspaceAuthBackend reads `session['user']`
   - Validates domain (if `required_domains` is set)
   - Fetches groups from Cloud Identity API (if `fetch_groups=True`)
   - Creates `WorkspaceUser` with groups
   - Populates `request.user` and `request.auth`

**When to Use Authlib:**
- ✅ Web applications with browser-based login pages
- ✅ Applications needing token refresh
- ✅ Applications with logout functionality
- ✅ Production apps requiring security best practices (PKCE, state validation)

**When NOT to Use Authlib:**
- ❌ Pure API services (use bearer tokens instead)
- ❌ Mobile/desktop apps calling your API (clients handle OAuth2)
- ❌ Simple testing scenarios (use `gcloud auth print-identity-token`)

**See Also:**
- [Session Authentication Guide](./SESSION_AUTHENTICATION.md) - Complete Authlib integration guide
- [examples/authlib_fastapi_example.py](../examples/authlib_fastapi_example.py) - Full working example
- [examples/authlib_starlette_example.py](../examples/authlib_starlette_example.py) - Starlette example

## Authentication Flow

### Bearer Token Flow (API Requests)

```
1. Client Request
   ├─ Authorization: Bearer <google_id_token>
   └─ GET /api/protected

2. WorkspaceAuthMiddleware
   └─ Calls WorkspaceAuthBackend.authenticate(conn)

3. WorkspaceAuthBackend.authenticate()
   ├─ Extract token from Authorization header
   ├─ Verify token with Google (cached)
   │  ├─ Check token cache
   │  ├─ If miss: Call google.oauth2.id_token.verify_oauth2_token()
   │  └─ Cache result for 5 minutes
   ├─ Extract user info (email, user_id, name)
   ├─ Validate domain restrictions
   ├─ Fetch user's groups (cached)
   │  ├─ Check group cache
   │  ├─ If miss: Call Cloud Identity Groups API
   │  └─ Cache result for 5 minutes
   ├─ Create WorkspaceUser object
   ├─ Create AuthCredentials with scopes
   └─ Return (AuthCredentials, WorkspaceUser)

4. Request Enrichment
   ├─ request.user = WorkspaceUser(...)
   └─ request.auth = AuthCredentials(scopes=[...])

5. Route Handler
   ├─ Decorators check request.user / request.auth
   └─ Handler logic executes
```

### Session Flow (Web Applications)

```
1. Login Flow (via Authlib OAuth2 Client)
   ├─ User visits /login
   ├─ Authlib OAuth2 client initiates authorization code flow
   │  └─ Generates authorization URL with PKCE, state, nonce
   ├─ Redirect to Google OAuth2 authorization endpoint
   ├─ User authenticates with Google
   ├─ Google redirects back to /auth/callback with authorization code
   ├─ Authlib OAuth2 client exchanges code for tokens
   │  ├─ Validates state, nonce for security
   │  ├─ Exchanges authorization code for access token & ID token
   │  └─ Validates ID token signature and claims
   └─ Application stores user data in session
      └─ request.session["user"] = {email, user_id, name, domain}

2. Subsequent Requests (Session-Based)
   ├─ SessionMiddleware extracts session from cookie
   ├─ WorkspaceAuthBackend.authenticate() called
   │  ├─ Check enable_session_auth flag
   │  ├─ Call _authenticate_from_session(conn, required_domains)
   │  │  ├─ Extract user_data from conn.session["user"]
   │  │  ├─ Validate domain if required_domains is set
   │  │  └─ Create WorkspaceUser from session data
   │  ├─ Optionally fetch fresh groups via Cloud Identity API
   │  │  └─ Calls _fetch_user_groups(email) with caching
   │  └─ Return (AuthCredentials, WorkspaceUser)
   └─ If session auth fails/disabled: Fall back to bearer token auth

3. Request Enrichment
   ├─ request.user = WorkspaceUser(...)
   └─ request.auth = AuthCredentials(scopes=[...])

4. Route Handler
   ├─ Decorators check request.user / request.auth
   └─ Handler logic executes
```

**Role of Authlib:**
- **NOT part of workspace-auth-middleware** - Authlib is a separate library
- **Handles OAuth2 protocol** - Authorization code flow, PKCE, token exchange
- **Security best practices** - State validation, nonce checking, CSRF protection
- **Token management** - Automatic token refresh, expiration handling
- **Populates session** - Stores user info that WorkspaceAuthBackend reads

**Separation of Concerns:**
- **Authlib** → OAuth2 login flow (login redirect, callback handling, token exchange)
- **SessionMiddleware** → Session cookie management (sign, verify, extract)
- **WorkspaceAuthBackend** → Read session, validate domain, fetch Google Workspace groups
- **WorkspaceAuthMiddleware** → Route protection, authorization (group checks)

## Design Principles

### 1. Extends Starlette

The package is built on top of Starlette's authentication system rather than reimplementing authentication from scratch. This ensures:
- Maximum compatibility with ASGI frameworks
- Follows established patterns and best practices
- Works seamlessly with Starlette's other features

### 2. Stateless Backend

The `WorkspaceAuthBackend` is stateless after initialization:
- All configuration happens in `__init__()`
- No state is modified during `authenticate()` calls
- Thread-safe and can be shared across workers
- Exception: Caches are mutable but thread-safe via `cachetools.TTLCache`

### 3. ASGI Spec Compliance

The middleware follows the ASGI specification:
- Works with any ASGI 3.0 compatible framework
- Properly handles async/await patterns
- Correctly passes ASGI messages (scope, receive, send)

### 4. Type-Safe

Full type annotations using Starlette's interfaces:
- All public APIs have type hints
- Uses Starlette's base types (`BaseUser`, `AuthenticationBackend`, etc.)
- MyPy type checking enforced via pre-commit hooks

### 5. Async First

All operations are async-aware:
- Backend's `authenticate()` is async
- Synchronous operations (Cloud Identity API) run in executors
- Non-blocking I/O throughout

### 6. High Performance

Built-in caching dramatically improves performance:
- Token verification cached (50-200ms → <1ms)
- Group fetching cached (100-500ms → <1ms)
- TTL-based expiration prevents stale data
- Configurable cache sizes and TTLs

## Module Reference

### [`workspace_auth_middleware/__init__.py`](../workspace_auth_middleware/__init__.py)

Package initialization and public API exports.

**Exports**:
- `WorkspaceAuthMiddleware` - Convenience middleware wrapper
- `WorkspaceAuthBackend` - Authentication backend
- `WorkspaceUser` - Authenticated user model
- `AnonymousUser` - Unauthenticated user model
- `require_auth` - Authentication decorator
- `require_group` - Group-based authorization decorator
- `require_scope` - Scope-based authorization decorator
- `PermissionDenied` - Authorization exception
- `AuthenticationError` - Re-exported from Starlette
- `AuthCredentials` - Re-exported from Starlette
- `requires` - Re-exported from Starlette

### [`workspace_auth_middleware/middleware.py`](../workspace_auth_middleware/middleware.py)

Middleware implementation.

**Classes**:
- `WorkspaceAuthMiddleware` - Extends `AuthenticationMiddleware`

**Functions**:
- `default_on_error()` - Default authentication error handler
- `custom_error_handler_example()` - Example custom error handler

### [`workspace_auth_middleware/auth.py`](../workspace_auth_middleware/auth.py)

Authentication backend implementation.

**Classes**:
- `WorkspaceAuthBackend` - Implements `AuthenticationBackend`

**Functions**:
- `_authenticate_from_session()` - Helper for session-based authentication

### [`workspace_auth_middleware/models.py`](../workspace_auth_middleware/models.py)

User models.

**Classes**:
- `WorkspaceUser` - Extends `BaseUser`
- `AnonymousUser` - Alias for `UnauthenticatedUser`

### [`workspace_auth_middleware/decorators.py`](../workspace_auth_middleware/decorators.py)

Route protection decorators.

**Classes**:
- `PermissionDenied` - Exception raised when authorization fails

**Functions**:
- `require_auth()` - Decorator requiring authentication
- `require_group()` - Decorator requiring group membership
- `require_scope()` - Decorator requiring specific scopes
- `_get_request_from_args()` - Helper to extract request from args

### [`workspace_auth_middleware/testing.py`](../workspace_auth_middleware/testing.py)

Test utilities for applications that use the middleware.

**Classes**:
- `MockWorkspaceAuthBackend` - Mock backend with configurable modes (user, error, callback, header)
- `MockWorkspaceAuthMiddleware` - Mock middleware wrapping `MockWorkspaceAuthBackend`

**Functions**:
- `create_workspace_user()` - Factory with defaults for building `WorkspaceUser` instances

### [`workspace_auth_middleware/pytest_plugin.py`](../workspace_auth_middleware/pytest_plugin.py)

Pytest plugin registered via `pytest11` entry point.

**Fixtures**:
- `workspace_user` - Factory fixture returning `create_workspace_user`
- `mock_workspace_backend` - Factory fixture for `MockWorkspaceAuthBackend`
- `override_workspace_auth` - Monkeypatch fixture for `WorkspaceAuthMiddleware`

## Extension Points

### Custom Error Handling

You can provide a custom error handler to control authentication failure responses:

```python
from starlette.responses import PlainTextResponse

def custom_error_handler(conn, exc):
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

### Custom Credentials

You can provide custom credentials instead of using Application Default Credentials:

```python
from google.oauth2 import service_account

credentials = service_account.Credentials.from_service_account_file(
    'service-account-key.json',
    scopes=['https://www.googleapis.com/auth/cloud-identity.groups.readonly']
)

backend = WorkspaceAuthBackend(
    client_id="...",
    credentials=credentials,
)
```

### Cache Configuration

You can customize caching behavior:

```python
backend = WorkspaceAuthBackend(
    client_id="...",
    # Token cache
    enable_token_cache=True,
    token_cache_ttl=60,        # 1 minute
    token_cache_maxsize=5000,  # 5000 tokens
    # Group cache
    enable_group_cache=True,
    group_cache_ttl=120,       # 2 minutes
    group_cache_maxsize=2000,  # 2000 users
)
```

### Direct Backend Usage

You can use `WorkspaceAuthBackend` directly with Starlette's `AuthenticationMiddleware`:

```python
from starlette.middleware.authentication import AuthenticationMiddleware
from workspace_auth_middleware import WorkspaceAuthBackend

backend = WorkspaceAuthBackend(
    client_id="...",
    required_domains=["example.com"],
)

app.add_middleware(AuthenticationMiddleware, backend=backend)
```

This gives you full control over the middleware configuration while using the Google Workspace backend.

## Performance Considerations

### Caching Impact

**Without caching:**
- Token verification: ~50-200ms per request
- Group fetching: ~100-500ms per request
- **Total: 100-700ms per authenticated request**

**With caching (default):**
- Token verification: <1ms for cache hits
- Group fetching: <1ms for cache hits
- **Total: <5ms for repeated requests**

### Trade-offs

**Advantages**:
- 10-100x performance improvement for repeated requests
- Reduced API costs (fewer calls to Google)
- Better user experience

**Disadvantages**:
- Slightly stale data (up to TTL)
- Memory usage (configurable)
- Token revocation delay (up to TTL)

### Best Practices

1. **Security-sensitive applications**: Use shorter TTLs (60-120s)
2. **Performance-focused applications**: Use longer TTLs (300-900s)
3. **High-traffic applications**: Increase cache sizes
4. **Monitor cache hit rates**: Use `backend.get_cache_stats()`
5. **Implement webhook-based invalidation**: For immediate group updates

## Related Documentation

- [Starlette Integration Guide](./STARLETTE_INTEGRATION.md) - Detailed Starlette integration
- [FastAPI Integration Guide](./FASTAPI_INTEGRATION.md) - Detailed FastAPI integration
- [Session Authentication](./SESSION_AUTHENTICATION.md) - Session-based authentication guide
- [Testing Guide](./TESTING_GUIDE.md) - Testing with real Google credentials

## External References

- [Starlette Authentication](https://www.starlette.io/authentication/)
- [Starlette Middleware](https://www.starlette.dev/middleware/)
- [FastAPI Middleware](https://fastapi.tiangolo.com/advanced/middleware/)
- [Google ID Token Verification](https://developers.google.com/identity/sign-in/web/backend-auth)
- [Cloud Identity Groups API](https://cloud.google.com/identity/docs/reference/rest)
