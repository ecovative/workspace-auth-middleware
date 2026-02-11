"""
Test utilities for workspace-auth-middleware.

Provides mock backends and middleware for testing applications that use
Google Workspace authentication without real Google credentials.

Usage with TestClient (unit tests):

    from workspace_auth_middleware.testing import (
        MockWorkspaceAuthMiddleware,
        create_workspace_user,
    )

    app = FastAPI()
    app.add_middleware(MockWorkspaceAuthMiddleware, user=create_workspace_user(
        email="admin@example.com",
        groups=["admins@example.com"],
    ))

Usage with Playwright (browser tests):

    app.add_middleware(MockWorkspaceAuthMiddleware, header_mode=True)
    # Then set X-Test-User header with JSON user data from the browser
"""

import inspect
import json
import typing

import starlette.authentication
import starlette.middleware.authentication
import starlette.requests
import starlette.responses

from .models import WorkspaceUser

__all__ = [
    "MockWorkspaceAuthBackend",
    "MockWorkspaceAuthMiddleware",
    "create_workspace_user",
]


def create_workspace_user(
    email: str = "user@example.com",
    user_id: str = "test-user-id",
    name: str = "Test User",
    groups: typing.Optional[typing.List[str]] = None,
    domain: typing.Optional[str] = None,
) -> WorkspaceUser:
    """
    Factory function to create a WorkspaceUser with sensible defaults.

    Args:
        email: User's email address
        user_id: Google user ID
        name: User's display name
        groups: List of group email addresses
        domain: Google Workspace domain (derived from email if not provided)

    Returns:
        A WorkspaceUser instance
    """
    if domain is None:
        domain = email.split("@")[-1]
    return WorkspaceUser(
        email=email,
        user_id=user_id,
        name=name,
        groups=groups or [],
        domain=domain,
    )


class MockWorkspaceAuthBackend(starlette.authentication.AuthenticationBackend):
    """
    Mock authentication backend for testing.

    Drop-in replacement for WorkspaceAuthBackend that requires no Google
    credentials and makes no API calls.

    Modes of operation (checked in this order):

    1. **error mode**: Always raises AuthenticationError
    2. **authenticate_fn mode**: Calls a custom function per request
    3. **header mode**: Reads user data from a JSON header (for browser tests)
    4. **user mode**: Returns a fixed user for all requests
    5. **anonymous mode**: Returns None (no user set, no header)

    Args:
        user: Default user to return for all requests
        error: If set, always raise AuthenticationError with this message
        authenticate_fn: Custom callback ``(conn) -> (AuthCredentials, WorkspaceUser) | None``.
            Can be sync or async.
        header_mode: If True, read user data from a JSON header
        header_name: Header name to read in header mode (default: ``X-Test-User``)
    """

    def __init__(
        self,
        user: typing.Optional[WorkspaceUser] = None,
        error: typing.Optional[str] = None,
        authenticate_fn: typing.Optional[
            typing.Callable[
                [starlette.requests.HTTPConnection],
                typing.Union[
                    typing.Optional[
                        typing.Tuple[
                            starlette.authentication.AuthCredentials, WorkspaceUser
                        ]
                    ],
                    typing.Awaitable[
                        typing.Optional[
                            typing.Tuple[
                                starlette.authentication.AuthCredentials, WorkspaceUser
                            ]
                        ]
                    ],
                ],
            ]
        ] = None,
        header_mode: bool = False,
        header_name: str = "X-Test-User",
    ):
        self.user = user
        self.error = error
        self.authenticate_fn = authenticate_fn
        self.header_mode = header_mode
        self.header_name = header_name

    async def authenticate(
        self, conn: starlette.requests.HTTPConnection
    ) -> typing.Optional[
        typing.Tuple[starlette.authentication.AuthCredentials, WorkspaceUser]
    ]:
        # 1. Error mode
        if self.error is not None:
            raise starlette.authentication.AuthenticationError(self.error)

        # 2. Custom callback
        if self.authenticate_fn is not None:
            result = self.authenticate_fn(conn)
            if inspect.isawaitable(result):
                result = await result
            return result  # type: ignore[return-value]

        # 3. Header mode
        if self.header_mode:
            header_value = conn.headers.get(self.header_name)
            if header_value is not None:
                user = _user_from_json(header_value)
                return _make_credentials(user), user

        # 4. Fixed user
        if self.user is not None:
            return _make_credentials(self.user), self.user

        # 5. Anonymous
        return None


class MockWorkspaceAuthMiddleware(
    starlette.middleware.authentication.AuthenticationMiddleware,
):
    """
    Mock middleware for testing. Drop-in replacement for WorkspaceAuthMiddleware.

    Wraps Starlette's AuthenticationMiddleware with a MockWorkspaceAuthBackend
    so no Google credentials or API calls are needed.

    Args:
        app: The ASGI application to wrap
        user: Default user to return for all requests
        error: If set, always raise AuthenticationError with this message
        authenticate_fn: Custom per-request callback
        header_mode: If True, read user data from a JSON header
        header_name: Header name to read in header mode
        on_error: Custom error handler; defaults to 401 JSON response
    """

    def __init__(
        self,
        app: typing.Callable,
        user: typing.Optional[WorkspaceUser] = None,
        error: typing.Optional[str] = None,
        authenticate_fn: typing.Optional[typing.Callable] = None,
        header_mode: bool = False,
        header_name: str = "X-Test-User",
        on_error: typing.Optional[typing.Callable] = None,
    ):
        backend = MockWorkspaceAuthBackend(
            user=user,
            error=error,
            authenticate_fn=authenticate_fn,
            header_mode=header_mode,
            header_name=header_name,
        )
        error_handler = on_error or _default_on_error
        super().__init__(app, backend=backend, on_error=error_handler)


def _make_credentials(
    user: WorkspaceUser,
) -> starlette.authentication.AuthCredentials:
    """Build AuthCredentials with auto-calculated scopes from user groups."""
    scopes = ["authenticated"]
    scopes.extend(f"group:{g}" for g in user.groups)
    return starlette.authentication.AuthCredentials(scopes)


def _user_from_json(header_value: str) -> WorkspaceUser:
    """Parse a JSON header value into a WorkspaceUser."""
    data = json.loads(header_value)
    return create_workspace_user(
        email=data.get("email", "user@example.com"),
        user_id=data.get("user_id", "test-user-id"),
        name=data.get("name", data.get("email", "Test User")),
        groups=data.get("groups", []),
        domain=data.get("domain"),
    )


def _default_on_error(
    conn: starlette.requests.HTTPConnection,
    exc: starlette.authentication.AuthenticationError,
) -> starlette.responses.JSONResponse:
    """Default error handler matching the real middleware's behavior."""
    return starlette.responses.JSONResponse(
        {
            "error": "Authentication failed",
            "detail": str(exc),
        },
        status_code=401,
        headers={"WWW-Authenticate": 'Bearer realm="Google Workspace"'},
    )
