# Examples Directory

This directory contains examples demonstrating how to use workspace-auth-middleware in various scenarios.

## Quick Start Guide

**Choose the right example for your use case:**

| Example | Best For | Authentication Method |
|---------|----------|----------------------|
| `authlib_fastapi_example.py` | **Production web applications** | Session cookies (OAuth2 flow) |
| `authlib_starlette_example.py` | **Lightweight web apps** | Session cookies (OAuth2 flow) |
| `manual_testing.py` | **Testing/debugging**, APIs | Bearer tokens (ID tokens) |
| `caching_example.py` | **Performance tuning** | Either method |

**For production web applications**, we **strongly recommend** the Authlib examples (#1 or #2). They provide:
- Industry-standard OAuth2 implementation
- Better security (PKCE, automatic state management)
- Session-based authentication (better UX for web apps)
- Easy integration with Google Workspace groups

## Available Examples

### 1. `authlib_fastapi_example.py` - Production-Ready OAuth2 with FastAPI (RECOMMENDED)

Complete production-ready example using Authlib + WorkspaceAuthMiddleware for OAuth2 authentication with Google Workspace.

**Features:**
- ✅ Industry-standard OAuth2 via Authlib
- ✅ Session-based authentication with SessionMiddleware
- ✅ Google Workspace group-based authorization
- ✅ Automatic API documentation (Swagger/ReDoc)
- ✅ PKCE security enabled by default
- ✅ Type-safe with FastAPI dependencies

**Run it:**
```bash
# 1. Set environment variables
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="your-client-secret"
export SESSION_SECRET_KEY="your-secret-key"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"  # Optional, for groups
export GOOGLE_DELEGATED_ADMIN="admin@example.com"  # Optional, for groups
export GOOGLE_WORKSPACE_DOMAIN="example.com"  # Optional

# 2. Install Authlib
poetry add authlib

# 3. Run the example
poetry run python examples/authlib_fastapi_example.py

# 4. Visit http://localhost:8000/ in your browser
```

**What you'll see:**
- Login page with Google OAuth2
- Protected routes requiring authentication
- Admin-only routes requiring group membership
- Interactive Swagger UI at `/docs`

### 2. `authlib_starlette_example.py` - Production-Ready OAuth2 with Starlette

Same features as the FastAPI example, but using pure Starlette for lightweight applications.

**Run it:**
```bash
poetry run python examples/authlib_starlette_example.py
# Visit http://localhost:8000/
```

### 3. `caching_example.py` - Performance Caching

Demonstrates how to:
- Enable/disable caching
- Configure cache TTL and sizes
- Monitor cache statistics
- Invalidate cache entries

**Run it:**
```bash
poetry run python examples/caching_example.py
```

### 4. `manual_testing.py` - Test with Real Google Credentials (Bearer Token Auth)

A complete FastAPI server for manual testing with real Google OAuth2 tokens.

**Setup:**

1. **Set up your Google Cloud credentials:**

   For service accounts (recommended for group fetching):
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
   ```

   Or use your user credentials:
   ```bash
   gcloud auth application-default login
   ```

2. **Configure environment variables:**
   ```bash
   # Required: Your OAuth2 Client ID
   export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"

   # Recommended: Your workspace domain
   export GOOGLE_WORKSPACE_DOMAIN="example.com"

   # Optional: Admin email for domain-wide delegation (required for group fetching)
   export GOOGLE_DELEGATED_ADMIN="admin@example.com"

   # Optional: Enable/disable group fetching (default: true)
   export FETCH_GROUPS="true"
   ```

3. **Install uvicorn:**
   ```bash
   poetry add --group dev uvicorn
   ```

4. **Run the test server:**
   ```bash
   poetry run python examples/manual_testing.py
   ```

5. **Get a Google ID token:**
   ```bash
   # Using gcloud CLI (easiest)
   TOKEN=$(gcloud auth print-identity-token)

   # Or visit OAuth2 Playground:
   # https://developers.google.com/oauthplayground/
   ```

6. **Test the API:**
   ```bash
   # Public endpoint (no auth)
   curl http://localhost:8000/

   # Protected endpoint (requires auth)
   curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/me

   # Check group membership
   curl -H "Authorization: Bearer $TOKEN" \
        http://localhost:8000/groups/admins@example.com

   # Admin endpoint (requires admin group)
   curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/admin
   ```

## Running Integration Tests

The test suite includes integration tests that use real Google credentials.

**Setup:**

1. **Configure your environment:**
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
   export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
   export GOOGLE_WORKSPACE_DOMAIN="example.com"
   export GOOGLE_DELEGATED_ADMIN="admin@example.com"
   export TEST_USER_EMAIL="testuser@example.com"
   export RUN_INTEGRATION_TESTS="true"
   ```

2. **Run the integration tests:**
   ```bash
   # Run all integration tests
   poetry run pytest tests/test_integration_adc.py -v

   # Run specific test
   poetry run pytest tests/test_integration_adc.py::TestADCIntegration::test_adc_credentials_available -v
   ```

## Google Cloud Setup Requirements

### For Token Verification Only

You only need:
- A Google Cloud project
- An OAuth2 Client ID (Web application type)

No credentials file is needed - token verification happens via Google's public API.

### For Group Fetching

You need:
1. **Service Account** in your Google Cloud project
2. **Cloud Identity API** enabled in your Google Cloud project
3. **Groups Reader role** granted to the service account in Google Workspace Admin
4. **OAuth Scopes** configured for the service account:
   - `https://www.googleapis.com/auth/cloud-identity.groups.readonly`
5. **Service Account Key** downloaded as JSON

**Steps:**

1. **Create Service Account:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Navigate to IAM & Admin > Service Accounts
   - Create a new service account
   - Download the JSON key

2. **Enable Cloud Identity API:**
   - Go to APIs & Services > Library
   - Search for "Cloud Identity API"
   - Click Enable

3. **Grant Groups Reader Role:**
   - Go to your [Google Workspace Admin Console](https://admin.google.com/)
   - Navigate to Account > Admin roles
   - Create or edit a role with Groups Reader privileges
   - Assign the role to your service account

4. **Set environment variable:**
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
   ```

## Troubleshooting

### "Could not load default credentials"

Make sure one of these is set:
```bash
# Option 1: Service account key
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"

# Option 2: User credentials
gcloud auth application-default login
```

### "Token verification failed"

- Check that your `GOOGLE_CLIENT_ID` is correct
- Make sure the token was issued for your Client ID
- Tokens expire after 1 hour - get a fresh token

### "Group fetching failed"

Common issues:
- Service account doesn't have domain-wide delegation
- Wrong OAuth scopes configured
- `GOOGLE_DELEGATED_ADMIN` not set or incorrect
- Admin SDK API not enabled

### "User not in required group"

- Verify the user actually belongs to the group in Google Workspace Admin
- Check the group email matches exactly (including domain)
- Wait up to 5 minutes for cache to expire if membership just changed

## Additional Resources

- [Google OAuth2 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [Service Account Domain-Wide Delegation](https://developers.google.com/identity/protocols/oauth2/service-account#delegatingauthority)
- [Admin SDK Directory API](https://developers.google.com/admin-sdk/directory/)
- [Starlette Authentication](https://www.starlette.io/authentication/)
