"""
workspace-auth-middleware: ASGI middleware for Google Workspace authentication.

This package provides authentication and authorization for ASGI applications
(FastAPI, Starlette) using Google Workspace OAuth2 tokens and group-based RBAC.

Built on top of Starlette's authentication system with Google Workspace-specific
features including group-based role-based access control (RBAC).

For OAuth2 authorization code flow (web applications), we recommend using Authlib:
https://docs.authlib.org/en/latest/client/starlette.html
"""

# Core components
from .middleware import WorkspaceAuthMiddleware
from .auth import WorkspaceAuthBackend
from .models import WorkspaceUser, AnonymousUser

# Decorators
from .decorators import (
    require_auth,
    require_group,
    require_scope,
    PermissionDenied,
)

# Re-export useful Starlette authentication components
import starlette.authentication

AuthenticationError = starlette.authentication.AuthenticationError
AuthCredentials = starlette.authentication.AuthCredentials
requires = starlette.authentication.requires

__version__ = "0.1.0"

__all__ = ["LOGGER_NAME"]

LOGGER_NAME = "workspace_auth_middleware"
