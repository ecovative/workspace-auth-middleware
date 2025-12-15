"""
Production-Ready OAuth2 Example using Authlib + WorkspaceAuthMiddleware (FastAPI).

This demonstrates the RECOMMENDED approach for FastAPI applications:
- Authlib handles OAuth2/OIDC (login, token exchange, session management)
- WorkspaceAuthMiddleware handles Google Workspace-specific features (groups, authorization)

Setup:
1. Install dependencies:
   poetry add authlib

2. Set environment variables:
   - GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
   - GOOGLE_CLIENT_SECRET="your-client-secret"
   - SESSION_SECRET_KEY="your-secret-key"
   - GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
   - GOOGLE_DELEGATED_ADMIN="admin@example.com"
   - GOOGLE_WORKSPACE_DOMAIN="example.com"  # Optional

3. Configure OAuth2 redirect URI in Google Cloud Console:
   http://localhost:8000/auth/callback

4. Run:
   poetry run python examples/authlib_fastapi_example.py

5. Visit:
   http://localhost:8000/
   http://localhost:8000/docs  # Swagger UI
"""

import os
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware

# Authlib for OAuth2/OIDC
from authlib.integrations.starlette_client import OAuth, OAuthError

# WorkspaceAuthMiddleware for Google Workspace features
from workspace_auth_middleware import (
    WorkspaceAuthBackend,
    require_auth,
    require_group,
    WorkspaceUser,
)

# Configuration
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
    client_kwargs={"scope": "openid email profile"},
)

# Create FastAPI app with middleware
app = FastAPI(
    title="Authlib + WorkspaceAuth Example",
    description="Production-ready OAuth2 with Google Workspace integration",
    version="1.0.0",
    middleware=[
        # SessionMiddleware MUST come FIRST
        Middleware(
            SessionMiddleware,
            secret_key=SESSION_SECRET,
            max_age=86400,
            same_site="lax",
            https_only=False,
        ),
        # AuthenticationMiddleware with WorkspaceAuthBackend
        Middleware(
            AuthenticationMiddleware,
            backend=WorkspaceAuthBackend(
                client_id=CLIENT_ID,
                required_domains=[WORKSPACE_DOMAIN] if WORKSPACE_DOMAIN else None,
                fetch_groups=True,
                enable_session_auth=True,
            ),
        ),
    ],
)


# Dependency for getting current user
def get_current_user(request: Request) -> WorkspaceUser:
    """Dependency to get current authenticated user."""
    return request.user


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with login/user info."""
    user = request.user

    if user.is_authenticated:
        groups_html = (
            " ".join([f'<span class="badge">{g}</span>' for g in user.groups])
            if user.groups
            else "None"
        )

        return HTMLResponse(f"""
        <html>
            <head>
                <title>FastAPI + Authlib + WorkspaceAuth</title>
                <style>
                    body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 50px auto; padding: 20px; }}
                    .user-info {{ background: #f0f0f0; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                    .badge {{ display: inline-block; padding: 4px 12px; background: #007bff; color: white; border-radius: 12px; font-size: 12px; margin: 2px; }}
                    .links {{ margin: 20px 0; }}
                    .links a {{ display: inline-block; margin-right: 15px; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 4px; }}
                    .links a:hover {{ background: #0056b3; }}
                    .logout {{ background: #dc3545 !important; }}
                    .tech-stack {{ background: #e3f2fd; padding: 15px; border-left: 4px solid #2196f3; margin: 20px 0; }}
                    .api-docs {{ background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 20px 0; }}
                </style>
            </head>
            <body>
                <h1>Welcome, {user.display_name}! 👋</h1>
                <div class="user-info">
                    <p><strong>Email:</strong> {user.email}</p>
                    <p><strong>User ID:</strong> {user.user_id}</p>
                    <p><strong>Domain:</strong> {user.domain or "N/A"}</p>
                    <p><strong>Groups:</strong> {groups_html}</p>
                </div>
                <div class="links">
                    <a href="/profile">View Profile (API)</a>
                    <a href="/protected">Protected Route</a>
                    <a href="/docs">API Docs (Swagger)</a>
                    <a href="/logout" class="logout">Logout</a>
                </div>
                <div class="api-docs">
                    <strong>📚 API Documentation:</strong>
                    <ul>
                        <li><a href="/docs">Swagger UI</a> - Interactive API documentation</li>
                        <li><a href="/redoc">ReDoc</a> - Alternative API docs</li>
                    </ul>
                </div>
                <div class="tech-stack">
                    <strong>🔧 Tech Stack:</strong>
                    <ul>
                        <li><strong>FastAPI</strong> - Modern async web framework</li>
                        <li><strong>Authlib</strong> - OAuth2/OIDC authentication</li>
                        <li><strong>Starlette SessionMiddleware</strong> - Session management</li>
                        <li><strong>WorkspaceAuthMiddleware</strong> - Google Workspace groups</li>
                    </ul>
                </div>
            </body>
        </html>
        """)
    else:
        return HTMLResponse("""
        <html>
            <head>
                <title>FastAPI + Authlib + WorkspaceAuth</title>
                <style>
                    body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; text-align: center; }
                    .login-btn { display: inline-block; padding: 15px 30px; background: #4285f4; color: white; text-decoration: none; border-radius: 4px; font-size: 16px; }
                    .info { background: #f9f9f9; padding: 20px; margin: 30px 0; border-left: 4px solid #4285f4; text-align: left; }
                </style>
            </head>
            <body>
                <h1>FastAPI + Authlib + WorkspaceAuthMiddleware</h1>
                <p>Production-ready OAuth2 with Google Workspace</p>
                <div class="info">
                    <h3>Features:</h3>
                    <ul>
                        <li>✅ Industry-standard OAuth2 via Authlib</li>
                        <li>✅ Google Workspace group-based authorization</li>
                        <li>✅ Automatic API documentation (Swagger/ReDoc)</li>
                        <li>✅ Type-safe with FastAPI dependencies</li>
                    </ul>
                </div>
                <a href="/login" class="login-btn">🔐 Login with Google</a>
                <p style="margin-top: 30px;"><a href="/docs">View API Documentation</a></p>
            </body>
        </html>
        """)


@app.get("/login")
async def login(request: Request):
    """Initiate OAuth2 login flow."""
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """OAuth2 callback - handle token exchange."""
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")

        if not user_info:
            return JSONResponse({"error": "Failed to get user info"}, status_code=500)

        # Store user in session for WorkspaceAuthMiddleware
        request.session["user"] = {
            "email": user_info["email"],
            "user_id": user_info["sub"],
            "name": user_info.get("name", user_info["email"]),
            "domain": user_info["email"].split("@")[-1],
            "groups": [],  # WorkspaceAuthMiddleware will populate
        }

        return RedirectResponse(url="/", status_code=302)

    except OAuthError as error:
        return JSONResponse(
            {"error": error.error, "description": error.description}, status_code=400
        )


@app.get("/logout")
async def logout(request: Request):
    """Logout - clear session."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


@app.get("/profile")
@require_auth
async def profile(user: WorkspaceUser = Depends(get_current_user)):
    """
    Protected endpoint - requires authentication.

    Returns current user profile information.
    """
    return {
        "email": user.email,
        "user_id": user.user_id,
        "name": user.name,
        "domain": user.domain,
        "groups": user.groups,
        "is_authenticated": user.is_authenticated,
        "auth_method": "Authlib + WorkspaceAuthMiddleware",
    }


@app.get("/protected")
@require_auth
async def protected(user: WorkspaceUser = Depends(get_current_user)):
    """Protected route - requires authentication."""
    return {
        "message": "This is a protected route",
        "user": user.email,
        "groups": user.groups,
    }


@app.get("/admin")
@require_group("admins@example.com")
async def admin_only(user: WorkspaceUser = Depends(get_current_user)):
    """
    Admin-only endpoint - requires 'admins@example.com' group membership.

    Only users who are members of the admins group can access this endpoint.
    """
    return {
        "message": "Admin access granted",
        "user": user.email,
        "groups": user.groups,
    }


@app.get("/teams")
@require_group(["team-a@example.com", "team-b@example.com"])
async def team_routes(user: WorkspaceUser = Depends(get_current_user)):
    """
    Team endpoint - requires membership in team-a OR team-b.

    Users must be in at least one of the specified groups.
    """
    return {
        "message": "Team access granted",
        "user": user.email,
        "groups": user.groups,
    }


@app.get("/me")
async def me(request: Request):
    """
    Get current user without requiring authentication.

    Returns user info if authenticated, or anonymous status.
    """
    user = request.user

    if user.is_authenticated:
        return {
            "authenticated": True,
            "email": user.email,
            "name": user.name,
            "groups": user.groups,
        }
    else:
        return {
            "authenticated": False,
            "message": "Not authenticated",
        }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 70)
    print("FastAPI + Authlib + WorkspaceAuthMiddleware Example")
    print("=" * 70)
    print(f"\nClient ID: {CLIENT_ID}")
    print(f"Workspace Domain: {WORKSPACE_DOMAIN or 'Any'}")
    print("\n🏗️  Architecture:")
    print("  1. FastAPI - Modern async web framework")
    print("  2. Authlib - OAuth2/OIDC authentication")
    print("  3. SessionMiddleware - Session management")
    print("  4. WorkspaceAuthMiddleware - Google Workspace groups")
    print("\n📚 Features:")
    print("  • Automatic API documentation (Swagger/ReDoc)")
    print("  • Type-safe dependencies")
    print("  • Group-based authorization decorators")
    print("  • Production-ready architecture")
    print("\n🌐 URLs:")
    print("  • App: http://localhost:8000/")
    print("  • Swagger: http://localhost:8000/docs")
    print("  • ReDoc: http://localhost:8000/redoc")
    print("\n⚙️  Required Environment Variables:")
    print("  • GOOGLE_CLIENT_ID")
    print("  • GOOGLE_CLIENT_SECRET")
    print("  • SESSION_SECRET_KEY")
    print("  • GOOGLE_APPLICATION_CREDENTIALS (optional, for groups)")
    print("  • GOOGLE_DELEGATED_ADMIN (optional, for groups)")
    print("=" * 70 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
