"""
Pytest plugin for workspace-auth-middleware.

Provides auto-discovered fixtures for testing applications that use
Google Workspace authentication. Registered via the ``pytest11`` entry point
so fixtures are available automatically when the package is installed.

Fixtures:
    workspace_user: Factory to create WorkspaceUser instances with defaults
    mock_workspace_backend: Factory to create MockWorkspaceAuthBackend instances
    override_workspace_auth: Monkeypatch WorkspaceAuthMiddleware to use mock backend
"""

import typing

import pytest

from .models import WorkspaceUser

__all__ = [
    "workspace_user",
    "mock_workspace_backend",
    "override_workspace_auth",
]
from .testing import MockWorkspaceAuthBackend, create_workspace_user


@pytest.fixture
def workspace_user() -> typing.Callable[..., WorkspaceUser]:
    """
    Factory fixture that returns ``create_workspace_user``.

    Usage::

        def test_something(workspace_user):
            user = workspace_user(email="admin@corp.com", groups=["admins@corp.com"])
            assert user.email == "admin@corp.com"
    """
    return create_workspace_user


@pytest.fixture
def mock_workspace_backend(
    workspace_user: typing.Callable[..., WorkspaceUser],
) -> typing.Callable[..., MockWorkspaceAuthBackend]:
    """
    Factory fixture that creates a ``MockWorkspaceAuthBackend``.

    Accepts either a pre-built ``user=`` or keyword arguments that are forwarded
    to ``create_workspace_user`` to build one automatically.

    Usage::

        def test_with_user(mock_workspace_backend):
            backend = mock_workspace_backend(email="test@corp.com", groups=["team@corp.com"])

        def test_error_mode(mock_workspace_backend):
            backend = mock_workspace_backend(error="Token expired")

        def test_header_mode(mock_workspace_backend):
            backend = mock_workspace_backend(header_mode=True)
    """

    def _factory(
        user: typing.Optional[WorkspaceUser] = None,
        error: typing.Optional[str] = None,
        authenticate_fn: typing.Optional[typing.Callable[..., typing.Any]] = None,
        header_mode: bool = False,
        header_name: str = "X-Test-User",
        **user_kwargs: typing.Any,
    ) -> MockWorkspaceAuthBackend:
        if user is None and error is None and authenticate_fn is None and user_kwargs:
            user = workspace_user(**user_kwargs)
        return MockWorkspaceAuthBackend(
            user=user,
            error=error,
            authenticate_fn=authenticate_fn,
            header_mode=header_mode,
            header_name=header_name,
        )

    return _factory


@pytest.fixture
def override_workspace_auth(
    monkeypatch: pytest.MonkeyPatch,
    workspace_user: typing.Callable[..., WorkspaceUser],
) -> typing.Callable[..., None]:
    """
    Monkeypatch ``WorkspaceAuthMiddleware.__init__`` so that any app created
    after calling this fixture uses a ``MockWorkspaceAuthBackend`` instead of
    the real backend.

    Automatically restored after the test via monkeypatch.

    Usage::

        def test_protected_route(override_workspace_auth):
            override_workspace_auth(email="user@example.com")
            app = create_my_app()  # uses WorkspaceAuthMiddleware internally
            client = TestClient(app)
            assert client.get("/protected").status_code == 200

        def test_admin_route(override_workspace_auth):
            override_workspace_auth(
                email="admin@example.com",
                groups=["admins@example.com"],
            )
            app = create_my_app()
            client = TestClient(app)
            assert client.get("/admin").status_code == 200
    """
    from .middleware import WorkspaceAuthMiddleware, default_on_error

    def _apply(
        user: typing.Optional[WorkspaceUser] = None,
        error: typing.Optional[str] = None,
        authenticate_fn: typing.Optional[typing.Callable[..., typing.Any]] = None,
        header_mode: bool = False,
        header_name: str = "X-Test-User",
        **user_kwargs: typing.Any,
    ) -> None:
        if user is None and error is None and authenticate_fn is None and user_kwargs:
            user = workspace_user(**user_kwargs)

        mock_backend = MockWorkspaceAuthBackend(
            user=user,
            error=error,
            authenticate_fn=authenticate_fn,
            header_mode=header_mode,
            header_name=header_name,
        )

        def patched_init(
            self: typing.Any,
            app: typing.Callable[..., typing.Any],
            on_error: typing.Optional[typing.Callable[..., typing.Any]] = None,
            **_kwargs: typing.Any,
        ) -> None:
            error_handler = on_error or default_on_error
            starlette_init = (
                starlette.middleware.authentication.AuthenticationMiddleware.__init__
            )
            starlette_init(self, app, backend=mock_backend, on_error=error_handler)

        monkeypatch.setattr(WorkspaceAuthMiddleware, "__init__", patched_init)

    # Need this import at function scope for the patched_init closure
    import starlette.middleware.authentication  # noqa: F811

    return _apply
