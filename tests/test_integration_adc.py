"""
Integration tests using Application Default Credentials from the environment.

These tests verify that the middleware works with real Google credentials
configured via the GOOGLE_APPLICATION_CREDENTIALS environment variable.

Setup instructions:
1. Follow https://cloud.google.com/docs/authentication/set-up-adc-local-dev-environment
2. Set GOOGLE_APPLICATION_CREDENTIALS to your service account key path
3. Ensure the service account has Groups Reader role in Google Workspace Admin
4. Ensure the service account has the Cloud Identity scope:
   https://www.googleapis.com/auth/cloud-identity.groups.readonly

These tests will be skipped if:
- GOOGLE_APPLICATION_CREDENTIALS is not set
- The credentials cannot be loaded
- RUN_INTEGRATION_TESTS environment variable is not set
"""

import os
import importlib.util
import pytest
from unittest.mock import patch
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from workspace_auth_middleware import WorkspaceAuthMiddleware, WorkspaceAuthBackend


# Skip these tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "true",
    reason="Integration tests require RUN_INTEGRATION_TESTS=true and valid ADC",
)


@pytest.fixture
def adc_available():
    """
    Check if Application Default Credentials are available.
    """
    try:
        from google.auth import default

        credentials, project = default(
            scopes=["https://www.googleapis.com/auth/cloud-identity.groups.readonly"]
        )
        return credentials is not None
    except Exception:
        return False


@pytest.fixture
def integration_client_id():
    """
    Get client ID from environment for integration tests.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        pytest.skip("GOOGLE_CLIENT_ID environment variable not set")
    return client_id


@pytest.fixture
def integration_required_domains():
    """
    Get workspace domains from environment for integration tests.
    """
    domain = os.getenv("GOOGLE_WORKSPACE_DOMAIN")
    if not domain:
        pytest.skip("GOOGLE_WORKSPACE_DOMAIN environment variable not set")
    return [domain]


@pytest.fixture
def integration_admin_email():
    """
    Get admin email for domain-wide delegation from environment.
    """
    admin_email = os.getenv("GOOGLE_DELEGATED_ADMIN")
    if not admin_email:
        pytest.skip("GOOGLE_DELEGATED_ADMIN environment variable not set")
    return admin_email


class TestADCIntegration:
    """Integration tests using real Application Default Credentials."""

    def test_adc_credentials_available(self, adc_available):
        """Test that ADC can be loaded from environment."""
        assert adc_available, (
            "Application Default Credentials not available. "
            "Please set GOOGLE_APPLICATION_CREDENTIALS or run 'gcloud auth application-default login'"
        )

    def test_backend_loads_adc(
        self, integration_client_id, integration_required_domains, adc_available
    ):
        """Test that WorkspaceAuthBackend loads ADC automatically."""
        if not adc_available:
            pytest.skip("ADC not available")

        backend = WorkspaceAuthBackend(
            client_id=integration_client_id,
            required_domains=integration_required_domains,
            fetch_groups=True,  # This should trigger ADC loading
        )

        # Backend should have loaded credentials
        assert backend.credentials is not None
        assert backend.client_id == integration_client_id
        assert backend.required_domains == integration_required_domains

    def test_backend_with_explicit_adc(
        self,
        integration_client_id,
        integration_required_domains,
        integration_admin_email,
        adc_available,
    ):
        """Test backend with explicitly loaded ADC and domain-wide delegation."""
        if not adc_available:
            pytest.skip("ADC not available")

        from google.auth import default

        credentials, _ = default(
            scopes=["https://www.googleapis.com/auth/cloud-identity.groups.readonly"]
        )

        backend = WorkspaceAuthBackend(
            client_id=integration_client_id,
            required_domains=integration_required_domains,
            credentials=credentials,
            fetch_groups=True,
        )

        assert backend.credentials is not None

    @pytest.mark.asyncio
    async def test_group_fetching_with_adc(
        self,
        integration_client_id,
        integration_required_domains,
        integration_admin_email,
        adc_available,
    ):
        """
        Test that group fetching works with real ADC.

        Note: This test requires:
        - Valid service account with Groups Reader role
        - Cloud Identity API enabled
        - Proper scopes configured
        """
        if not adc_available:
            pytest.skip("ADC not available")

        # Check if google-api-python-client is installed
        if importlib.util.find_spec("googleapiclient") is None:
            pytest.skip("google-api-python-client not installed")

        backend = WorkspaceAuthBackend(
            client_id=integration_client_id,
            required_domains=integration_required_domains,
            fetch_groups=True,
        )

        # Test email (should exist in your workspace for this test)
        test_email = os.getenv("TEST_USER_EMAIL")
        if not test_email:
            pytest.skip("TEST_USER_EMAIL environment variable not set")

        # Attempt to fetch groups for test user
        try:
            groups = await backend._fetch_user_groups(test_email)

            # If successful, groups should be a list (may be empty)
            assert isinstance(groups, list)

            # Log the groups for debugging (optional)
            if groups:
                print(f"User {test_email} belongs to groups: {groups}")
            else:
                print(f"User {test_email} has no group memberships")

        except Exception as e:
            pytest.fail(f"Group fetching failed with ADC: {str(e)}")


class TestMiddlewareWithADC:
    """Integration tests for middleware using ADC."""

    @pytest.fixture
    def app_with_adc(
        self,
        integration_client_id,
        integration_required_domains,
        integration_admin_email,
        adc_available,
    ):
        """Create test app using ADC."""
        if not adc_available:
            pytest.skip("ADC not available")

        async def protected_endpoint(request):
            user = request.user
            return JSONResponse(
                {
                    "authenticated": user.is_authenticated,
                    "email": user.email if user.is_authenticated else None,
                    "groups": user.groups if user.is_authenticated else [],
                }
            )

        routes = [Route("/protected", protected_endpoint)]
        app = Starlette(routes=routes)

        # Middleware will automatically use ADC
        app.add_middleware(
            WorkspaceAuthMiddleware,
            client_id=integration_client_id,
            required_domains=integration_required_domains,
            fetch_groups=True,
        )

        return app

    def test_middleware_anonymous_user(self, app_with_adc, adc_available):
        """Test middleware with ADC for anonymous user."""
        if not adc_available:
            pytest.skip("ADC not available")

        client = TestClient(app_with_adc)
        response = client.get("/protected")

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_middleware_with_valid_token_and_adc(
        self,
        mock_verify,
        app_with_adc,
        valid_id_token_claims,
        mock_id_token,
        adc_available,
    ):
        """Test middleware validates tokens correctly when using ADC."""
        if not adc_available:
            pytest.skip("ADC not available")

        # Mock token verification (we're not testing Google's token validation)
        mock_verify.return_value = valid_id_token_claims

        client = TestClient(app_with_adc)
        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["email"] == "user@example.com"
        # Groups list may or may not be populated depending on Admin SDK availability
        assert isinstance(data["groups"], list)


class TestADCConfigurationErrors:
    """Tests for handling ADC configuration errors gracefully."""

    def test_backend_without_adc_fetch_groups_disabled(self, integration_client_id):
        """Test backend works without ADC when fetch_groups=False."""
        # Should not try to load ADC
        backend = WorkspaceAuthBackend(
            client_id=integration_client_id,
            fetch_groups=False,
        )

        assert backend.credentials is None

    @patch("google.auth.default")
    def test_backend_handles_adc_load_failure(
        self, mock_default, integration_client_id
    ):
        """Test backend handles ADC loading failure gracefully."""
        # Simulate ADC not being available
        mock_default.side_effect = Exception("Could not load default credentials")

        # Should not raise, but set credentials to None
        backend = WorkspaceAuthBackend(
            client_id=integration_client_id,
            fetch_groups=True,
        )

        assert backend.credentials is None
