"""
Tests for WorkspaceAuthBackend authentication functionality.
"""

import hashlib

import pytest
import google.auth.credentials
from unittest.mock import Mock, MagicMock, patch
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

        with pytest.raises(AuthenticationError, match="Domain not allowed"):
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
    async def test_service_built_once_and_reused(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_cloud_identity_service,
        sample_groups,
    ):
        """Test that discovery.build is called once and the service is reused."""
        mock_build.return_value = mock_cloud_identity_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            enable_group_cache=False,
        )

        await backend._fetch_user_groups("user1@example.com")
        await backend._fetch_user_groups("user2@example.com")

        # discovery.build should only be called once
        mock_build.assert_called_once()

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

    @patch("googleapiclient.discovery.build")
    async def test_query_includes_customer_id_when_set(
        self,
        mock_build,
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

        # Verify searchTransitiveGroups was called with query containing parent filter
        call_kwargs = (
            mock_cloud_identity_service.groups()
            .memberships()
            .searchTransitiveGroups.call_args
        )
        assert "parent == 'customers/C028qv0z5'" in call_kwargs.kwargs["query"]

    @patch("googleapiclient.discovery.build")
    async def test_query_omits_customer_id_when_not_set(
        self,
        mock_build,
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

        # Verify searchTransitiveGroups was called with query NOT containing parent filter
        call_kwargs = (
            mock_cloud_identity_service.groups()
            .memberships()
            .searchTransitiveGroups.call_args
        )
        assert "parent ==" not in call_kwargs.kwargs["query"]

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


@pytest.mark.asyncio
class TestTokenCacheHashing:
    """Tests for token cache key hashing (Item 5: avoid storing raw JWTs)."""

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_cache_keys_are_hashed(
        self,
        mock_verify,
        client_id,
        required_domains,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test that token cache keys are SHA-256 hashes, not raw tokens."""
        mock_verify.return_value = valid_id_token_claims

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
            enable_token_cache=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        await backend.authenticate(conn)

        # The raw token must NOT be a cache key
        assert mock_id_token not in backend._token_cache

        # The SHA-256 hash of the token MUST be the cache key
        expected_key = hashlib.sha256(mock_id_token.encode()).hexdigest()
        assert expected_key in backend._token_cache

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_invalidate_token_uses_hash(
        self,
        mock_verify,
        client_id,
        required_domains,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test that invalidate_token hashes the token before lookup."""
        mock_verify.return_value = valid_id_token_claims

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
            enable_token_cache=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        await backend.authenticate(conn)
        assert len(backend._token_cache) == 1

        result = backend.invalidate_token(mock_id_token)
        assert result is True
        assert len(backend._token_cache) == 0


@pytest.mark.asyncio
class TestEmailValidation:
    """Tests for email validation before Cloud Identity query (Item 6)."""

    async def test_invalid_email_returns_empty_groups(
        self, client_id, mock_google_credentials
    ):
        """Test that an email with injection characters returns empty groups."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
        )

        # Email with single-quote injection attempt
        groups = backend._fetch_groups_sync(
            mock_google_credentials, "user'@example.com"
        )
        assert groups == []

    async def test_valid_email_is_not_rejected(
        self, client_id, mock_google_credentials, mock_cloud_identity_service
    ):
        """Test that a normal email passes validation."""
        with patch("googleapiclient.discovery.build") as mock_build:
            mock_build.return_value = mock_cloud_identity_service

            backend = WorkspaceAuthBackend(
                client_id=client_id,
                credentials=mock_google_credentials,
                fetch_groups=True,
            )

            groups = await backend._fetch_user_groups("user@example.com")
            # Should not be empty (validation passed, mock returns groups)
            assert len(groups) > 0


@pytest.mark.asyncio
class TestSessionAuthentication:
    """Tests for session-based authentication."""

    async def test_session_auth_valid_user(self, client_id, required_domains):
        """Test session auth succeeds with valid session data."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}  # No Authorization header
        conn.session = {
            "user": {
                "email": "user@example.com",
                "user_id": "12345",
                "name": "Test User",
                "domain": "example.com",
                "groups": ["admins@example.com"],
            }
        }

        result = await backend.authenticate(conn)
        assert result is not None
        credentials, user = result
        assert user.email == "user@example.com"
        assert user.user_id == "12345"
        assert user.groups == ["admins@example.com"]
        assert "authenticated" in credentials.scopes
        assert "group:admins@example.com" in credentials.scopes

    async def test_session_auth_missing_email(self, client_id):
        """Test session auth returns None when email is missing."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=False,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}
        conn.session = {"user": {"user_id": "12345"}}

        result = await backend.authenticate(conn)
        assert result is None

    async def test_session_auth_missing_user_id(self, client_id):
        """Test session auth returns None when user_id is missing."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=False,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}
        conn.session = {"user": {"email": "user@example.com"}}

        result = await backend.authenticate(conn)
        assert result is None

    async def test_session_auth_wrong_domain(self, client_id):
        """Test session auth rejects users from wrong domain."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=["allowed.com"],
            fetch_groups=False,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}
        conn.session = {
            "user": {
                "email": "user@other.com",
                "user_id": "12345",
            }
        }

        result = await backend.authenticate(conn)
        assert result is None

    async def test_session_auth_disabled(self, client_id):
        """Test that session auth is skipped when disabled."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=False,
            enable_session_auth=False,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}
        conn.session = {
            "user": {
                "email": "user@example.com",
                "user_id": "12345",
            }
        }

        # Should return None (anonymous) — session not checked
        result = await backend.authenticate(conn)
        assert result is None

    async def test_session_auth_no_session_middleware(self, client_id):
        """Test graceful handling when SessionMiddleware is not installed."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=False,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}
        # Starlette raises AssertionError when session is accessed without SessionMiddleware
        type(conn).session = property(
            lambda self: (_ for _ in ()).throw(
                AssertionError("SessionMiddleware not installed")
            )
        )

        result = await backend.authenticate(conn)
        assert result is None

    async def test_session_auth_non_dict_groups(self, client_id):
        """Test session auth handles non-list groups gracefully."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=False,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}
        conn.session = {
            "user": {
                "email": "user@example.com",
                "user_id": "12345",
                "groups": "not-a-list",
            }
        }

        result = await backend.authenticate(conn)
        assert result is not None
        _, user = result
        assert user.groups == []

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_session_takes_priority_over_bearer(
        self,
        mock_verify,
        client_id,
        required_domains,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test that session auth is tried before bearer token when both are present."""
        mock_verify.return_value = valid_id_token_claims

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}
        conn.session = {
            "user": {
                "email": "session-user@example.com",
                "user_id": "session-id",
            }
        }

        credentials, user = await backend.authenticate(conn)
        # Session user should win
        assert user.email == "session-user@example.com"
        # Bearer token should NOT have been verified
        mock_verify.assert_not_called()

    @patch.object(WorkspaceAuthBackend, "_fetch_user_groups")
    async def test_session_auth_fetches_groups_when_enabled(
        self, mock_fetch_groups, client_id, required_domains, sample_groups
    ):
        """Test that fetch_groups=True fetches groups from API for session users."""
        mock_fetch_groups.return_value = sample_groups

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=True,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}
        conn.session = {
            "user": {
                "email": "user@example.com",
                "user_id": "12345",
                "name": "Test User",
                "domain": "example.com",
                "groups": [],
            }
        }

        credentials, user = await backend.authenticate(conn)

        mock_fetch_groups.assert_called_once_with("user@example.com")
        assert user.groups == sample_groups
        assert "authenticated" in credentials.scopes
        for group in sample_groups:
            assert f"group:{group}" in credentials.scopes

    @patch.object(WorkspaceAuthBackend, "_fetch_user_groups")
    async def test_session_auth_ignores_session_groups_when_fetch_enabled(
        self, mock_fetch_groups, client_id, required_domains
    ):
        """Test that API groups override stale session groups when fetch_groups=True."""
        api_groups = ["new-group@example.com"]
        mock_fetch_groups.return_value = api_groups

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=True,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}
        conn.session = {
            "user": {
                "email": "user@example.com",
                "user_id": "12345",
                "name": "Test User",
                "domain": "example.com",
                "groups": ["stale-group@example.com"],
            }
        }

        credentials, user = await backend.authenticate(conn)

        assert user.groups == api_groups
        assert "group:new-group@example.com" in credentials.scopes
        assert "group:stale-group@example.com" not in credentials.scopes

    async def test_session_auth_uses_session_groups_when_fetch_disabled(
        self, client_id, required_domains
    ):
        """Test that session groups are preserved when fetch_groups=False."""
        session_groups = ["admins@example.com"]

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}
        conn.session = {
            "user": {
                "email": "user@example.com",
                "user_id": "12345",
                "name": "Test User",
                "domain": "example.com",
                "groups": session_groups,
            }
        }

        credentials, user = await backend.authenticate(conn)

        assert user.groups == session_groups
        assert "group:admins@example.com" in credentials.scopes

    @patch.object(WorkspaceAuthBackend, "_fetch_user_groups")
    async def test_session_auth_group_fetch_failure_returns_empty_groups(
        self, mock_fetch_groups, client_id, required_domains
    ):
        """Test that user is still authenticated when group fetch returns empty."""
        mock_fetch_groups.return_value = []

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=True,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}
        conn.session = {
            "user": {
                "email": "user@example.com",
                "user_id": "12345",
                "name": "Test User",
                "domain": "example.com",
            }
        }

        credentials, user = await backend.authenticate(conn)

        assert user.is_authenticated
        assert user.groups == []
        assert "authenticated" in credentials.scopes
        assert len(credentials.scopes) == 1

    @patch.object(WorkspaceAuthBackend, "_fetch_user_groups")
    async def test_session_auth_with_groups_preserves_user_fields(
        self, mock_fetch_groups, client_id, required_domains, sample_groups
    ):
        """Test that rebuilding user for groups preserves all session fields."""
        mock_fetch_groups.return_value = sample_groups

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=True,
            enable_session_auth=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {}
        conn.session = {
            "user": {
                "email": "user@example.com",
                "user_id": "12345",
                "name": "Test User",
                "domain": "example.com",
                "groups": [],
            }
        }

        credentials, user = await backend.authenticate(conn)

        assert user.email == "user@example.com"
        assert user.user_id == "12345"
        assert user.name == "Test User"
        assert user.domain == "example.com"
        assert user.groups == sample_groups


@pytest.mark.asyncio
class TestCacheBehavior:
    """Tests for cache stats, invalidation, and disabled cache behavior."""

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_cache_stats_track_hits_and_misses(
        self,
        mock_verify,
        client_id,
        required_domains,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test that get_cache_stats accurately reports hits and misses."""
        mock_verify.return_value = valid_id_token_claims

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
            enable_token_cache=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        # First call: cache miss
        await backend.authenticate(conn)
        # Second call: cache hit
        await backend.authenticate(conn)

        stats = backend.get_cache_stats()
        assert stats["token_cache"]["hits"] == 1
        assert stats["token_cache"]["misses"] == 1
        assert stats["token_cache"]["hit_rate"] == 0.5
        assert stats["token_cache"]["size"] == 1

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_clear_caches_resets_stats(
        self,
        mock_verify,
        client_id,
        required_domains,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test that clear_caches empties cache and resets stats."""
        mock_verify.return_value = valid_id_token_claims

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
            enable_token_cache=True,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        await backend.authenticate(conn)
        assert len(backend._token_cache) == 1

        backend.clear_caches()

        stats = backend.get_cache_stats()
        assert stats["token_cache"]["hits"] == 0
        assert stats["token_cache"]["misses"] == 0
        assert stats["token_cache"]["size"] == 0

    def test_cache_disabled_stats(self, client_id):
        """Test stats report disabled when caches are off."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=False,
            enable_token_cache=False,
            enable_group_cache=False,
        )

        stats = backend.get_cache_stats()
        assert stats["token_cache"] == {"enabled": False}
        assert stats["group_cache"] == {"enabled": False}

    def test_invalidate_nonexistent_token(self, client_id):
        """Test invalidating a token not in cache returns False."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=False,
            enable_token_cache=True,
        )

        result = backend.invalidate_token("nonexistent-token")
        assert result is False

    def test_invalidate_nonexistent_user_groups(self, client_id):
        """Test invalidating groups for a user not in cache returns False."""
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=False,
            enable_group_cache=True,
        )

        result = backend.invalidate_user_groups("nobody@example.com")
        assert result is False

    @patch("googleapiclient.discovery.build")
    async def test_group_cache_hit(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_cloud_identity_service,
        sample_groups,
    ):
        """Test that group cache returns cached results on second call."""
        mock_build.return_value = mock_cloud_identity_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            enable_group_cache=True,
        )

        # First call: cache miss, hits API
        groups1 = await backend._fetch_user_groups("user@example.com")
        # Second call: cache hit, no API call
        groups2 = await backend._fetch_user_groups("user@example.com")

        assert groups1 == sample_groups
        assert groups2 == sample_groups

        stats = backend.get_cache_stats()
        assert stats["group_cache"]["hits"] == 1
        assert stats["group_cache"]["misses"] == 1

    @patch("googleapiclient.discovery.build")
    async def test_invalidate_user_groups_removes_entry(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_cloud_identity_service,
    ):
        """Test that invalidate_user_groups removes the cached entry."""
        mock_build.return_value = mock_cloud_identity_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            enable_group_cache=True,
        )

        await backend._fetch_user_groups("user@example.com")
        assert backend.invalidate_user_groups("user@example.com") is True
        assert backend.invalidate_user_groups("user@example.com") is False


@pytest.mark.asyncio
class TestMultiClientIdFallback:
    """Tests for multi-client-ID authentication fallback."""

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_second_client_id_succeeds(
        self, mock_verify, required_domains, valid_id_token_claims, mock_id_token
    ):
        """Test that auth succeeds when first client_id fails but second succeeds."""

        def verify_side_effect(token, request, audience):
            if audience == "wrong-id":
                raise ValueError("Token audience mismatch")
            return valid_id_token_claims

        mock_verify.side_effect = verify_side_effect

        backend = WorkspaceAuthBackend(
            client_id=["wrong-id", "test-client-id.apps.googleusercontent.com"],
            required_domains=required_domains,
            fetch_groups=False,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        credentials, user = await backend.authenticate(conn)
        assert user.email == "user@example.com"
        assert mock_verify.call_count == 2

    @patch("google.oauth2.id_token.verify_oauth2_token")
    async def test_all_client_ids_fail(self, mock_verify, mock_id_token):
        """Test that auth fails when all client_ids reject the token."""
        mock_verify.side_effect = ValueError("Token audience mismatch")

        backend = WorkspaceAuthBackend(
            client_id=["bad-id-1", "bad-id-2"],
            fetch_groups=False,
        )

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": f"Bearer {mock_id_token}"}

        with pytest.raises(AuthenticationError, match="Token verification failed"):
            await backend.authenticate(conn)

        assert mock_verify.call_count == 2


@pytest.mark.asyncio
class TestPaginatedGroupResponses:
    """Tests for paginated Cloud Identity API responses."""

    @patch("googleapiclient.discovery.build")
    async def test_paginated_groups_are_collected(
        self, mock_build, client_id, mock_google_credentials
    ):
        """Test that all groups are fetched across multiple pages."""
        service = MagicMock()

        # Page 1: returns groups + nextPageToken
        page1_response = {
            "memberships": [
                {"groupKey": {"id": "group-a@example.com"}},
                {"groupKey": {"id": "group-b@example.com"}},
            ],
            "nextPageToken": "page2token",
        }
        # Page 2: returns more groups, no nextPageToken
        page2_response = {
            "memberships": [
                {"groupKey": {"id": "group-c@example.com"}},
            ],
        }

        execute_mock = MagicMock(side_effect=[page1_response, page2_response])
        service.groups.return_value.memberships.return_value.searchTransitiveGroups.return_value.execute = execute_mock
        mock_build.return_value = service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            enable_group_cache=False,
        )

        groups = await backend._fetch_user_groups("user@example.com")

        assert groups == [
            "group-a@example.com",
            "group-b@example.com",
            "group-c@example.com",
        ]
        assert execute_mock.call_count == 2


@pytest.mark.asyncio
class TestEmptyBearerToken:
    """Tests for edge cases in Authorization header parsing."""

    async def test_bearer_with_empty_token(self, client_id):
        """Test that 'Authorization: Bearer ' with empty token fails gracefully."""
        backend = WorkspaceAuthBackend(client_id=client_id, fetch_groups=False)

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": "Bearer "}

        with pytest.raises(AuthenticationError):
            await backend.authenticate(conn)

    async def test_bearer_with_no_space(self, client_id):
        """Test that 'Authorization: Bearer' with no token fails gracefully."""
        backend = WorkspaceAuthBackend(client_id=client_id, fetch_groups=False)

        conn = Mock(spec=HTTPConnection)
        conn.headers = {"authorization": "Bearer"}

        with pytest.raises(AuthenticationError):
            await backend.authenticate(conn)


@pytest.mark.asyncio
class TestAdminSDKGroupFetching:
    """Tests for Admin SDK Directory API group fetching."""

    @patch("googleapiclient.discovery.build")
    async def test_fetch_direct_groups_via_admin_sdk(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_admin_directory_service,
    ):
        """Test fetching direct groups using Admin SDK."""
        mock_build.return_value = mock_admin_directory_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
        )

        groups = await backend._fetch_user_groups("user@example.com")

        assert "team-a@example.com" in groups
        assert "devs@example.com" in groups
        mock_build.assert_called_once_with(
            "admin",
            "directory_v1",
            credentials=mock_google_credentials,
            cache_discovery=False,
        )

    @patch("googleapiclient.discovery.build")
    async def test_transitive_groups_via_target_groups(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_admin_directory_service_with_nesting,
    ):
        """Test transitive group resolution with target_groups and nesting."""
        mock_build.return_value = mock_admin_directory_service_with_nesting

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
            target_groups=[
                "team-a@example.com",  # direct match
                "all-teams@example.com",  # transitive (contains team-a)
                "unrelated@example.com",  # no match
            ],
        )

        groups = await backend._fetch_user_groups("user@example.com")

        assert "team-a@example.com" in groups
        assert "all-teams@example.com" in groups
        assert "unrelated@example.com" not in groups

    @patch("googleapiclient.discovery.build")
    async def test_admin_sdk_service_reused(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_admin_directory_service,
    ):
        """Test that Admin SDK service is built once and reused."""
        mock_build.return_value = mock_admin_directory_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
            enable_group_cache=False,
        )

        await backend._fetch_user_groups("user1@example.com")
        await backend._fetch_user_groups("user2@example.com")

        mock_build.assert_called_once()

    @patch("googleapiclient.discovery.build")
    async def test_no_delegated_admin_uses_cloud_identity(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_cloud_identity_service,
        sample_groups,
    ):
        """Test that without delegated_admin, Cloud Identity API is used."""
        mock_build.return_value = mock_cloud_identity_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            # No delegated_admin set
        )

        groups = await backend._fetch_user_groups("user@example.com")

        # Should use Cloud Identity path
        assert groups == sample_groups
        mock_build.assert_called_once_with(
            "cloudidentity", "v1", credentials=mock_google_credentials
        )

    @patch("googleapiclient.discovery.build")
    async def test_admin_sdk_without_target_groups_returns_direct_only(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_admin_directory_service,
    ):
        """Test that Admin SDK without target_groups returns only direct groups."""
        mock_build.return_value = mock_admin_directory_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
            # No target_groups
        )

        groups = await backend._fetch_user_groups("user@example.com")

        assert groups == ["team-a@example.com", "devs@example.com"]

    @patch("googleapiclient.discovery.build")
    async def test_admin_sdk_api_error_returns_empty(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
    ):
        """Test that Admin SDK API errors return empty list."""
        service = MagicMock()
        service.groups.return_value.list.return_value.execute.side_effect = Exception(
            "API Error"
        )
        mock_build.return_value = service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
        )

        groups = await backend._fetch_user_groups("user@example.com")
        assert groups == []


@pytest.mark.asyncio
class TestAdminSDKCredentials:
    """Tests for Admin SDK credential configuration."""

    @patch("google.auth.default")
    async def test_delegated_admin_uses_correct_scopes(
        self, mock_default, client_id, mock_google_credentials
    ):
        """Test that delegated_admin triggers Admin SDK scopes."""
        mock_google_credentials.with_subject = Mock(
            return_value=mock_google_credentials
        )
        mock_default.return_value = (mock_google_credentials, "project-id")

        WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=True,
            delegated_admin="admin@example.com",
        )

        mock_default.assert_called_once_with(
            scopes=[
                "https://www.googleapis.com/auth/admin.directory.group.readonly",
                "https://www.googleapis.com/auth/admin.directory.group.member.readonly",
            ]
        )

    @patch("google.auth.default")
    async def test_delegated_admin_calls_with_subject(
        self, mock_default, client_id, mock_google_credentials
    ):
        """Test that with_subject is called with the delegated admin email."""
        mock_google_credentials.with_subject = Mock(
            return_value=mock_google_credentials
        )
        mock_default.return_value = (mock_google_credentials, "project-id")

        WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=True,
            delegated_admin="admin@example.com",
        )

        mock_google_credentials.with_subject.assert_called_once_with(
            "admin@example.com"
        )

    @patch("google.auth.default")
    async def test_compute_engine_creds_raise_error(self, mock_default, client_id):
        """Test that Compute Engine creds without with_subject raise clear error."""
        # Compute Engine creds don't have with_subject
        compute_creds = Mock(spec=google.auth.credentials.Credentials)
        compute_creds.refresh = Mock()
        # Explicitly ensure with_subject doesn't exist
        if hasattr(compute_creds, "with_subject"):
            delattr(compute_creds, "with_subject")
        mock_default.return_value = (compute_creds, "project-id")

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=True,
            delegated_admin="admin@example.com",
        )

        # Should handle gracefully — credentials set to None
        assert backend.credentials is None

    async def test_explicit_creds_bypass_adc(self, client_id, mock_google_credentials):
        """Test that explicit credentials skip ADC loading entirely."""
        with patch("google.auth.default") as mock_default:
            backend = WorkspaceAuthBackend(
                client_id=client_id,
                credentials=mock_google_credentials,
                fetch_groups=True,
                delegated_admin="admin@example.com",
            )

            mock_default.assert_not_called()
            assert backend.credentials == mock_google_credentials


@pytest.mark.asyncio
class TestTargetGroups:
    """Tests for target_groups optimization."""

    @patch("googleapiclient.discovery.build")
    async def test_direct_match_skips_has_member(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_admin_directory_service_with_nesting,
    ):
        """Test that direct group matches don't call hasMember API."""
        mock_build.return_value = mock_admin_directory_service_with_nesting

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
            target_groups=["team-a@example.com", "devs@example.com"],
        )

        groups = await backend._fetch_user_groups("user@example.com")

        # Both are direct groups — hasMember should not be called
        assert "team-a@example.com" in groups
        assert "devs@example.com" in groups
        mock_admin_directory_service_with_nesting.members.return_value.hasMember.assert_not_called()

    @patch("googleapiclient.discovery.build")
    async def test_has_member_for_non_direct_targets(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_admin_directory_service_with_nesting,
    ):
        """Test hasMember resolution for targets not in direct groups."""
        mock_build.return_value = mock_admin_directory_service_with_nesting

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
            target_groups=["all-teams@example.com"],
        )

        groups = await backend._fetch_user_groups("user@example.com")

        assert "all-teams@example.com" in groups

    @patch("googleapiclient.discovery.build")
    async def test_deep_transitive_resolution(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_admin_directory_service_with_nesting,
    ):
        """Test hasMember resolves deep nesting (org -> all-teams -> team-a)."""
        mock_build.return_value = mock_admin_directory_service_with_nesting

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
            target_groups=["org@example.com"],
        )

        groups = await backend._fetch_user_groups("user@example.com")

        # hasMember handles transitive resolution natively
        assert "org@example.com" in groups

    @patch("googleapiclient.discovery.build")
    async def test_has_member_failure_returns_no_match(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
    ):
        """Test that hasMember API errors result in no match for that group."""
        service = MagicMock()

        service.groups.return_value.list.return_value.execute.return_value = {
            "groups": [{"email": "leaf@example.com"}]
        }

        # hasMember raises an error
        def has_member_error(groupKey, memberKey):
            from googleapiclient.errors import HttpError

            resp = MagicMock()
            resp.status = 403
            raise HttpError(resp, b"Not Authorized")

        service.members.return_value.hasMember.side_effect = has_member_error
        mock_build.return_value = service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
            target_groups=["target@example.com"],
        )

        groups = await backend._fetch_user_groups("user@example.com")

        # Should NOT match because hasMember failed
        assert "target@example.com" not in groups

    @patch("googleapiclient.discovery.build")
    async def test_mixed_direct_and_transitive(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_admin_directory_service_with_nesting,
    ):
        """Test mix of direct matches and transitive resolution."""
        mock_build.return_value = mock_admin_directory_service_with_nesting

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
            target_groups=[
                "devs@example.com",  # direct
                "all-teams@example.com",  # transitive
                "unrelated@example.com",  # no match
            ],
        )

        groups = await backend._fetch_user_groups("user@example.com")

        assert "devs@example.com" in groups
        assert "all-teams@example.com" in groups
        assert "unrelated@example.com" not in groups

    @patch("googleapiclient.discovery.build")
    async def test_empty_target_groups_returns_empty(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_admin_directory_service,
    ):
        """Test that empty target_groups list returns empty results."""
        mock_build.return_value = mock_admin_directory_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
            target_groups=[],
        )

        groups = await backend._fetch_user_groups("user@example.com")

        assert groups == []


@pytest.mark.asyncio
class TestTargetGroupsWithCloudIdentity:
    """Tests for target_groups filtering with Cloud Identity API."""

    @patch("googleapiclient.discovery.build")
    async def test_target_groups_filter_cloud_identity_results(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_cloud_identity_service,
        sample_groups,
    ):
        """Test that target_groups filters Cloud Identity results."""
        mock_build.return_value = mock_cloud_identity_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            target_groups=["admins@example.com", "nonexistent@example.com"],
            # No delegated_admin — uses Cloud Identity
        )

        groups = await backend._fetch_user_groups("user@example.com")

        assert groups == ["admins@example.com"]

    @patch("googleapiclient.discovery.build")
    async def test_no_target_groups_returns_all_cloud_identity(
        self,
        mock_build,
        client_id,
        mock_google_credentials,
        mock_cloud_identity_service,
        sample_groups,
    ):
        """Test that without target_groups, all Cloud Identity results are returned."""
        mock_build.return_value = mock_cloud_identity_service

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            credentials=mock_google_credentials,
            fetch_groups=True,
            # No target_groups
        )

        groups = await backend._fetch_user_groups("user@example.com")

        assert groups == sample_groups
