"""
Production-Ready OAuth2 Example using Authlib + WorkspaceAuthMiddleware (Starlette).

This demonstrates the RECOMMENDED approach:
- Authlib handles OAuth2/OIDC (login, token exchange, session management)
- WorkspaceAuthMiddleware handles Google Workspace-specific features (groups, authorization)

Setup:
1. Install dependencies:
   poetry add authlib

2. Set environment variables:
   - GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
   - GOOGLE_CLIENT_SECRET="your-client-secret"
   - SESSION_SECRET_KEY="your-secret-key"  # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
   - GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"  # For group fetching
   - GOOGLE_DELEGATED_ADMIN="admin@example.com"  # For group fetching
   - GOOGLE_WORKSPACE_DOMAIN="example.com"  # Optional domain restriction

3. Configure OAuth2 redirect URI in Google Cloud Console:
   http://localhost:8000/auth/callback

4. Run:
   poetry run python examples/authlib_starlette_example.py

5. Visit:
   http://localhost:8000/
"""

import os
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Route
from starlette.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.requests import Request

# Authlib for OAuth2/OIDC
from authlib.integrations.starlette_client import OAuth, OAuthError

# WorkspaceAuthMiddleware for Google Workspace features
from workspace_auth_middleware import (
    WorkspaceAuthBackend,
    require_auth,
    require_group,
)

# Configuration from environment
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "your-client-id.apps.googleusercontent.com")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "your-client-secret")
SESSION_SECRET = os.getenv("SESSION_SECRET_KEY")
WORKSPACE_DOMAIN = os.getenv("GOOGLE_WORKSPACE_DOMAIN")
DELEGATED_ADMIN = os.getenv("GOOGLE_DELEGATED_ADMIN")

if not SESSION_SECRET:
    raise ValueError("SESSION_SECRET_KEY environment variable is required")

# Initialize Authlib OAuth
oauth = OAuth()
oauth.register(
    name="google",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile",
        # Add Admin SDK scope if you want to fetch groups during OAuth
        # 'scope': 'openid email profile https://www.googleapis.com/auth/admin.directory.group.readonly',
    },
)


# Routes
async def home(request: Request):
    """Home page - shows login button or user info."""
    user = request.user

    if user.is_authenticated:
        return HTMLResponse(f"""
        <html>
            <head>
                <title>Authlib + WorkspaceAuth Example</title>
                <style>
                    body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }}
                    .user-info {{ background: #f0f0f0; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                    .badge {{ display: inline-block; padding: 4px 12px; background: #007bff; color: white; border-radius: 12px; font-size: 12px; margin: 2px; }}
                    .links {{ margin: 20px 0; }}
                    .links a {{ display: inline-block; margin-right: 15px; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 4px; }}
                    .links a:hover {{ background: #0056b3; }}
                    .logout {{ background: #dc3545 !important; }}
                    .logout:hover {{ background: #c82333 !important; }}
                    .tech-stack {{ background: #e8f5e9; padding: 15px; border-left: 4px solid #4caf50; margin: 20px 0; }}
                </style>
            </head>
            <body>
                <h1>Welcome, {user.display_name}! 👋</h1>
                <div class="user-info">
                    <p><strong>Email:</strong> {user.email}</p>
                    <p><strong>User ID:</strong> {user.user_id}</p>
                    <p><strong>Domain:</strong> {user.domain or "N/A"}</p>
                    <p><strong>Groups:</strong>
                        {" ".join([f'<span class="badge">{g}</span>' for g in user.groups]) if user.groups else "None"}
                    </p>
                </div>
                <div class="links">
                    <a href="/profile">View Profile (API)</a>
                    <a href="/protected">Protected Route</a>
                    <a href="/logout" class="logout">Logout</a>
                </div>
                <div class="tech-stack">
                    <strong>🔧 Tech Stack:</strong>
                    <ul>
                        <li><strong>Authlib</strong> - OAuth2/OIDC authentication</li>
                        <li><strong>Starlette SessionMiddleware</strong> - Session management</li>
                        <li><strong>WorkspaceAuthMiddleware</strong> - Google Workspace groups & authorization</li>
                    </ul>
                </div>
            </body>
        </html>
        """)
    else:
        return HTMLResponse("""
        <html>
            <head>
                <title>Authlib + WorkspaceAuth Example</title>
                <style>
                    body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; text-align: center; }
                    .login-btn { display: inline-block; padding: 15px 30px; background: #4285f4; color: white; text-decoration: none; border-radius: 4px; font-size: 16px; }
                    .login-btn:hover { background: #357ae8; }
                    .info { background: #f9f9f9; padding: 20px; margin: 30px 0; border-left: 4px solid #4285f4; text-align: left; }
                    .architecture { background: #fff3cd; padding: 20px; margin: 30px 0; border-left: 4px solid #ffc107; text-align: left; }
                </style>
            </head>
            <body>
                <h1>Authlib + WorkspaceAuthMiddleware</h1>
                <p>Production-ready OAuth2 authentication with Google Workspace</p>

                <div class="architecture">
                    <h3>🏗️ Architecture:</h3>
                    <ol>
                        <li><strong>Authlib</strong> - Handles OAuth2/OIDC (industry standard)</li>
                        <li><strong>SessionMiddleware</strong> - Manages signed cookie sessions</li>
                        <li><strong>WorkspaceAuthMiddleware</strong> - Adds Google Workspace groups</li>
                        <li><strong>Your Routes</strong> - Use @require_group decorators</li>
                    </ol>
                </div>

                <div class="info">
                    <h3>How it works:</h3>
                    <ol>
                        <li>Click "Login with Google" below</li>
                        <li>Authlib handles OAuth2 flow (PKCE, state validation)</li>
                        <li>User info stored in session by Authlib</li>
                        <li>WorkspaceAuthMiddleware fetches Google Workspace groups</li>
                        <li>Routes protected with @require_group decorators</li>
                    </ol>
                </div>

                <a href="/login" class="login-btn">🔐 Login with Google</a>
            </body>
        </html>
        """)


async def login(request: Request):
    """Initiate OAuth2 login flow via Authlib."""
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


async def auth_callback(request: Request):
    """
    OAuth2 callback - Authlib handles token exchange and session creation.

    WorkspaceAuthMiddleware will later read from session and add groups.
    """
    try:
        # Authlib handles token exchange and stores in session automatically
        token = await oauth.google.authorize_access_token(request)

        # Extract user info from ID token (automatically parsed by Authlib)
        user_info = token.get("userinfo")

        if not user_info:
            return JSONResponse({"error": "Failed to get user info"}, status_code=500)

        # Store basic user info in session for WorkspaceAuthMiddleware
        # WorkspaceAuthMiddleware will read this and add groups
        request.session["user"] = {
            "email": user_info["email"],
            "user_id": user_info["sub"],
            "name": user_info.get("name", user_info["email"]),
            "domain": user_info["email"].split("@")[-1],
            "groups": [],  # WorkspaceAuthMiddleware will populate this
        }

        return RedirectResponse(url="/", status_code=302)

    except OAuthError as error:
        return HTMLResponse(f"""
        <html>
            <body>
                <h1>Authentication Error</h1>
                <p><strong>Error:</strong> {error.error}</p>
                <p><strong>Description:</strong> {error.description}</p>
                <p><a href="/">Go back</a></p>
            </body>
        </html>
        """)


async def logout(request: Request):
    """Logout - clear session."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


@require_auth
async def profile(request: Request):
    """Protected route - requires authentication."""
    user = request.user

    return JSONResponse(
        {
            "email": user.email,
            "user_id": user.user_id,
            "name": user.name,
            "domain": user.domain,
            "groups": user.groups,
            "is_authenticated": user.is_authenticated,
            "auth_method": "Authlib + SessionMiddleware + WorkspaceAuthMiddleware",
        }
    )


@require_auth
async def protected(request: Request):
    """Another protected route."""
    return JSONResponse(
        {
            "message": "This is a protected route",
            "user": request.user.email,
            "groups": request.user.groups,
        }
    )


@require_group("admins@example.com")
async def admin_only(request: Request):
    """Admin-only route - requires specific group membership."""
    return JSONResponse(
        {
            "message": "Admin access granted",
            "user": request.user.email,
            "groups": request.user.groups,
        }
    )


# Create Starlette app with middleware
middleware = [
    # 1. SessionMiddleware MUST come FIRST (Authlib needs it)
    Middleware(
        SessionMiddleware,
        secret_key=SESSION_SECRET,
        max_age=86400,  # 24 hours
        same_site="lax",
        https_only=False,  # Set to True in production with HTTPS
    ),
    # 2. AuthenticationMiddleware with WorkspaceAuthBackend
    #    Reads session and adds Google Workspace groups
    Middleware(
        AuthenticationMiddleware,
        backend=WorkspaceAuthBackend(
            client_id=CLIENT_ID,
            required_domains=[WORKSPACE_DOMAIN] if WORKSPACE_DOMAIN else None,
            fetch_groups=True,  # Fetch Google Workspace groups
            delegated_admin=DELEGATED_ADMIN,
            enable_session_auth=True,  # Read from session (populated by Authlib)
        ),
    ),
]

routes = [
    Route("/", home),
    Route("/login", login),
    Route("/auth/callback", auth_callback, name="auth_callback"),
    Route("/logout", logout),
    Route("/profile", profile),
    Route("/protected", protected),
    Route("/admin", admin_only),
]

app = Starlette(
    routes=routes,
    middleware=middleware,
)


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 70)
    print("Authlib + WorkspaceAuthMiddleware Example (Starlette)")
    print("=" * 70)
    print(f"\nClient ID: {CLIENT_ID}")
    print(f"Workspace Domain: {WORKSPACE_DOMAIN or 'Any'}")
    print("\n🏗️  Architecture:")
    print("  1. Authlib - OAuth2/OIDC authentication")
    print("  2. SessionMiddleware - Session management")
    print("  3. WorkspaceAuthMiddleware - Google Workspace groups")
    print("\n📚 Documentation:")
    print("  - Authlib: https://docs.authlib.org/en/latest/client/starlette.html")
    print("  - WorkspaceAuth: docs/SESSION_AUTHENTICATION.md")
    print("\n🌐 Visit: http://localhost:8000/")
    print("\n⚙️  Make sure to:")
    print("  1. Set GOOGLE_CLIENT_ID environment variable")
    print("  2. Set GOOGLE_CLIENT_SECRET environment variable")
    print("  3. Set SESSION_SECRET_KEY environment variable")
    print("  4. Configure redirect URI in Google Cloud Console:")
    print("     http://localhost:8000/auth/callback")
    print("  5. (Optional) Set GOOGLE_APPLICATION_CREDENTIALS for group fetching")
    print("=" * 70 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
