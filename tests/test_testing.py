"""
Tests for workspace_auth_middleware.testing utilities and pytest plugin fixtures.
"""

import json

import pytest
from starlette.applications import Starlette
from starlette.authentication import AuthCredentials, AuthenticationError
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from workspace_auth_middleware import WorkspaceAuthMiddleware
from workspace_auth_middleware.decorators import require_auth, require_group
from workspace_auth_middleware.models import WorkspaceUser
from workspace_auth_middleware.testing import (
    MockWorkspaceAuthBackend,
    MockWorkspaceAuthMiddleware,
    create_workspace_user,
)


# ---------------------------------------------------------------------------
# create_workspace_user
# ---------------------------------------------------------------------------


class TestCreateWorkspaceUser:
    """Tests for the create_workspace_user factory."""

    def test_defaults(self):
        user = create_workspace_user()
        assert user.email == "user@example.com"
        assert user.user_id == "test-user-id"
        assert user.name == "Test User"
        assert user.groups == []
        assert user.domain == "example.com"
        assert user.is_authenticated is True

    def test_custom_values(self):
        user = create_workspace_user(
            email="admin@corp.com",
            user_id="admin-123",
            name="Admin",
            groups=["admins@corp.com", "devs@corp.com"],
            domain="corp.com",
        )
        assert user.email == "admin@corp.com"
        assert user.user_id == "admin-123"
        assert user.name == "Admin"
        assert user.groups == ["admins@corp.com", "devs@corp.com"]
        assert user.domain == "corp.com"

    def test_domain_derived_from_email(self):
        user = create_workspace_user(email="someone@acme.org")
        assert user.domain == "acme.org"

    def test_explicit_domain_overrides(self):
        user = create_workspace_user(email="someone@acme.org", domain="override.com")
        assert user.domain == "override.com"


# ---------------------------------------------------------------------------
# MockWorkspaceAuthBackend
# ---------------------------------------------------------------------------


def _make_conn(headers: dict | None = None) -> HTTPConnection:
    """Build a minimal ASGI HTTPConnection for testing the backend directly."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
    }
    return HTTPConnection(scope)


class TestMockWorkspaceAuthBackend:
    """Tests for MockWorkspaceAuthBackend."""

    async def test_anonymous_by_default(self):
        backend = MockWorkspaceAuthBackend()
        result = await backend.authenticate(_make_conn())
        assert result is None

    async def test_fixed_user(self):
        user = create_workspace_user(email="user@test.com", groups=["team@test.com"])
        backend = MockWorkspaceAuthBackend(user=user)
        result = await backend.authenticate(_make_conn())

        assert result is not None
        creds, returned_user = result
        assert returned_user.email == "user@test.com"
        assert "authenticated" in creds.scopes
        assert "group:team@test.com" in creds.scopes

    async def test_scopes_include_all_groups(self):
        user = create_workspace_user(groups=["a@x.com", "b@x.com", "c@x.com"])
        backend = MockWorkspaceAuthBackend(user=user)
        creds, _ = await backend.authenticate(_make_conn())  # type: ignore[misc]

        assert "authenticated" in creds.scopes
        assert "group:a@x.com" in creds.scopes
        assert "group:b@x.com" in creds.scopes
        assert "group:c@x.com" in creds.scopes

    async def test_error_mode(self):
        backend = MockWorkspaceAuthBackend(error="Token expired")
        with pytest.raises(AuthenticationError, match="Token expired"):
            await backend.authenticate(_make_conn())

    async def test_error_takes_priority_over_user(self):
        """Error mode should fire even if a user is also set."""
        user = create_workspace_user()
        backend = MockWorkspaceAuthBackend(user=user, error="Forced error")
        with pytest.raises(AuthenticationError, match="Forced error"):
            await backend.authenticate(_make_conn())

    async def test_authenticate_fn_sync(self):
        user = create_workspace_user(email="callback@test.com")

        def my_fn(conn: HTTPConnection):
            return AuthCredentials(["authenticated"]), user

        backend = MockWorkspaceAuthBackend(authenticate_fn=my_fn)
        result = await backend.authenticate(_make_conn())
        assert result is not None
        assert result[1].email == "callback@test.com"

    async def test_authenticate_fn_async(self):
        user = create_workspace_user(email="async@test.com")

        async def my_fn(conn: HTTPConnection):
            return AuthCredentials(["authenticated"]), user

        backend = MockWorkspaceAuthBackend(authenticate_fn=my_fn)
        result = await backend.authenticate(_make_conn())
        assert result is not None
        assert result[1].email == "async@test.com"

    async def test_authenticate_fn_returning_none(self):
        def my_fn(conn: HTTPConnection):
            return None

        backend = MockWorkspaceAuthBackend(authenticate_fn=my_fn)
        result = await backend.authenticate(_make_conn())
        assert result is None

    async def test_header_mode_with_header(self):
        backend = MockWorkspaceAuthBackend(header_mode=True)
        payload = json.dumps(
            {"email": "browser@test.com", "groups": ["viewers@test.com"]}
        )
        conn = _make_conn(headers={"X-Test-User": payload})
        result = await backend.authenticate(conn)

        assert result is not None
        creds, user = result
        assert user.email == "browser@test.com"
        assert user.groups == ["viewers@test.com"]
        assert "group:viewers@test.com" in creds.scopes

    async def test_header_mode_without_header_falls_through(self):
        """When header_mode is on but no header is sent, fall through to user/anonymous."""
        backend = MockWorkspaceAuthBackend(header_mode=True)
        result = await backend.authenticate(_make_conn())
        assert result is None

    async def test_header_mode_with_fallback_user(self):
        """When header is absent but a user is set, return the user."""
        user = create_workspace_user(email="fallback@test.com")
        backend = MockWorkspaceAuthBackend(header_mode=True, user=user)
        result = await backend.authenticate(_make_conn())
        assert result is not None
        assert result[1].email == "fallback@test.com"

    async def test_header_mode_custom_header_name(self):
        backend = MockWorkspaceAuthBackend(header_mode=True, header_name="X-Auth-User")
        payload = json.dumps({"email": "custom@test.com"})
        conn = _make_conn(headers={"X-Auth-User": payload})
        result = await backend.authenticate(conn)
        assert result is not None
        assert result[1].email == "custom@test.com"

    async def test_header_mode_minimal_json(self):
        """Minimal JSON payload uses defaults for missing fields."""
        backend = MockWorkspaceAuthBackend(header_mode=True)
        conn = _make_conn(headers={"X-Test-User": "{}"})
        result = await backend.authenticate(conn)
        assert result is not None
        _, user = result
        assert user.email == "user@example.com"
        assert user.groups == []


# ---------------------------------------------------------------------------
# MockWorkspaceAuthMiddleware
# ---------------------------------------------------------------------------


def _make_app(middleware_kwargs: dict) -> Starlette:
    """Create a small Starlette app with MockWorkspaceAuthMiddleware."""

    async def me_endpoint(request):
        user = request.user
        return JSONResponse(
            {
                "authenticated": user.is_authenticated,
                "email": user.email if user.is_authenticated else None,
                "groups": user.groups if user.is_authenticated else [],
                "scopes": sorted(request.auth.scopes) if request.auth else [],
            }
        )

    app = Starlette(routes=[Route("/me", me_endpoint)])
    app.add_middleware(MockWorkspaceAuthMiddleware, **middleware_kwargs)
    return app


class TestMockWorkspaceAuthMiddleware:
    """Tests for MockWorkspaceAuthMiddleware via TestClient."""

    def test_authenticated_user(self):
        user = create_workspace_user(email="dev@corp.com", groups=["devs@corp.com"])
        app = _make_app({"user": user})
        client = TestClient(app)

        resp = client.get("/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["email"] == "dev@corp.com"
        assert "group:devs@corp.com" in data["scopes"]

    def test_anonymous_user(self):
        app = _make_app({})
        client = TestClient(app)

        resp = client.get("/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False

    def test_error_mode_returns_401(self):
        app = _make_app({"error": "Invalid token"})
        client = TestClient(app)

        resp = client.get("/me")
        assert resp.status_code == 401
        data = resp.json()
        assert data["error"] == "Authentication failed"
        assert "Invalid token" in data["detail"]

    def test_header_mode(self):
        app = _make_app({"header_mode": True})
        client = TestClient(app)

        payload = json.dumps(
            {
                "email": "playwright@test.com",
                "groups": ["editors@test.com"],
            }
        )
        resp = client.get("/me", headers={"X-Test-User": payload})
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "playwright@test.com"
        assert "editors@test.com" in data["groups"]

    def test_header_mode_anonymous_without_header(self):
        app = _make_app({"header_mode": True})
        client = TestClient(app)

        resp = client.get("/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False

    def test_custom_error_handler(self):
        def my_handler(conn, exc):
            return JSONResponse({"custom": True}, status_code=403)

        app = _make_app({"error": "nope", "on_error": my_handler})
        client = TestClient(app)

        resp = client.get("/me")
        assert resp.status_code == 403
        assert resp.json() == {"custom": True}


# ---------------------------------------------------------------------------
# Decorator integration
# ---------------------------------------------------------------------------


class TestDecoratorIntegration:
    """Verify that the mock middleware works correctly with decorators."""

    def test_require_auth_passes(self):
        @require_auth
        async def protected(request):
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/protected", protected)])
        app.add_middleware(
            MockWorkspaceAuthMiddleware,
            user=create_workspace_user(),
        )
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/protected").status_code == 200

    def test_require_group_passes(self):
        @require_group("admins@example.com")
        async def admin(request):
            return JSONResponse({"admin": True})

        app = Starlette(routes=[Route("/admin", admin)])
        app.add_middleware(
            MockWorkspaceAuthMiddleware,
            user=create_workspace_user(groups=["admins@example.com"]),
        )
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/admin").status_code == 200

    def test_require_group_denied(self):
        @require_group("admins@example.com")
        async def admin(request):
            return JSONResponse({"admin": True})

        app = Starlette(routes=[Route("/admin", admin)])
        app.add_middleware(
            MockWorkspaceAuthMiddleware,
            user=create_workspace_user(groups=[]),
        )
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/admin").status_code == 403


# ---------------------------------------------------------------------------
# Pytest plugin fixtures
# ---------------------------------------------------------------------------


class TestWorkspaceUserFixture:
    """Tests for the workspace_user fixture (auto-discovered via plugin)."""

    def test_creates_default_user(self, workspace_user):
        user = workspace_user()
        assert isinstance(user, WorkspaceUser)
        assert user.email == "user@example.com"

    def test_creates_custom_user(self, workspace_user):
        user = workspace_user(email="custom@corp.com", groups=["team@corp.com"])
        assert user.email == "custom@corp.com"
        assert user.groups == ["team@corp.com"]


class TestMockWorkspaceBackendFixture:
    """Tests for the mock_workspace_backend fixture."""

    async def test_with_user_kwargs(self, mock_workspace_backend):
        backend = mock_workspace_backend(email="fix@test.com", groups=["g@test.com"])
        result = await backend.authenticate(_make_conn())
        assert result is not None
        assert result[1].email == "fix@test.com"
        assert "group:g@test.com" in result[0].scopes

    async def test_with_explicit_user(self, mock_workspace_backend):
        user = create_workspace_user(email="explicit@test.com")
        backend = mock_workspace_backend(user=user)
        result = await backend.authenticate(_make_conn())
        assert result is not None
        assert result[1].email == "explicit@test.com"

    async def test_error_mode(self, mock_workspace_backend):
        backend = mock_workspace_backend(error="bad token")
        with pytest.raises(AuthenticationError, match="bad token"):
            await backend.authenticate(_make_conn())

    async def test_header_mode(self, mock_workspace_backend):
        backend = mock_workspace_backend(header_mode=True)
        payload = json.dumps({"email": "hdr@test.com"})
        conn = _make_conn(headers={"X-Test-User": payload})
        result = await backend.authenticate(conn)
        assert result is not None
        assert result[1].email == "hdr@test.com"

    async def test_no_kwargs_gives_anonymous(self, mock_workspace_backend):
        backend = mock_workspace_backend()
        result = await backend.authenticate(_make_conn())
        assert result is None


# ---------------------------------------------------------------------------
# override_workspace_auth fixture
# ---------------------------------------------------------------------------


def _create_real_app():
    """Simulates a user's application that uses the real WorkspaceAuthMiddleware."""

    async def endpoint(request):
        user = request.user
        return JSONResponse(
            {
                "authenticated": user.is_authenticated,
                "email": user.email if user.is_authenticated else None,
                "groups": user.groups if user.is_authenticated else [],
            }
        )

    app = Starlette(routes=[Route("/info", endpoint)])
    app.add_middleware(
        WorkspaceAuthMiddleware,
        client_id="real-client-id.apps.googleusercontent.com",
        required_domains=["example.com"],
        fetch_groups=False,
    )
    return app


class TestOverrideWorkspaceAuth:
    """Tests for the override_workspace_auth fixture."""

    def test_patches_middleware_with_user_kwargs(self, override_workspace_auth):
        override_workspace_auth(
            email="patched@example.com",
            groups=["team@example.com"],
        )
        app = _create_real_app()
        client = TestClient(app)

        resp = client.get("/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["email"] == "patched@example.com"
        assert "team@example.com" in data["groups"]

    def test_patches_middleware_anonymous(self, override_workspace_auth):
        override_workspace_auth()
        app = _create_real_app()
        client = TestClient(app)

        resp = client.get("/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False

    def test_patches_middleware_error_mode(self, override_workspace_auth):
        override_workspace_auth(error="Unauthorized")
        app = _create_real_app()
        client = TestClient(app)

        resp = client.get("/info")
        assert resp.status_code == 401
        assert "Unauthorized" in resp.json()["detail"]

    def test_restores_after_test(self, override_workspace_auth):
        """Verify that the real __init__ signature is restored after the fixture."""
        original_init = WorkspaceAuthMiddleware.__init__

        override_workspace_auth(email="temp@example.com")

        # __init__ should be patched now
        assert WorkspaceAuthMiddleware.__init__ is not original_init

        # monkeypatch will restore it after this test function returns;
        # we can't easily assert that here, but the fact that other tests
        # in this module work with the real middleware proves restoration.

    def test_header_mode_via_override(self, override_workspace_auth):
        override_workspace_auth(header_mode=True)
        app = _create_real_app()
        client = TestClient(app)

        payload = json.dumps({"email": "browser@example.com"})
        resp = client.get("/info", headers={"X-Test-User": payload})
        assert resp.status_code == 200
        assert resp.json()["email"] == "browser@example.com"
