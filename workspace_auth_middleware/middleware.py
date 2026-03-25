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
        client_id: Google OAuth2 client ID or list of client IDs for multi-client validation
        required_domains: Optional list of allowed Google Workspace domains (e.g., ["example.com", "partner.com"]).
                         If specified, only users from these domains will be allowed.
                         If None, users from any domain are allowed.
        fetch_groups: If True, fetch user's group memberships using Cloud Identity API
        credentials: Google credentials for Cloud Identity API. If None, uses default credentials
        customer_id: Optional Google Workspace customer ID for group queries
        enable_token_cache: Enable caching of verified tokens (default: True)
        token_cache_ttl: Token cache time-to-live in seconds (default: 300)
        token_cache_maxsize: Maximum number of cached tokens (default: 1000)
        enable_group_cache: Enable caching of group memberships (default: True)
        group_cache_ttl: Group cache time-to-live in seconds (default: 300)
        group_cache_maxsize: Maximum number of cached group entries (default: 500)
        enable_session_auth: Enable session-based authentication (default: True)
        delegated_admin: Workspace admin email for domain-wide delegation. When set,
                        uses Admin SDK Directory API instead of Cloud Identity API.
                        Required for Business Standard (which lacks Cloud Identity Premium).
        target_groups: Specific groups to check membership for. Dramatically improves
                      Admin SDK efficiency by avoiding full domain graph traversal.
                      Also filters Cloud Identity API results when set.
        public_paths: Optional list of URL path prefixes to skip authentication for
                     (e.g., ["/v1/webhooks/", "/health"]). Requests matching these
                     paths will be treated as anonymous (request.user.is_authenticated
                     will be False). Useful for Pub/Sub push endpoints and health checks.
        on_error: Optional custom error handler (Request, AuthenticationError) -> Response
    """

    def __init__(
        self,
        app: typing.Callable[..., typing.Any],
        client_id: typing.Union[str, typing.List[str]],
        required_domains: typing.Optional[typing.List[str]] = None,
        fetch_groups: bool = True,
        credentials: typing.Optional[google.auth.credentials.Credentials] = None,
        customer_id: typing.Optional[str] = None,
        enable_token_cache: bool = True,
        token_cache_ttl: int = 300,
        token_cache_maxsize: int = 1000,
        enable_group_cache: bool = True,
        group_cache_ttl: int = 300,
        group_cache_maxsize: int = 500,
        enable_session_auth: bool = True,
        delegated_admin: typing.Optional[str] = None,
        target_groups: typing.Optional[typing.List[str]] = None,
        public_paths: typing.Optional[typing.List[str]] = None,
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
            customer_id=customer_id,
            enable_token_cache=enable_token_cache,
            token_cache_ttl=token_cache_ttl,
            token_cache_maxsize=token_cache_maxsize,
            enable_group_cache=enable_group_cache,
            group_cache_ttl=group_cache_ttl,
            group_cache_maxsize=group_cache_maxsize,
            enable_session_auth=enable_session_auth,
            delegated_admin=delegated_admin,
            target_groups=target_groups,
            public_paths=public_paths,
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
