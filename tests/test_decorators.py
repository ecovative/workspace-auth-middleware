"""
Tests for authentication and authorization decorators.
"""

import pytest
from unittest.mock import patch, Mock
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.testclient import TestClient
from starlette.authentication import requires

from workspace_auth_middleware import (
    WorkspaceAuthMiddleware,
    require_auth,
    require_group,
)


@pytest.fixture
def app_with_decorators(client_id, required_domains, mock_google_credentials):
    """Create test app with decorated routes."""

    @require_auth
    async def protected_route(request):
        return JSONResponse({"message": "authenticated"})

    @require_group("admins@example.com")
    async def admin_route(request):
        return JSONResponse({"message": "admin access"})

    @require_group(["team-a@example.com", "team-b@example.com"])
    async def multi_group_route(request):
        return JSONResponse({"message": "team access"})

    @require_group(["managers@example.com", "leads@example.com"], require_all=True)
    async def all_groups_route(request):
        return JSONResponse({"message": "restricted access"})

    # Using Starlette's @requires decorator
    @requires("authenticated")
    async def starlette_auth_route(request):
        return JSONResponse({"message": "starlette auth"})

    @requires("group:developers@example.com")
    async def starlette_group_route(request):
        return JSONResponse({"message": "starlette group"})

    routes = [
        Route("/protected", protected_route),
        Route("/admin", admin_route),
        Route("/multi-group", multi_group_route),
        Route("/all-groups", all_groups_route),
        Route("/starlette-auth", starlette_auth_route),
        Route("/starlette-group", starlette_group_route),
    ]

    app = Starlette(routes=routes)

    app.add_middleware(
        WorkspaceAuthMiddleware,
        client_id=client_id,
        required_domains=required_domains,
        credentials=mock_google_credentials,
        delegated_admin="admin@example.com",
        fetch_groups=True,
    )

    return app


class TestRequireAuthDecorator:
    """Tests for @require_auth decorator."""

    def test_require_auth_anonymous_user(self, app_with_decorators):
        """Test @require_auth blocks anonymous users."""
        client = TestClient(app_with_decorators, raise_server_exceptions=False)
        response = client.get("/protected")

        # Should raise PermissionDenied which becomes 500 without error handling
        assert response.status_code == 500

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("googleapiclient.discovery.build")
    def test_require_auth_authenticated_user(
        self,
        mock_build,
        mock_verify,
        app_with_decorators,
        valid_id_token_claims,
        mock_id_token,
        mock_admin_sdk_service,
    ):
        """Test @require_auth allows authenticated users."""
        mock_verify.return_value = valid_id_token_claims
        mock_build.return_value = mock_admin_sdk_service

        client = TestClient(app_with_decorators)
        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        assert response.status_code == 200
        assert response.json() == {"message": "authenticated"}


class TestRequireGroupDecorator:
    """Tests for @require_group decorator."""

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("googleapiclient.discovery.build")
    def test_require_group_user_in_group(
        self,
        mock_build,
        mock_verify,
        app_with_decorators,
        valid_id_token_claims,
        mock_id_token,
        mock_admin_sdk_service,
    ):
        """Test @require_group allows users in the required group."""
        mock_verify.return_value = valid_id_token_claims
        mock_build.return_value = mock_admin_sdk_service

        client = TestClient(app_with_decorators)
        response = client.get(
            "/admin", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        assert response.status_code == 200
        assert response.json() == {"message": "admin access"}

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("googleapiclient.discovery.build")
    def test_require_group_user_not_in_group(
        self,
        mock_build,
        mock_verify,
        app_with_decorators,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test @require_group blocks users not in required group."""
        mock_verify.return_value = valid_id_token_claims

        # Mock empty groups
        mock_service = Mock()
        mock_service.groups().list().execute.return_value = {"groups": []}
        mock_build.return_value = mock_service

        client = TestClient(app_with_decorators, raise_server_exceptions=False)
        response = client.get(
            "/admin", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        # Should raise PermissionDenied
        assert response.status_code == 500

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("googleapiclient.discovery.build")
    def test_require_group_multi_group_any(
        self,
        mock_build,
        mock_verify,
        app_with_decorators,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test @require_group with multiple groups (any match)."""
        mock_verify.return_value = valid_id_token_claims

        # User is only in team-a
        mock_service = Mock()
        mock_service.groups().list().execute.return_value = {
            "groups": [{"email": "team-a@example.com"}]
        }
        mock_build.return_value = mock_service

        client = TestClient(app_with_decorators)
        response = client.get(
            "/multi-group", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        assert response.status_code == 200
        assert response.json() == {"message": "team access"}

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("googleapiclient.discovery.build")
    def test_require_group_multi_group_all(
        self,
        mock_build,
        mock_verify,
        app_with_decorators,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test @require_group with require_all=True."""
        mock_verify.return_value = valid_id_token_claims

        # User has both required groups
        mock_service = Mock()
        mock_service.groups().list().execute.return_value = {
            "groups": [
                {"email": "managers@example.com"},
                {"email": "leads@example.com"},
            ]
        }
        mock_build.return_value = mock_service

        client = TestClient(app_with_decorators)
        response = client.get(
            "/all-groups", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        assert response.status_code == 200
        assert response.json() == {"message": "restricted access"}

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("googleapiclient.discovery.build")
    def test_require_group_multi_group_all_missing_one(
        self,
        mock_build,
        mock_verify,
        app_with_decorators,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test @require_group with require_all=True when user is missing one group."""
        mock_verify.return_value = valid_id_token_claims

        # User only has one of the two required groups
        mock_service = Mock()
        mock_service.groups().list().execute.return_value = {
            "groups": [{"email": "managers@example.com"}]
        }
        mock_build.return_value = mock_service

        client = TestClient(app_with_decorators, raise_server_exceptions=False)
        response = client.get(
            "/all-groups", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        # Should fail because user doesn't have all required groups
        assert response.status_code == 500


class TestStarletteRequiresDecorator:
    """Tests for Starlette's @requires decorator integration."""

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("googleapiclient.discovery.build")
    def test_starlette_requires_authenticated(
        self,
        mock_build,
        mock_verify,
        app_with_decorators,
        valid_id_token_claims,
        mock_id_token,
        mock_admin_sdk_service,
    ):
        """Test Starlette's @requires('authenticated') decorator."""
        mock_verify.return_value = valid_id_token_claims
        mock_build.return_value = mock_admin_sdk_service

        client = TestClient(app_with_decorators)
        response = client.get(
            "/starlette-auth", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        assert response.status_code == 200
        assert response.json() == {"message": "starlette auth"}

    def test_starlette_requires_unauthenticated(self, app_with_decorators):
        """Test Starlette's @requires decorator blocks unauthenticated users."""
        client = TestClient(app_with_decorators)
        response = client.get("/starlette-auth")

        # Starlette returns 403 for failed authorization
        assert response.status_code == 403

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("googleapiclient.discovery.build")
    def test_starlette_requires_group_scope(
        self,
        mock_build,
        mock_verify,
        app_with_decorators,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test Starlette's @requires with group scope."""
        mock_verify.return_value = valid_id_token_claims

        # User is in developers group
        mock_service = Mock()
        mock_service.groups().list().execute.return_value = {
            "groups": [{"email": "developers@example.com"}]
        }
        mock_build.return_value = mock_service

        client = TestClient(app_with_decorators)
        response = client.get(
            "/starlette-group", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        assert response.status_code == 200
        assert response.json() == {"message": "starlette group"}

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("googleapiclient.discovery.build")
    def test_starlette_requires_group_scope_denied(
        self,
        mock_build,
        mock_verify,
        app_with_decorators,
        valid_id_token_claims,
        mock_id_token,
    ):
        """Test Starlette's @requires blocks users without required group scope."""
        mock_verify.return_value = valid_id_token_claims

        # User has no groups
        mock_service = Mock()
        mock_service.groups().list().execute.return_value = {"groups": []}
        mock_build.return_value = mock_service

        client = TestClient(app_with_decorators)
        response = client.get(
            "/starlette-group", headers={"Authorization": f"Bearer {mock_id_token}"}
        )

        # Starlette returns 403 for insufficient permissions
        assert response.status_code == 403
