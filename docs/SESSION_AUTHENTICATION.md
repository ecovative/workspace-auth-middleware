# Session-Based Authentication with WorkspaceAuthMiddleware

## Overview

This guide explains how to implement session-based authentication for web applications using **Authlib** for OAuth2 and **WorkspaceAuthMiddleware** for Google Workspace features.

WorkspaceAuthMiddleware supports two authentication methods:

1. **Bearer Token Authentication** - For APIs and mobile apps (stateless)
2. **Session-Based Authentication** - For web applications (stateful)

This document focuses on **session-based authentication**, the recommended approach for web applications with login pages.

## Recommended Stack: Authlib + WorkspaceAuthMiddleware

For production web applications, we **strongly recommend** using [Authlib](https://docs.authlib.org/) for OAuth2/OIDC, combined with WorkspaceAuthMiddleware for Google Workspace features:

```
┌─────────────────────────────────────────────────┐
│  Your FastAPI/Starlette Application             │
├─────────────────────────────────────────────────┤
│  1. SessionMiddleware                            │
│     └─ Manages signed cookie sessions           │
│                                                  │
│  2. AuthenticationMiddleware                     │
│     └─ WorkspaceAuthBackend                     │
│        ├─ Reads session data                    │
│        ├─ Validates domain restrictions         │
│        └─ Fetches Google Workspace groups       │
│                                                  │
│  3. Authlib OAuth Client                        │
│     ├─ Handles OAuth2 authorization flow        │
│     ├─ Token exchange with PKCE                 │
│     └─ Stores user info in session              │
└─────────────────────────────────────────────────┘
```

**Separation of Concerns:**
- **Authlib** - OAuth2/OIDC protocol (login, callback, token exchange)
- **SessionMiddleware** - Session management (signed cookies)
- **WorkspaceAuthMiddleware** - Google Workspace features (groups, domain checks)
- **Your Application** - Business logic, authorization rules

**Why Authlib?**
- ✅ Industry-standard OAuth2/OIDC library
- ✅ PKCE enabled by default for better security
- ✅ Automatic state management (CSRF protection)
- ✅ Built-in token refresh support
- ✅ Comprehensive error handling
- ✅ Battle-tested and actively maintained

## Key Concepts

### 1. Starlette's SessionMiddleware

[Starlette's SessionMiddleware](https://www.starlette.io/middleware/#sessionmiddleware) provides:
- **Signed cookie-based sessions**: Session data stored in browser cookie (signed, not encrypted)
- **Automatic management**: No server-side storage needed
- **Simple API**: Access via `request.session` dictionary

### 2. Integration with AuthenticationMiddleware

Our `WorkspaceAuthBackend` checks TWO sources:
1. **`request.session["user"]`** - User data from OAuth2 flow (via SessionMiddleware)
2. **`Authorization` header** - Bearer token (original ID token auth)

## Complete Example

### Step 1: Add Both Middlewares

```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware
from workspace_auth_middleware import WorkspaceAuthBackend

# Create backend
backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    required_domains=["example.com"],
    enable_session_auth=True,  # Enable session support
)

# Configure middlewares (ORDER MATTERS!)
middleware = [
    # SessionMiddleware MUST come before AuthenticationMiddleware
    Middleware(
        SessionMiddleware,
        secret_key="your-secret-key-here",  # Use secrets.token_urlsafe(32)
        max_age=86400,  # 24 hours
        same_site="lax",
        https_only=True,  # Production only
    ),
    # AuthenticationMiddleware reads from session
    Middleware(
        AuthenticationMiddleware,
        backend=backend,
    ),
]

app = Starlette(routes=routes, middleware=middleware)
```

**Important**: SessionMiddleware MUST be added BEFORE AuthenticationMiddleware so that `request.session` is available when `backend.authenticate()` is called.

### Step 2: OAuth2 Login Flow with Authlib

```python
from authlib.integrations.starlette_client import OAuth
from starlette.responses import RedirectResponse, JSONResponse

# Initialize Authlib OAuth (do this once, at module level)
oauth = OAuth()
oauth.register(
    name='google',
    client_id="your-client-id.apps.googleusercontent.com",
    client_secret="your-client-secret",
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

@app.get("/login")
async def login(request: Request):
    """Redirect user to Google for authorization."""
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle OAuth2 callback and create session."""
    try:
        # Exchange authorization code for tokens
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo')

        if not user_info:
            return JSONResponse(
                {'error': 'Failed to get user info'},
                status_code=500
            )

        # Store user in Starlette session for WorkspaceAuthMiddleware
        request.session['user'] = {
            'email': user_info['email'],
            'user_id': user_info['sub'],
            'name': user_info.get('name', user_info['email']),
            'domain': user_info['email'].split('@')[-1],
            'groups': [],  # WorkspaceAuthMiddleware will fetch groups
        }

        return RedirectResponse(url='/', status_code=302)

    except Exception as error:
        return JSONResponse(
            {'error': str(error)},
            status_code=400
        )
```

**Why Authlib?**
- **PKCE enabled by default** - Better security
- **Automatic state management** - No manual CSRF token handling needed
- **Industry standard** - Battle-tested library
- **Better error handling** - Comprehensive exception types
- **Token refresh** - Built-in support for refresh tokens

### Step 3: Logout

```python
@app.get("/logout")
async def logout(request: Request):
    """Clear session and log out user."""
    request.session.clear()
    return RedirectResponse(url='/', status_code=302)
```

### Step 4: Protected Routes

```python
from workspace_auth_middleware import require_auth

@app.get("/profile")
@require_auth
async def profile(request: Request):
    """
    Protected route - works with BOTH:
    - Session authentication (request.session["user"])
    - Bearer token authentication (Authorization header)
    """
    return {
        "email": request.user.email,
        "name": request.user.name,
        "groups": request.user.groups,
    }
```

## How It Works

### Authentication Flow

```
1. Request arrives
2. SessionMiddleware processes it → populates request.session
3. AuthenticationMiddleware calls backend.authenticate(conn)
4. Backend checks:
   a. If request.session["user"] exists → Create user from session
   b. Else if Authorization header exists → Verify ID token
   c. Else → Anonymous user (request.user = UnauthenticatedUser)
5. Route handler accesses request.user
```

### Session Data Structure

```python
request.session["user"] = {
    "email": "user@example.com",
    "user_id": "123456",
    "name": "John Doe",
    "domain": "example.com",
    "groups": ["team@example.com", "admins@example.com"],
}
```

## Backend Implementation

The `WorkspaceAuthBackend.authenticate()` method:

```python
async def authenticate(self, conn):
    # 1. Check session first (if enabled)
    if self.enable_session_auth and hasattr(conn, "session"):
        session_user = authenticate_from_session(conn, self.required_domains)
        if session_user:
            return session_user

    # 2. Fall back to bearer token
    if "authorization" in conn.headers:
        # ... verify ID token ...
        return credentials, user

    # 3. Anonymous
    return None
```

## Advantages of This Approach

### vs. Custom Session Store

| Custom Session Store | Starlette SessionMiddleware |
|---------------------|----------------------------|
| Requires server-side storage | No storage needed |
| Need to manage session lifecycle | Automatic via cookies |
| Need cleanup tasks | Automatic expiry |
| Complex implementation | Simple `request.session` dict |
| Multi-server needs Redis/DB | Works with signed cookies |

### Security

**SessionMiddleware provides:**
- Cryptographically signed cookies (tamper-proof)
- Configurable expiry (max_age)
- HTTPS-only option (secure flag)
- SameSite CSRF protection

**Note**: Session data is **signed but not encrypted** - it's readable in browser. Don't store sensitive data (tokens, passwords) in the session. Store only user identifiers.

## Best Practices

### 1. Secret Key Management

```python
import secrets

# Generate once, store securely
secret_key = secrets.token_urlsafe(32)

# Use environment variable in production
import os
secret_key = os.getenv("SESSION_SECRET_KEY")
```

### 2. Secure Cookie Settings

```python
Middleware(
    SessionMiddleware,
    secret_key=secret_key,
    max_age=86400,  # 24 hours
    same_site="lax",  # or "strict" for more security
    https_only=True,  # MUST be True in production
    session_cookie="session",  # Custom cookie name
)
```

### 3. Don't Store Tokens in Session

```python
# DON'T do this:
request.session["access_token"] = tokens["access_token"]  # Visible in cookie!

# DO this instead:
# - Let backend fetch fresh data as needed
# - Use refresh tokens server-side only
# - Store minimal user info in session
```

### 4. Session Cleanup

SessionMiddleware handles expiry automatically via max_age. No cleanup needed!

## Group Fetching

WorkspaceAuthMiddleware **automatically fetches groups** when `fetch_groups=True`. You don't need to fetch them manually in the OAuth callback.

### Automatic Group Fetching (Recommended)

```python
# In middleware configuration
backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    fetch_groups=True,  # Enable automatic group fetching
    delegated_admin="admin@example.com",
    enable_group_cache=True,  # Cache for performance
    group_cache_ttl=300,  # 5 minutes
)

# In OAuth callback - just store basic user info
@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get('userinfo')

    request.session['user'] = {
        'email': user_info['email'],
        'user_id': user_info['sub'],
        'name': user_info.get('name'),
        'domain': user_info['email'].split('@')[-1],
        'groups': [],  # Leave empty - middleware will populate automatically
    }

    return RedirectResponse(url='/')

# Groups are automatically available in protected routes
@app.get("/profile")
@require_auth
async def profile(request: Request):
    # request.user.groups is automatically populated by middleware
    return {
        'email': request.user.email,
        'groups': request.user.groups,  # Automatically fetched!
    }
```

The middleware fetches groups on each request and caches them for performance. This ensures groups are always up-to-date without manual management.

## Complete Working Examples

See the [examples](../examples) directory for complete, runnable applications:

- **[authlib_fastapi_example.py](../examples/authlib_fastapi_example.py)** - Full FastAPI + Authlib integration with HTML UI, Swagger docs
- **[authlib_starlette_example.py](../examples/authlib_starlette_example.py)** - Full Starlette + Authlib integration

Run them with:
```bash
poetry run python examples/authlib_fastapi_example.py
# or
poetry run python examples/authlib_starlette_example.py
```

Visit http://localhost:8000/ to see the examples in action.

## Comparison: Bearer vs. Session

### Bearer Token (Original)

```
Client → Get ID token → Send with each request
          ↓
      Authorization: Bearer <id_token>
          ↓
      Backend verifies token with Google (cached)
```

**Best for**: APIs, mobile apps, CLIs

### Session Cookie (New)

```
User → OAuth2 flow → Session created → Cookie set
                          ↓
              Subsequent requests use cookie
                          ↓
              Backend reads from request.session
```

**Best for**: Web applications, browsers

### Both Work Together!

The backend supports both simultaneously:
- Web users: Session cookie
- API clients: Bearer token
- No changes needed to existing bearer token auth

## Migration Path

### From OAuth2Helper to Authlib (Recommended)

If you're using the deprecated `OAuth2Helper` class, migrate to Authlib:

```python
# BEFORE: Using deprecated OAuth2Helper
from workspace_auth_middleware import OAuth2Helper

oauth2 = OAuth2Helper(
    client_id='...',
    client_secret='...',
    redirect_uri='...',
)

@app.get("/login")
async def login():
    auth_url, state = oauth2.generate_authorization_url(state='...')
    return RedirectResponse(url=auth_url)

@app.get("/auth/callback")
async def callback(request: Request, code: str):
    tokens = await oauth2.exchange_code_for_tokens(code)
    user_info = tokens["user_info"]
    # ... store in session

# AFTER: Using Authlib (recommended)
from authlib.integrations.starlette_client import OAuth

oauth = OAuth()
oauth.register(
    name='google',
    client_id='...',
    client_secret='...',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

@app.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get('userinfo')
    # ... store in session
```

**Benefits of migrating to Authlib:**
- PKCE enabled automatically (better security)
- No manual state management needed
- Better error handling with specific exception types
- Token refresh built-in
- Industry-standard library with active maintenance

### From Bearer-Only to Sessions

```python
# Before: Bearer token only
backend = WorkspaceAuthBackend(client_id="...")
app.add_middleware(AuthenticationMiddleware, backend=backend)

# After: Add SessionMiddleware (bearer tokens still work!)
app.add_middleware(SessionMiddleware, secret_key="...")
backend = WorkspaceAuthBackend(
    client_id="...",
    enable_session_auth=True,  # Enable session support
)
app.add_middleware(AuthenticationMiddleware, backend=backend)

# Add OAuth2 endpoints (/login, /callback, /logout)
# Existing bearer token clients continue to work unchanged
```

## Troubleshooting

### Session Not Available

**Problem**: `request.session` doesn't exist

**Solution**: Ensure SessionMiddleware is added BEFORE AuthenticationMiddleware

### Session Data Lost

**Problem**: User logged in but session cleared

**Solutions**:
- Check `max_age` setting (may be too short)
- Verify secret_key hasn't changed (invalidates all sessions)
- Check cookie settings (secure/same_site may block cookies)

### Bearer Tokens Stopped Working

**Problem**: Adding sessions broke bearer token auth

**Solution**: This shouldn't happen - both methods work independently. Check that bearer token validation code wasn't modified.

## References

- [Starlette SessionMiddleware](https://www.starlette.io/middleware/#sessionmiddleware)
- [Starlette Authentication](https://www.starlette.io/authentication/)
- [OAuth2 Authorization Code Flow](https://developers.google.com/identity/protocols/oauth2/web-server)
