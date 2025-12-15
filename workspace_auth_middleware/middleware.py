"""
Middleware utilities for Google Workspace authentication.

This module provides convenience wrappers around Starlette's AuthenticationMiddleware
with Google Workspace-specific configuration.
"""

import typing

import google.auth.credentials
import starlette.middleware.authentication
import starlette.authentication
import starlette.requests
import starlette.responses

from .auth import WorkspaceAuthBackend

__all__ = [
    "WorkspaceAuthMiddleware",
    "default_on_error",
]


class WorkspaceAuthMiddleware(
    starlette.middleware.authentication.AuthenticationMiddleware
):
    """
    Convenience wrapper for Starlette's AuthenticationMiddleware with Google Workspace backend.

    This is a drop-in replacement that automatically configures Starlette's AuthenticationMiddleware
    with the WorkspaceAuthBackend. It provides the same functionality as using
    AuthenticationMiddleware directly but with a simpler interface.

    The middleware:
    1. Intercepts all HTTP requests
    2. Extracts and validates Google OAuth2 tokens from Authorization header
    3. Populates request.user and request.auth
    4. Handles authentication errors with configurable error handler

    Usage with FastAPI:
        ```python
        from fastapi import FastAPI
        from workspace_auth_middleware import WorkspaceAuthMiddleware

        app = FastAPI()

        app.add_middleware(
            WorkspaceAuthMiddleware,
            client_id="your-google-client-id.apps.googleusercontent.com",
            required_domains=["example.com"],
            fetch_groups=True,
        )
        ```

    Usage with Starlette:
        ```python
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from workspace_auth_middleware import WorkspaceAuthMiddleware

        middleware = [
            Middleware(
                WorkspaceAuthMiddleware,
                client_id="your-client-id.apps.googleusercontent.com",
                required_domains=["example.com"],
            )
        ]

        app = Starlette(routes=routes, middleware=middleware)
        ```

    Alternative: Use Starlette's AuthenticationMiddleware directly:
        ```python
        from starlette.middleware.authentication import AuthenticationMiddleware
        from workspace_auth_middleware import WorkspaceAuthBackend

        backend = WorkspaceAuthBackend(
            client_id="your-client-id.apps.googleusercontent.com",
            required_domains=["example.com"],
        )

        app.add_middleware(AuthenticationMiddleware, backend=backend)
        ```

    Args:
        app: The ASGI application to wrap
        client_id: Google OAuth2 client ID
        required_domains: Optional list of allowed Google Workspace domains (e.g., ["example.com", "partner.com"]).
                         If specified, only users from these domains will be allowed.
                         If None, users from any domain are allowed.
        fetch_groups: If True, fetch user's group memberships using Cloud Identity API
        credentials: Google credentials for Cloud Identity API. If None, uses default credentials
        on_error: Optional custom error handler (Request, AuthenticationError) -> Response
    """

    def __init__(
        self,
        app: typing.Callable,
        client_id: str,
        required_domains: typing.Optional[typing.List[str]] = None,
        fetch_groups: bool = True,
        credentials: typing.Optional[google.auth.credentials.Credentials] = None,
        on_error: typing.Optional[
            typing.Callable[
                [
                    starlette.requests.HTTPConnection,
                    starlette.authentication.AuthenticationError,
                ],
                starlette.responses.Response,
            ]
        ] = None,
    ):
        # Create the backend
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=fetch_groups,
            credentials=credentials,
        )

        # Use custom error handler or default
        error_handler = on_error or default_on_error

        # Initialize parent AuthenticationMiddleware
        super().__init__(app, backend=backend, on_error=error_handler)


def default_on_error(
    conn: starlette.requests.HTTPConnection,
    exc: starlette.authentication.AuthenticationError,
) -> starlette.responses.JSONResponse:
    """
    Default error handler for authentication failures.

    Sends a 401 Unauthorized response with JSON error message.

    Args:
        conn: Starlette Request object
        exc: The authentication error that occurred

    Returns:
        JSONResponse with error details
    """
    return starlette.responses.JSONResponse(
        {
            "error": "Authentication failed",
            "detail": str(exc),
        },
        status_code=401,
        headers={"WWW-Authenticate": 'Bearer realm="Google Workspace"'},
    )


def custom_error_handler_example(
    conn: starlette.requests.HTTPConnection,
    exc: starlette.authentication.AuthenticationError,
) -> starlette.responses.JSONResponse:
    """
    Example custom error handler.

    You can create your own error handler following this signature.
    The handler should return a Starlette Response object.

    Example:
        ```python
        from starlette.responses import JSONResponse, PlainTextResponse
        from starlette.authentication import AuthenticationError

        def my_error_handler(conn, exc):
            return PlainTextResponse(
                "Access denied",
                status_code=403,
            )

        app.add_middleware(
            WorkspaceAuthMiddleware,
            client_id="...",
            on_error=my_error_handler,
        )
        ```
    """
    return starlette.responses.JSONResponse(
        {"error": "Custom error", "message": str(exc)},
        status_code=403,
    )
