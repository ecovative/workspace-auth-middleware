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
def test_app(client_id, workspace_domain):
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
        workspace_domain=workspace_domain,
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
    def app_with_groups(self, client_id, workspace_domain, mock_google_credentials):
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
            workspace_domain=workspace_domain,
            credentials=mock_google_credentials,
            delegated_admin="admin@example.com",
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
        mock_admin_sdk_service,
        sample_groups,
    ):
        """Test middleware fetches and exposes user groups."""
        mock_verify.return_value = valid_id_token_claims
        mock_build.return_value = mock_admin_sdk_service

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


class TestCustomErrorHandler:
    """Tests for custom error handlers."""

    @pytest.fixture
    def app_with_custom_error_handler(self, client_id, workspace_domain):
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
            workspace_domain=workspace_domain,
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
