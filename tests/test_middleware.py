"""
Tests for WorkspaceAuthMiddleware integration.
"""

import pytest
from unittest.mock import patch
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from workspace_auth_middleware import WorkspaceAuthMiddleware


@pytest.fixture
def test_app(client_id, required_domains):
    """
    Create a test Starlette application with authentication middleware.
    """

    async def public_endpoint(request):
        return JSONResponse({"message": "public"})

    async def protected_endpoint(request):
        user = request.user
        return JSONResponse(
            {
                "email": user.email if user.is_authenticated else None,
                "authenticated": user.is_authenticated,
            }
        )

    async def groups_endpoint(request):
        user = request.user
        return JSONResponse(
            {
                "email": user.email,
                "groups": user.groups if user.is_authenticated else [],
            }
        )

    routes = [
        Route("/public", public_endpoint),
        Route("/protected", protected_endpoint),
        Route("/groups", groups_endpoint),
    ]

    app = Starlette(routes=routes)

    # Add authentication middleware
    app.add_middleware(
        WorkspaceAuthMiddleware,
        client_id=client_id,
        required_domains=required_domains,
        fetch_groups=False,  # Disable for simpler tests
    )

    return app


class TestMiddlewareIntegration:
    """Tests for middleware integration with Starlette."""

    def test_public_endpoint_no_auth(self, test_app):
        """Test that public endpoints work without authentication."""
        client = TestClient(test_app)
        response = client.get("/public")

        assert response.status_code == 200
        assert response.json() == {"message": "public"}

    def test_protected_endpoint_anonymous_user(self, test_app):
        """Test that anonymous users can access endpoints but are not authenticated."""
        client = TestClient(test_app)
        response = client.get("/protected")

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False
        assert data["email"] is None

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_protected_endpoint_with_valid_token(
        self, mock_verify, test_app, valid_id_token_claims, mock_id_token
    ):
        """Test authenticated user can access protected endpoint."""
        mock_verify.return_value = valid_id_token_claims

        client = TestClient(test_app)
        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["email"] == "user@example.com"

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_middleware_invalid_token(self, mock_verify, test_app, mock_id_token):
        """Test middleware returns 401 for invalid tokens."""
        mock_verify.side_effect = Exception("Invalid token")

        client = TestClient(test_app)
        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        assert response.status_code == 401
        data = response.json()
        assert "error" in data
        assert data["error"] == "Authentication failed"

    def test_middleware_wrong_auth_scheme(self, test_app):
        """Test middleware rejects non-Bearer authentication."""
        client = TestClient(test_app)
        response = client.get(
            "/protected", headers={"Authorization": "Basic user:pass"}
        )

        assert response.status_code == 401
        data = response.json()
        assert "error" in data


class TestMiddlewareWithGroups:
    """Tests for middleware with group fetching enabled."""

    @pytest.fixture
    def app_with_groups(self, client_id, required_domains, mock_google_credentials):
        """Create app with group fetching enabled."""

        async def groups_endpoint(request):
            user = request.user
            return JSONResponse(
                {
                    "email": user.email if user.is_authenticated else None,
                    "groups": user.groups if user.is_authenticated else [],
                    "scopes": list(request.auth.scopes) if request.auth else [],
                }
            )

        routes = [Route("/groups", groups_endpoint)]
        app = Starlette(routes=routes)

        app.add_middleware(
            WorkspaceAuthMiddleware,
            client_id=client_id,
            required_domains=required_domains,
            credentials=mock_google_credentials,
            fetch_groups=True,
        )

        return app

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("googleapiclient.discovery.build")
    def test_middleware_with_group_fetching(
        self,
        mock_build,
        mock_verify,
        app_with_groups,
        valid_id_token_claims,
        mock_id_token,
        mock_cloud_identity_service,
        sample_groups,
    ):
        """Test middleware fetches and exposes user groups."""
        mock_verify.return_value = valid_id_token_claims
        mock_build.return_value = mock_cloud_identity_service

        client = TestClient(app_with_groups)
        response = client.get(
            "/groups", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["email"] == "user@example.com"
        assert data["groups"] == sample_groups

        # Check that group scopes were added
        assert "authenticated" in data["scopes"]
        assert "group:admins@example.com" in data["scopes"]
        assert "group:developers@example.com" in data["scopes"]


class TestMiddlewareBackendForwarding:
    """Tests that WorkspaceAuthMiddleware forwards all parameters to the backend."""

    def test_middleware_forwards_cache_params(self, client_id, required_domains):
        """Test that cache parameters are forwarded to the backend."""

        async def endpoint(request):
            return JSONResponse({"message": "ok"})

        app = Starlette(routes=[Route("/test", endpoint)])
        app.add_middleware(
            WorkspaceAuthMiddleware,
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
            enable_token_cache=True,
            token_cache_ttl=120,
            token_cache_maxsize=50,
            enable_group_cache=False,
            group_cache_ttl=60,
            group_cache_maxsize=25,
        )

        # Force middleware stack build
        client = TestClient(app)
        client.get("/test")

        # Access the backend through the middleware stack
        backend = app.middleware_stack.app.backend  # type: ignore[union-attr]
        assert backend.enable_token_cache is True
        assert backend._token_cache is not None
        assert backend._token_cache.maxsize == 50
        assert backend._token_cache.ttl == 120
        assert backend.enable_group_cache is False
        assert backend._group_cache is None

    def test_middleware_accepts_list_of_client_ids(self, required_domains):
        """Test that middleware accepts a list of client IDs."""

        async def endpoint(request):
            return JSONResponse({"message": "ok"})

        app = Starlette(routes=[Route("/test", endpoint)])
        app.add_middleware(
            WorkspaceAuthMiddleware,
            client_id=[
                "id-one.apps.googleusercontent.com",
                "id-two.apps.googleusercontent.com",
            ],
            required_domains=required_domains,
            fetch_groups=False,
        )

        client = TestClient(app)
        client.get("/test")

        backend = app.middleware_stack.app.backend  # type: ignore[union-attr]
        assert backend.client_ids == [
            "id-one.apps.googleusercontent.com",
            "id-two.apps.googleusercontent.com",
        ]

    def test_middleware_forwards_session_auth_param(self, client_id, required_domains):
        """Test that enable_session_auth is forwarded to the backend."""

        async def endpoint(request):
            return JSONResponse({"message": "ok"})

        app = Starlette(routes=[Route("/test", endpoint)])
        app.add_middleware(
            WorkspaceAuthMiddleware,
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
            enable_session_auth=False,
        )

        client = TestClient(app)
        client.get("/test")

        backend = app.middleware_stack.app.backend  # type: ignore[union-attr]
        assert backend.enable_session_auth is False

    def test_middleware_forwards_delegated_admin(
        self, client_id, required_domains, mock_google_credentials
    ):
        """Test that delegated_admin is forwarded to the backend."""

        async def endpoint(request):
            return JSONResponse({"message": "ok"})

        app = Starlette(routes=[Route("/test", endpoint)])
        app.add_middleware(
            WorkspaceAuthMiddleware,
            client_id=client_id,
            required_domains=required_domains,
            credentials=mock_google_credentials,
            fetch_groups=True,
            delegated_admin="admin@example.com",
        )

        client = TestClient(app)
        client.get("/test")

        backend = app.middleware_stack.app.backend  # type: ignore[union-attr]
        assert backend.delegated_admin == "admin@example.com"

    def test_middleware_forwards_target_groups(
        self, client_id, required_domains, mock_google_credentials
    ):
        """Test that target_groups is forwarded to the backend."""

        async def endpoint(request):
            return JSONResponse({"message": "ok"})

        app = Starlette(routes=[Route("/test", endpoint)])
        app.add_middleware(
            WorkspaceAuthMiddleware,
            client_id=client_id,
            required_domains=required_domains,
            credentials=mock_google_credentials,
            fetch_groups=True,
            target_groups=["admins@example.com", "devs@example.com"],
        )

        client = TestClient(app)
        client.get("/test")

        backend = app.middleware_stack.app.backend  # type: ignore[union-attr]
        assert backend.target_groups == ["admins@example.com", "devs@example.com"]


class TestCustomErrorHandler:
    """Tests for custom error handlers."""

    @pytest.fixture
    def app_with_custom_error_handler(self, client_id, required_domains):
        """Create app with custom error handler."""

        def custom_error_handler(conn, exc):
            from starlette.responses import JSONResponse

            return JSONResponse(
                {"custom_error": "Authentication failed", "detail": str(exc)},
                status_code=403,
            )

        async def endpoint(request):
            return JSONResponse({"message": "ok"})

        routes = [Route("/test", endpoint)]
        app = Starlette(routes=routes)

        app.add_middleware(
            WorkspaceAuthMiddleware,
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
            on_error=custom_error_handler,
        )

        return app

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_custom_error_handler_called(
        self, mock_verify, app_with_custom_error_handler, mock_id_token
    ):
        """Test custom error handler is called on authentication failure."""
        mock_verify.side_effect = Exception("Token expired")

        client = TestClient(app_with_custom_error_handler)
        response = client.get(
            "/test", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        assert response.status_code == 403  # Custom status code
        data = response.json()
        assert "custom_error" in data
        assert data["custom_error"] == "Authentication failed"
