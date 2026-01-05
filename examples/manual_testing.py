"""
Manual testing script for workspace-auth-middleware with real Google credentials.

This script sets up a test FastAPI server that you can use to test the middleware
with real Google OAuth2 ID tokens.

Setup Instructions:
===================

1. Set up Google Cloud credentials:

   Option A - Service Account (for group fetching):
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
   ```

   Option B - User credentials (no group fetching):
   ```bash
   gcloud auth application-default login
   ```

2. Set your OAuth2 Client ID:
   ```bash
   export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
   ```

3. Set your Google Workspace domain:
   ```bash
   export GOOGLE_WORKSPACE_DOMAIN="example.com"
   ```

4. (Optional) For group fetching with domain-wide delegation:
   ```bash
   export GOOGLE_DELEGATED_ADMIN="admin@example.com"
   ```

5. Run this script:
   ```bash
   poetry run python examples/manual_testing.py
   ```

Getting a Google ID Token:
==========================

Method 1 - Using gcloud CLI:
```bash
gcloud auth print-identity-token
```

Method 2 - Using OAuth2 Playground:
1. Go to https://developers.google.com/oauthplayground/
2. Click the gear icon (settings) in the top right
3. Check "Use your own OAuth credentials"
4. Enter your OAuth Client ID and Secret
5. In the list on the left, select "Google OAuth2 API v2" > "email, profile, openid"
6. Click "Authorize APIs"
7. Sign in with your Google Workspace account
8. Click "Exchange authorization code for tokens"
9. Copy the "id_token" value

Method 3 - Using Python script:
See get_id_token() function below for programmatic token generation.

Testing the API:
================

Once the server is running, test it with curl:

```bash
# Get your ID token
TOKEN=$(gcloud auth print-identity-token)

# Test public endpoint (no auth required)
curl http://localhost:8000/

# Test protected endpoint (requires auth)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/me

# Test admin endpoint (requires group membership)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/admin
```
"""

import os
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from workspace_auth_middleware import (
    WorkspaceAuthMiddleware,
    require_auth,
    require_group,
    PermissionDenied,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load configuration from environment
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
WORKSPACE_DOMAIN = os.getenv("GOOGLE_WORKSPACE_DOMAIN")
DELEGATED_ADMIN = os.getenv("GOOGLE_DELEGATED_ADMIN")
FETCH_GROUPS = os.getenv("FETCH_GROUPS", "true").lower() == "true"

# Validate required configuration
if not CLIENT_ID:
    logger.error("GOOGLE_CLIENT_ID environment variable not set!")
    logger.error("Please set it to your OAuth2 Client ID:")
    logger.error(
        "  export GOOGLE_CLIENT_ID='your-client-id.apps.googleusercontent.com'"
    )
    exit(1)

if not WORKSPACE_DOMAIN:
    logger.warning(
        "GOOGLE_WORKSPACE_DOMAIN not set. Domain validation will be disabled."
    )

# Create FastAPI app
app = FastAPI(title="Workspace Auth Middleware Test Server")


# Add custom error handler for PermissionDenied
@app.exception_handler(PermissionDenied)
async def permission_denied_handler(request: Request, exc: PermissionDenied):
    return JSONResponse(
        status_code=403, content={"error": "Forbidden", "message": str(exc)}
    )


# Configure middleware
logger.info("Configuring WorkspaceAuthMiddleware...")
logger.info("  Client ID: %s", CLIENT_ID)
logger.info(
    "  Workspace Domain: %s", WORKSPACE_DOMAIN or "Not set (any domain allowed)"
)
logger.info("  Fetch Groups: %s", FETCH_GROUPS)
logger.info("  Delegated Admin: %s", DELEGATED_ADMIN or "Not set")

app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id=CLIENT_ID,
    required_domains=[WORKSPACE_DOMAIN] if WORKSPACE_DOMAIN else None,
    fetch_groups=FETCH_GROUPS,
)

logger.info("Middleware configured successfully!")


# Routes


@app.get("/")
async def public_route():
    """Public endpoint - no authentication required."""
    return {
        "message": "Welcome to the Workspace Auth Middleware test server!",
        "endpoints": {
            "/": "This public endpoint (no auth required)",
            "/me": "Get current user info (auth required)",
            "/admin": "Admin-only endpoint (requires 'admins' group)",
            "/health": "Health check endpoint",
        },
        "how_to_test": "Add 'Authorization: Bearer <your-id-token>' header to requests",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint - no authentication required."""
    return {"status": "healthy"}


@app.get("/me")
@require_auth
async def get_user_info(request: Request):
    """Protected endpoint - returns information about the authenticated user."""
    user = request.user

    return {
        "authenticated": user.is_authenticated,
        "email": user.email,
        "user_id": user.user_id,
        "name": user.name,
        "domain": user.domain,
        "groups": user.groups,
        "picture": getattr(user, "picture", None),
    }


@app.get("/admin")
@require_group("admins@" + (WORKSPACE_DOMAIN or "example.com"))
async def admin_endpoint(request: Request):
    """
    Admin-only endpoint - requires membership in admins group.

    NOTE: Change the group name to match your actual admin group.
    """
    return {
        "message": "Admin access granted!",
        "user": request.user.email,
        "groups": request.user.groups,
    }


@app.get("/groups/{group_email}")
@require_auth
async def check_group_membership(request: Request, group_email: str):
    """Check if the current user belongs to a specific group."""
    user = request.user

    return {
        "user": user.email,
        "group": group_email,
        "is_member": user.has_group(group_email),
        "all_groups": user.groups,
    }


@app.get("/cache/stats")
@require_group("admins@" + (WORKSPACE_DOMAIN or "example.com"))
async def cache_stats(request: Request):
    """
    Admin endpoint to view cache statistics.

    This requires access to the backend instance, which is a bit tricky
    with the middleware pattern. In production, you'd want to expose this
    via a management interface.
    """
    return {
        "message": "Cache stats endpoint",
        "note": "In production, implement cache monitoring via your backend instance",
    }


def get_id_token_instructions():
    """Print instructions for getting an ID token."""
    print("\n" + "=" * 70)
    print("GETTING A GOOGLE ID TOKEN")
    print("=" * 70)
    print("\nMethod 1 - Using gcloud CLI (easiest):")
    print("  $ gcloud auth print-identity-token")
    print("\nMethod 2 - Using OAuth2 Playground:")
    print("  1. Visit https://developers.google.com/oauthplayground/")
    print("  2. Configure with your OAuth Client ID")
    print("  3. Authorize and get the 'id_token'")
    print("\nMethod 3 - Using curl with OAuth2:")
    print("  (See Google's OAuth2 documentation)")
    print("\nOnce you have a token, test with:")
    print("  $ curl -H 'Authorization: Bearer YOUR_TOKEN' http://localhost:8000/me")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    import uvicorn

    logger.info("\n" + "=" * 70)
    logger.info("Starting Workspace Auth Middleware Test Server")
    logger.info("=" * 70)

    get_id_token_instructions()

    logger.info("Server starting on http://localhost:8000")
    logger.info("Press CTRL+C to stop")
    logger.info("=" * 70 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
