# Testing with Real Google Cloud Credentials

Quick guide for testing workspace-auth-middleware with your actual Google Workspace credentials.

## Quick Start (5 minutes)

### 1. Run the Interactive Setup

```bash
cd examples
./setup_env.sh
```

Follow the prompts to configure your environment.

### 2. Load Environment Variables

```bash
source .env
```

### 3. Run the Test Server

```bash
poetry run python examples/manual_testing.py
```

### 4. Get an ID Token

```bash
# Using gcloud CLI (easiest)
TOKEN=$(gcloud auth print-identity-token)

# Verify it works
echo $TOKEN
```

### 5. Test the API

```bash
# Public endpoint (no auth)
curl http://localhost:8000/

# Get your user info (requires auth)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/me

# Check group membership
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/groups/admins@yourdomain.com"
```

## Configuration Details

### Required Environment Variables

```bash
# Your OAuth2 Client ID from Google Cloud Console
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
```

### Optional Environment Variables

```bash
# Your Google Workspace domain (recommended)
export GOOGLE_WORKSPACE_DOMAIN="example.com"

# For group fetching (requires service account with domain-wide delegation)
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
export GOOGLE_DELEGATED_ADMIN="admin@example.com"
export FETCH_GROUPS="true"

# For integration tests
export TEST_USER_EMAIL="testuser@example.com"
export RUN_INTEGRATION_TESTS="true"
```

## Getting a Google ID Token

### Method 1: gcloud CLI (Recommended)

```bash
# Make sure you're logged in
gcloud auth login

# Get an ID token
gcloud auth print-identity-token

# Save it to a variable for easy testing
TOKEN=$(gcloud auth print-identity-token)
```

### Method 2: OAuth2 Playground

1. Go to [OAuth2 Playground](https://developers.google.com/oauthplayground/)
2. Click the gear icon (⚙️) in the top right
3. Check ☑️ "Use your own OAuth credentials"
4. Enter your OAuth Client ID and Secret
5. In Step 1, select:
   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/userinfo.profile`
   - `openid`
6. Click "Authorize APIs"
7. Sign in with your Google Workspace account
8. Click "Exchange authorization code for tokens"
9. Copy the `id_token` value

### Method 3: Browser DevTools (for testing web apps)

If you have a web application with Google Sign-In:

1. Open your app in Chrome/Firefox
2. Open DevTools (F12)
3. Go to Console tab
4. After signing in, run:
   ```javascript
   // For Google Sign-In v2
   gapi.auth2.getAuthInstance().currentUser.get().getAuthResponse().id_token

   // Or check Network tab for the token in authorization headers
   ```

## Testing Scenarios

### Scenario 1: Token Verification Only

**What it tests:** Token validation without group fetching

**Setup:**
```bash
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export FETCH_GROUPS="false"
```

**Test:**
```bash
poetry run python examples/manual_testing.py &
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/me
```

**Expected:** User info returned, but `groups` array is empty.

### Scenario 2: Token Verification + Group Fetching

**What it tests:** Full authentication with group membership

**Setup:**
```bash
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_WORKSPACE_DOMAIN="example.com"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
export GOOGLE_DELEGATED_ADMIN="admin@example.com"
export FETCH_GROUPS="true"
```

**Test:**
```bash
poetry run python examples/manual_testing.py &
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/me
```

**Expected:** User info with populated `groups` array showing all Google Workspace groups.

### Scenario 3: Group-Based Authorization

**What it tests:** Route protection with `@require_group` decorator

**Setup:** Same as Scenario 2

**Test:**
```bash
# This should succeed if you're in the admins group
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/admin

# This should return 403 if you're not in the group
```

**Expected:**
- 200 + success message if in group
- 403 + permission denied if not in group

### Scenario 4: Performance with Caching

**What it tests:** Cache effectiveness with repeated requests

**Test:**
```bash
# Make 10 requests and time them
for i in {1..10}; do
  time curl -s -H "Authorization: Bearer $TOKEN" \
       http://localhost:8000/me > /dev/null
done
```

**Expected:** First request ~100-500ms, subsequent requests <10ms

## Running Integration Tests

The test suite includes integration tests for real credential validation.

### Run All Integration Tests

```bash
export RUN_INTEGRATION_TESTS="true"
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_WORKSPACE_DOMAIN="example.com"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
export GOOGLE_DELEGATED_ADMIN="admin@example.com"
export TEST_USER_EMAIL="testuser@example.com"

poetry run pytest tests/test_integration_adc.py -v
```

### Run Specific Test

```bash
# Test ADC loading
poetry run pytest tests/test_integration_adc.py::TestADCIntegration::test_adc_credentials_available -v

# Test group fetching with real credentials
poetry run pytest tests/test_integration_adc.py::TestADCIntegration::test_group_fetching_with_adc -v
```

## Troubleshooting

### "GOOGLE_CLIENT_ID environment variable not set"

**Solution:**
```bash
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
```

Get your Client ID from: https://console.cloud.google.com/apis/credentials

### "Token verification failed: Wrong client ID"

**Cause:** The ID token was issued for a different OAuth Client ID.

**Solution:** Make sure the token was created using the same Client ID in `GOOGLE_CLIENT_ID`.

### "Could not load default credentials"

**Solution 1:** Set service account credentials:
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

**Solution 2:** Use gcloud user credentials:
```bash
gcloud auth application-default login
```

### "Group fetching failed: Insufficient permissions"

**Common causes:**
1. Service account doesn't have Groups Reader role in Google Workspace
2. OAuth scopes not configured correctly
3. Cloud Identity API not enabled

**Solution:**

1. Grant Groups Reader role:
   - Go to [Google Workspace Admin Console](https://admin.google.com/)
   - Account > Admin roles
   - Create or edit a role with Groups Reader privileges
   - Assign the role to your service account

2. Configure OAuth scopes:
   - Ensure your service account has the scope: `https://www.googleapis.com/auth/cloud-identity.groups.readonly`

3. Enable Cloud Identity API:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - APIs & Services > Library
   - Search "Cloud Identity API" > Enable

### "401 Unauthorized"

**Common causes:**
1. Token expired (tokens last 1 hour)
2. No Authorization header
3. Wrong token format

**Solution:**
```bash
# Get a fresh token
TOKEN=$(gcloud auth print-identity-token)

# Verify format: Authorization: Bearer <token>
curl -v -H "Authorization: Bearer $TOKEN" http://localhost:8000/me
```

### "403 Forbidden: User must belong to group"

**Cause:** User is not in the required Google Workspace group.

**Solution:**
1. Add user to the group in Google Workspace Admin
2. Wait up to 5 minutes for cache to expire
3. Or manually invalidate the cache (in production code)

## Google Cloud Setup

### Minimal Setup (Token Verification Only)

No special setup needed! Just create an OAuth 2.0 Client ID:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project
3. APIs & Services > Credentials
4. Create Credentials > OAuth 2.0 Client ID
5. Application type: Web application
6. Note the Client ID

### Complete Setup (With Group Fetching)

Follow the [complete setup guide](./examples/README.md#google-cloud-setup-requirements) for:
- Creating a service account
- Granting Groups Reader role in Google Workspace Admin
- Configuring OAuth scopes
- Enabling Cloud Identity API

## Additional Resources

- **Examples Directory:** [`./examples/`](./examples/)
- **Integration Tests:** [`./tests/test_integration_adc.py`](./tests/test_integration_adc.py)
- **Main Documentation:** [`./README.md`](./README.md)
- [Google OAuth2 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [Cloud Identity Groups API](https://cloud.google.com/identity/docs/reference/rest)
