"""
Decorators for route protection and role-based access control.

This module provides Google Workspace-specific decorators for authentication and
authorization. These decorators work alongside Starlette's built-in @requires decorator.

Two approaches for route protection:

1. **Custom decorators (this module)**: Google Workspace-specific, group-based
   - @require_auth - Require authentication
   - @require_group("group@example.com") - Require group membership

2. **Starlette's @requires decorator**: Scope-based authentication
   ```python
   from starlette.authentication import requires

   @requires("authenticated")
   async def protected_route(request):
       return {"user": request.user.email}

   @requires("group:admins@example.com")
   async def admin_route(request):
       return {"message": "Admin access"}
   ```

   The WorkspaceAuthBackend automatically populates scopes:
   - "authenticated" - User is authenticated
   - "group:<group_email>" - User belongs to specific group
"""

import functools
import typing
import inspect

import starlette.authentication
import starlette.exceptions

__all__ = [
    "PermissionDenied",
    "require_auth",
    "require_group",
    "require_scope",
]


class PermissionDenied(starlette.exceptions.HTTPException):
    """
    Raised when a user doesn't have required permissions.

    Returns a 403 Forbidden response. Starlette and FastAPI have built-in
    handlers for HTTPException, so this is handled automatically.
    """

    def __init__(self, detail: str = "Permission denied"):
        super().__init__(status_code=403, detail=detail)


def require_auth(
    func: typing.Callable[..., typing.Any],
) -> typing.Callable[..., typing.Any]:
    """
    Decorator that requires a user to be authenticated.

    Raises PermissionDenied if the user is not authenticated.

    Usage with FastAPI:
        ```python
        from fastapi import FastAPI, Request
        from workspace_auth_middleware import require_auth

        @app.get("/protected")
        @require_auth
        async def protected_route(request: Request):
            return {"user": request.user.email}
        ```

    Usage with Starlette:
        ```python
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from workspace_auth_middleware import require_auth

        @require_auth
        async def protected_endpoint(request: Request):
            return JSONResponse({"user": request.user.email})

        routes = [
            Route("/protected", protected_endpoint),
        ]
        ```
    """

    @functools.wraps(func)
    async def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        # Find the request object in args or kwargs
        request = _get_request_from_args(args, kwargs)

        if request is None:
            raise RuntimeError(
                "Could not find request object. "
                "Ensure your route handler has a 'request' parameter."
            )

        # Use request.scope.get() to avoid Starlette's user property assertion
        # which raises AssertionError if AuthenticationMiddleware hasn't set 'user'
        user = request.scope.get("user")

        if (
            user is None
            or isinstance(user, starlette.authentication.UnauthenticatedUser)
            or not user.is_authenticated
        ):
            raise PermissionDenied("Authentication required")

        return (
            await func(*args, **kwargs)
            if inspect.iscoroutinefunction(func)
            else func(*args, **kwargs)
        )

    return wrapper


def require_group(
    group: typing.Union[str, typing.List[str]], require_all: bool = False
) -> typing.Callable[..., typing.Any]:
    """
    Decorator that requires a user to belong to specific Google Workspace group(s).

    Args:
        group: Single group email or list of group emails
        require_all: If True, user must belong to ALL groups. If False, user must
                     belong to at least one group (default: False)

    Raises:
        PermissionDenied if user doesn't belong to required group(s)

    Usage with FastAPI:
        ```python
        from fastapi import FastAPI, Request
        from workspace_auth_middleware import require_group

        @app.get("/admin")
        @require_group("admins@example.com")
        async def admin_route(request: Request):
            return {"message": "Admin access granted"}

        @app.get("/special")
        @require_group(["team-a@example.com", "team-b@example.com"])
        async def multi_group_route(request: Request):
            # User must be in team-a OR team-b
            return {"message": "Team access granted"}

        @app.get("/restricted")
        @require_group(["managers@example.com", "leads@example.com"], require_all=True)
        async def restricted_route(request: Request):
            # User must be in BOTH managers AND leads groups
            return {"message": "Restricted access granted"}
        ```

    Usage with Starlette:
        ```python
        from starlette.responses import JSONResponse
        from workspace_auth_middleware import require_group

        @require_group("admins@example.com")
        async def admin_endpoint(request):
            return JSONResponse({"message": "Admin access"})
        ```
    """

    def decorator(
        func: typing.Callable[..., typing.Any],
    ) -> typing.Callable[..., typing.Any]:
        @functools.wraps(func)
        async def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
            # Find the request object
            request = _get_request_from_args(args, kwargs)

            if request is None:
                raise RuntimeError(
                    "Could not find request object. "
                    "Ensure your route handler has a 'request' parameter."
                )

            # Use request.scope.get() to avoid Starlette's user property assertion
            user = request.scope.get("user")

            # First check if user is authenticated
            if (
                user is None
                or isinstance(user, starlette.authentication.UnauthenticatedUser)
                or not user.is_authenticated
            ):
                raise PermissionDenied("Authentication required")

            # Check group membership
            groups = [group] if isinstance(group, str) else group

            if require_all:
                if not user.has_all_groups(groups):
                    raise PermissionDenied(
                        f"User must belong to all groups: {', '.join(groups)}"
                    )
            else:
                if not user.has_any_group(groups):
                    raise PermissionDenied(
                        f"User must belong to at least one group: {', '.join(groups)}"
                    )

            return (
                await func(*args, **kwargs)
                if inspect.iscoroutinefunction(func)
                else func(*args, **kwargs)
            )

        return wrapper

    return decorator


def require_scope(
    scope: typing.Union[str, typing.List[str]],
) -> typing.Callable[..., typing.Any]:
    """
    Decorator that requires specific authentication scope(s).

    Args:
        scope: Single scope or list of scopes

    Raises:
        PermissionDenied if user doesn't have required scope(s)

    Usage:
        ```python
        from fastapi import Request
        from workspace_auth_middleware import require_scope

        @app.get("/data")
        @require_scope("authenticated")
        async def data_route(request: Request):
            return {"data": "sensitive information"}
        ```
    """

    def decorator(
        func: typing.Callable[..., typing.Any],
    ) -> typing.Callable[..., typing.Any]:
        @functools.wraps(func)
        async def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
            request = _get_request_from_args(args, kwargs)

            if request is None:
                raise RuntimeError(
                    "Could not find request object. "
                    "Ensure your route handler has a 'request' parameter."
                )

            # Use request.scope.get() to avoid Starlette's auth property assertion
            auth = request.scope.get("auth")

            if auth is None:
                raise PermissionDenied("Authentication required")

            scopes = [scope] if isinstance(scope, str) else scope

            for required_scope in scopes:
                if not auth.has_scope(required_scope):
                    raise PermissionDenied(f"Missing required scope: {required_scope}")

            return (
                await func(*args, **kwargs)
                if inspect.iscoroutinefunction(func)
                else func(*args, **kwargs)
            )

        return wrapper

    return decorator


def _get_request_from_args(
    args: tuple[typing.Any, ...], kwargs: dict[str, typing.Any]
) -> typing.Any:
    """
    Helper function to extract the request object from function arguments.

    Checks both positional and keyword arguments for a request-like object.
    """
    # Check kwargs first
    if "request" in kwargs:
        return kwargs["request"]

    # Check positional args for request-like object
    for arg in args:
        if hasattr(arg, "scope") and hasattr(arg, "user"):
            return arg
        # For Starlette/FastAPI Request objects
        if hasattr(arg, "scope") and isinstance(getattr(arg, "scope", None), dict):
            return arg

    return None
