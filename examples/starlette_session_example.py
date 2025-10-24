"""
Complete OAuth2 Session Authentication Example using Starlette's SessionMiddleware.

This example demonstrates the RECOMMENDED approach for session-based authentication:
- Uses Starlette's built-in SessionMiddleware (signed cookies)
- Uses Authlib for OAuth2 authorization code flow
- Shows login, callback, and logout endpoints
- Demonstrates session-based authentication in protected routes

Setup:
1. Create OAuth2 credentials in Google Cloud Console
2. Install Authlib: poetry add authlib
3. Set environment variables:
   - GOOGLE_CLIENT_ID
   - GOOGLE_CLIENT_SECRET
   - SESSION_SECRET_KEY (or it will be generated)
   - GOOGLE_WORKSPACE_DOMAIN (optional, for domain restriction)

4. Run: poetry run python examples/starlette_session_example.py
5. Visit: http://localhost:8000/
"""

import os
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware
from authlib.integrations.starlette_client import OAuth
import uvicorn

from workspace_auth_middleware import (
    WorkspaceAuthBackend,
    require_auth,
    require_group,
)

# Configuration from environment
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "your-client-id.apps.googleusercontent.com")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "your-client-secret")
SESSION_SECRET = os.getenv("SESSION_SECRET_KEY", secrets.token_urlsafe(32))
WORKSPACE_DOMAIN = os.getenv("GOOGLE_WORKSPACE_DOMAIN")
DELEGATED_ADMIN = os.getenv("GOOGLE_DELEGATED_ADMIN")

# Create authentication backend
backend = WorkspaceAuthBackend(
    client_id=CLIENT_ID,
    required_domains=[WORKSPACE_DOMAIN] if WORKSPACE_DOMAIN else None,
    fetch_groups=True,
    delegated_admin=DELEGATED_ADMIN,
    enable_session_auth=True,  # Enable Starlette session support
)

# Create FastAPI app with middlewares
# IMPORTANT: SessionMiddleware MUST come BEFORE AuthenticationMiddleware
app = FastAPI(
    title="Starlette Session Auth Example",
    middleware=[
        # SessionMiddleware FIRST
        Middleware(
            SessionMiddleware,
            secret_key=SESSION_SECRET,
            max_age=86400,  # 24 hours
            same_site="lax",
            https_only=False,  # Set to True in production with HTTPS
        ),
        # AuthenticationMiddleware SECOND (reads from session)
        Middleware(
            AuthenticationMiddleware,
            backend=backend,
        ),
    ],
)

# Initialize Authlib OAuth client
oauth = OAuth()
oauth.register(
    name="google",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile",
        "hd": WORKSPACE_DOMAIN,  # Restrict to specific domain
    },
)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page - shows login button or user info."""
    if request.user.is_authenticated:
        return f"""
        <html>
            <head>
                <title>Starlette Session Example</title>
                <style>
                    body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }}
                    .user-info {{ background: #f0f0f0; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                    .links {{ margin: 20px 0; }}
                    .links a {{ display: inline-block; margin-right: 15px; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 4px; }}
                    .links a:hover {{ background: #0056b3; }}
                    .logout {{ background: #dc3545 !important; }}
                    .logout:hover {{ background: #c82333 !important; }}
                </style>
            </head>
            <body>
                <h1>Welcome, {request.user.display_name}!</h1>
                <div class="user-info">
                    <p><strong>Email:</strong> {request.user.email}</p>
                    <p><strong>User ID:</strong> {request.user.user_id}</p>
                    <p><strong>Domain:</strong> {request.user.domain}</p>
                    <p><strong>Groups:</strong> {", ".join(request.user.groups) if request.user.groups else "None"}</p>
                </div>
                <div class="links">
                    <a href="/profile">View Profile (API)</a>
                    <a href="/protected">Protected Route</a>
                    <a href="/stats">Cache Stats</a>
                    <a href="/logout" class="logout">Logout</a>
                </div>
                <hr>
                <p><em>Authenticated via: Starlette Session (request.session)</em></p>
            </body>
        </html>
        """
    else:
        return """
        <html>
            <head>
                <title>Starlette Session Example</title>
                <style>
                    body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; text-align: center; }
                    .login-btn { display: inline-block; padding: 15px 30px; background: #4285f4; color: white; text-decoration: none; border-radius: 4px; font-size: 16px; }
                    .login-btn:hover { background: #357ae8; }
                    .info { background: #f9f9f9; padding: 20px; margin: 30px 0; border-left: 4px solid #4285f4; text-align: left; }
                </style>
            </head>
            <body>
                <h1>Starlette Session Authentication Example</h1>
                <p>This demonstrates OAuth2 authorization code flow with Starlette's SessionMiddleware.</p>
                <div class="info">
                    <h3>How it works:</h3>
                    <ol>
                        <li>Click "Login with Google" below</li>
                        <li>Authorize with your Google account</li>
                        <li>Session is created and stored in signed cookie</li>
                        <li>Subsequent requests automatically authenticated via session</li>
                    </ol>
                </div>
                <a href="/login" class="login-btn">🔐 Login with Google</a>
            </body>
        </html>
        """


@app.get("/login")
async def login(request: Request):
    """Redirect to Google's OAuth2 authorization endpoint."""
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle OAuth2 callback from Google."""
    try:
        # Authlib handles token exchange and validation
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")

        if not user_info:
            return JSONResponse({"error": "Failed to get user info"}, status_code=400)

        # Extract user information
        email = user_info["email"]
        user_id = user_info["sub"]
        name = user_info.get("name", email)
        domain = email.split("@")[-1]

        # Store user in session for WorkspaceAuthMiddleware
        request.session["user"] = {
            "email": email,
            "user_id": user_id,
            "name": name,
            "domain": domain,
            "groups": [],  # Will be fetched by WorkspaceAuthBackend on next request
        }

        # Redirect to home page (user is now authenticated)
        return RedirectResponse(url="/", status_code=302)

    except Exception as e:
        return JSONResponse(
            {"error": "Authorization failed", "detail": str(e)}, status_code=500
        )


@app.get("/profile")
@require_auth
async def profile(request: Request):
    """Protected route - requires authentication (JSON response)."""
    user = request.user

    return {
        "email": user.email,
        "user_id": user.user_id,
        "name": user.name,
        "domain": user.domain,
        "groups": user.groups,
        "is_authenticated": user.is_authenticated,
        "auth_method": "session (request.session)",
    }


@app.get("/protected")
@require_auth
async def protected_route(request: Request):
    """Another protected route."""
    return {
        "message": "This is a protected route",
        "user": request.user.email,
        "session_data": dict(request.session),
    }


@app.get("/admin")
@require_group("admins@example.com")
async def admin_route(request: Request):
    """Admin-only route - requires specific group membership."""
    return {
        "message": "Admin access granted",
        "user": request.user.email,
        "groups": request.user.groups,
    }


@app.get("/logout")
async def logout(request: Request):
    """Logout - clear session data."""
    # Clear session
    request.session.clear()

    # Redirect to home
    return RedirectResponse(url="/", status_code=302)


@app.get("/stats")
async def stats():
    """Show cache statistics."""
    cache_stats = backend.get_cache_stats()

    return {
        "cache_stats": cache_stats,
        "session_middleware": "Starlette SessionMiddleware",
        "session_storage": "Signed cookies (no server storage)",
    }


@app.get("/session-info")
@require_auth
async def session_info(request: Request):
    """Show session information (for debugging)."""
    return {
        "session_data": dict(request.session),
        "user": {
            "email": request.user.email,
            "user_id": request.user.user_id,
            "name": request.user.name,
            "domain": request.user.domain,
            "groups": request.user.groups,
        },
    }


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("Starlette Session Authentication Example")
    print("=" * 70)
    print(f"\nClient ID: {CLIENT_ID}")
    print("Redirect URI: http://localhost:8000/auth/callback")
    print(f"Workspace Domain: {WORKSPACE_DOMAIN or 'Any'}")
    print("OAuth2 Library: Authlib")
    print("Session Storage: Starlette SessionMiddleware (signed cookies)")
    print("\nVisit: http://localhost:8000/")
    print("\nMake sure to:")
    print("1. Install Authlib: poetry add authlib")
    print("2. Set GOOGLE_CLIENT_ID environment variable")
    print("3. Set GOOGLE_CLIENT_SECRET environment variable")
    print(
        "4. Configure redirect URI (http://localhost:8000/auth/callback) in Google Cloud Console"
    )
    print("5. (Optional) Set GOOGLE_APPLICATION_CREDENTIALS for group fetching")
    print("=" * 70 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
