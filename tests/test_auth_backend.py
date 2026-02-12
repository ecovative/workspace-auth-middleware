"""
Tests for WorkspaceAuthBackend authentication functionality.
"""

import urllib.parse

import pytest
from unittest.mock import Mock, patch
from starlette.authentication import AuthenticationError
from starlette.requests import HTTPConnection

from workspace_auth_middleware.auth import WorkspaceAuthBackend
from workspace_auth_middleware.models import WorkspaceUser


@pytest.mark.asyncio
class TestWorkspaceAuthBackend:
    """Tests for the WorkspaceAuthBackend class."""

    async def test_init_with_explicit_credentials(
        self, client_id, required_domains, mock_google_credentials
    ):
        """Test backend initialization with explicit credentials."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            credentials=mock_google_credentials,
        )

        assert backend.client_id == client_id
        assert backend.required_domains == required_domains
        assert backend.credentials == mock_google_credentials

    async def test_init_without_credentials_fetch_groups_disabled(
        self, client_id, required_domains
    ):
        """Test that no credentials are loaded when fetch_groups is False."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
        )

        assert backend.credentials is None

    @patch("google.auth.default")
    async def test_init_with_default_credentials(
        self, mock_default, client_id, required_domains, mock_google_credentials
    ):
        """Test that default application credentials are loaded automatically."""
        # Mock google.auth.default() to return test credentials
        mock_default.return_value = (mock_google_credentials, "project-id")

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=True,  # This should trigger ADC loading
        )

        # Verify default() was called with the correct scope
        mock_default.assert_called_once_with(
            scopes=["https://www.googleapis.com/auth/cloud-identity.groups.readonly"]
        )
        assert backend.credentials == mock_google_credentials

    @patch("google.auth.default")
    async def test_init_with_default_credentials_not_available(
        self, mock_default, client_id, required_domains
    ):
        """Test graceful handling when default credentials are not available."""
        # Mock google.auth.default() to raise an exception
        mock_default.side_effect = Exception("Default credentials not available")

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=True,
        )

        # Should handle the exception gracefully
        assert backend.credentials is None

    async def test_authenticate_no_authorization_header(self, client_id):
        """Test authentication returns None when no Authorization header present."""
        backend = WorkspaceAuthBackend(client_id=client_id, fetch_groups=False)

        # Mock HTTPConnection without authorization header
        conn = Mock(spec=HTTPConnection)
        conn.headers = {}

        result = await backend.authenticate(conn)

        assert result is None  # Returns None for anonymous users

    async def test_authenticate_invalid_scheme(self, client_id):
        """Test authentication fails with non-Bearer scheme."""
        backend = WorkspaceAuthBackend(client_id=client_id, fetch_groups=False)

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": "Basic user:pass"}

        with pytest.raises(AuthenticationError, match="Invalid authentication scheme"):
            await backend.authenticate(conn)

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_authenticate_valid_token(
        self,
        mock_verify,
        client_id,
        required_domains,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test successful authentication with valid token."""
        mock_verify.return_value = valid_id_token_claims

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        credentials, user = await backend.authenticate(conn)

        # Verify token was verified
        mock_verify.assert_called_once()

        # Check user object
        assert isinstance(user, WorkspaceUser)
        assert user.email == "user@example.com"
        assert user.user_id == "1234567890"
        assert user.name == "Test User"
        assert user.domain == "example.com"

        # Check credentials
        assert "authenticated" in credentials.scopes

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_authenticate_token_wrong_domain(
        self, mock_verify, client_id, valid_id_token_claims, mock_id_token
    ):
        """Test authentication fails when user is from wrong domain."""
        mock_verify.return_value = valid_id_token_claims

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=["otherdomain.com"],  # Different domain
            fetch_groups=False,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        with pytest.raises(AuthenticationError, match="not in allowed domains"):
            await backend.authenticate(conn)

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch.object(WorkspaceAuthBackend, "_fetch_user_groups")
    async def test_authenticate_with_groups(
        self,
        mock_fetch_groups,
        mock_verify,
        client_id,
        required_domains,
        valid_id_token_claims,
        mock_id_token,
        sample_groups,
    ):
        """Test authentication with group fetching enabled."""
        mock_verify.return_value = valid_id_token_claims
        mock_fetch_groups.return_value = sample_groups

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        credentials, user = await backend.authenticate(conn)

        # Verify groups were fetched
        mock_fetch_groups.assert_called_once_with("user@example.com")

        # Check user has groups
        assert user.groups == sample_groups

        # Check scopes include group scopes
        assert "authenticated" in credentials.scopes
        assert "group:admins@example.com" in credentials.scopes
        assert "group:developers@example.com" in credentials.scopes
        assert "group:team-leads@example.com" in credentials.scopes

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_verify_token_invalid_issuer(
        self, mock_verify, client_id, mock_id_token
    ):
        """Test authentication fails with invalid token issuer."""
        invalid_claims = {
            "iss": "https://evil.com",  # Invalid issuer
            "sub": "123",
            "email": "user@example.com",
        }
        mock_verify.return_value = invalid_claims

        backend = WorkspaceAuthBackend(client_id=client_id, fetch_groups=False)

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        with pytest.raises(AuthenticationError, match="Invalid token issuer"):
            await backend.authenticate(conn)


@pytest.mark.asyncio
class TestGroupFetching:
    """Tests for group fetching functionality."""

    async def test_fetch_groups_no_credentials(self, client_id):
        """Test group fetching returns empty list when no credentials."""
        backend = WorkspaceAuthBackend(client_id=client_id, fetch_groups=False)
        backend.credentials = None

        groups = await backend._fetch_user_groups("user@example.com")

        assert groups == []

    @patch("googleapiclient.discovery.build")
    async def test_fetch_groups_api_client_not_installed(
        self, mock_build, client_id, mock_google_credentials
    ):
        """Test group fetching handles missing googleapiclient gracefully."""
        # Mock import error
        mock_build.side_effect = ImportError("No module named 'googleapiclient'")

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
        )

        groups = await backend._fetch_user_groups("user@example.com")

        # Should return empty list, not raise exception
        assert groups == []

    @patch("googleapiclient.discovery.build")
    async def test_fetch_groups_cloud_identity_api(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_cloud_identity_service,
        sample_groups,
    ):
        """Test group fetching using Cloud Identity API."""
        mock_build.return_value = mock_cloud_identity_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
        )

        groups = await backend._fetch_user_groups("user@example.com")

        # Verify Cloud Identity API was called
        mock_cloud_identity_service.groups().memberships().searchTransitiveGroups.assert_called()

        assert groups == sample_groups

    @patch("googleapiclient.discovery.build")
    async def test_fetch_groups_api_error(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_cloud_identity_service,
    ):
        """Test group fetching handles API errors gracefully."""
        # Mock API error
        mock_cloud_identity_service.groups().memberships().searchTransitiveGroups().execute.side_effect = Exception(
            "API Error"
        )
        mock_build.return_value = mock_cloud_identity_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
        )

        groups = await backend._fetch_user_groups("user@example.com")

        # Should return empty list on error, not raise
        assert groups == []


@pytest.mark.asyncio
class TestEmailVerified:
    """Tests for email_verified claim checking."""

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_email_not_verified_is_rejected(
        self, mock_verify, client_id, valid_id_token_claims, mock_id_token
    ):
        """Test authentication fails when email_verified is False."""
        claims = {**valid_id_token_claims, "email_verified": False}
        mock_verify.return_value = claims

        backend = WorkspaceAuthBackend(client_id=client_id, fetch_groups=False)

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        with pytest.raises(
            AuthenticationError, match="Email address has not been verified"
        ):
            await backend.authenticate(conn)

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_email_verified_missing_is_rejected(
        self, mock_verify, client_id, valid_id_token_claims, mock_id_token
    ):
        """Test authentication fails when email_verified claim is absent."""
        claims = {
            k: v for k, v in valid_id_token_claims.items() if k != "email_verified"
        }
        mock_verify.return_value = claims

        backend = WorkspaceAuthBackend(client_id=client_id, fetch_groups=False)

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        with pytest.raises(
            AuthenticationError, match="Email address has not been verified"
        ):
            await backend.authenticate(conn)

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_email_verified_true_is_accepted(
        self,
        mock_verify,
        client_id,
        required_domains,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test authentication succeeds when email_verified is True."""
        mock_verify.return_value = (
            valid_id_token_claims  # already has email_verified: True
        )

        backend = WorkspaceAuthBackend(
            client_id=client_id, required_domains=required_domains, fetch_groups=False
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        credentials, user = await backend.authenticate(conn)
        assert user.email == "user@example.com"


@pytest.mark.asyncio
class TestCustomerId:
    """Tests for customer_id configuration."""

    @patch(
        "workspace_auth_middleware.auth.urllib.parse.urlencode",
        wraps=urllib.parse.urlencode,
    )
    @patch("googleapiclient.discovery.build")
    async def test_query_includes_customer_id_when_set(
        self,
        mock_build,
        mock_urlencode,
        client_id,
        mock_google_credentials,
        mock_cloud_identity_service,
        sample_groups,
    ):
        """Test that the API query includes parent filter when customer_id is set."""
        mock_build.return_value = mock_cloud_identity_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            customer_id="C028qv0z5",
        )

        await backend._fetch_user_groups("user@example.com")

        # Verify urlencode was called with a query containing parent filter
        call_args = mock_urlencode.call_args[0][0]
        assert "parent == 'customers/C028qv0z5'" in call_args["query"]

    @patch(
        "workspace_auth_middleware.auth.urllib.parse.urlencode",
        wraps=urllib.parse.urlencode,
    )
    @patch("googleapiclient.discovery.build")
    async def test_query_omits_customer_id_when_not_set(
        self,
        mock_build,
        mock_urlencode,
        client_id,
        mock_google_credentials,
        mock_cloud_identity_service,
        sample_groups,
    ):
        """Test that the API query omits parent filter when customer_id is None."""
        mock_build.return_value = mock_cloud_identity_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            # No customer_id set
        )

        await backend._fetch_user_groups("user@example.com")

        # Verify urlencode was called with a query NOT containing parent filter
        call_args = mock_urlencode.call_args[0][0]
        assert "parent ==" not in call_args["query"]

    def test_customer_id_stored_on_backend(self, client_id):
        """Test that customer_id is stored as an attribute."""
        backend = WorkspaceAuthBackend(
            client_id=client_id, fetch_groups=False, customer_id="C12345"
        )
        assert backend.customer_id == "C12345"

    def test_customer_id_defaults_to_none(self, client_id):
        """Test that customer_id defaults to None."""
        backend = WorkspaceAuthBackend(client_id=client_id, fetch_groups=False)
        assert backend.customer_id is None
