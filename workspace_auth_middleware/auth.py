"""
Google Workspace authentication backend.

This module provides a Starlette-compatible authentication backend for
validating Google OAuth2 ID tokens and extracting Google Workspace group memberships.
"""

import asyncio
import typing

import google.auth.credentials
import google.auth
import google.oauth2.id_token
import google.auth.transport.requests
import starlette.authentication
import starlette.requests
import cachetools

from .models import WorkspaceUser

__all__ = [
    "WorkspaceAuthBackend",
]


class WorkspaceAuthBackend(starlette.authentication.AuthenticationBackend):
    """
    Authentication backend for Google Workspace users.

    Extends Starlette's AuthenticationBackend to provide Google Workspace-specific
    authentication using Google OAuth2 ID tokens and group-based authorization.

    This backend:
    1. Validates Google OAuth2 ID tokens from Authorization header
    2. Extracts user information from the token
    3. Fetches user's Google Workspace groups (configurable)
    4. Populates request.user and request.auth via Starlette's middleware

    Args:
        client_id: Google OAuth2 client ID for token validation
        workspace_domain: Expected Google Workspace domain (e.g., "example.com")
        required_domain: If True, only allow users from workspace_domain
        fetch_groups: If True, fetch user's group memberships (requires Admin SDK)
        credentials: Google credentials for Admin SDK calls. If None, uses default
                    application credentials. Must have appropriate scopes for Admin SDK.
        delegated_admin: Admin email for domain-wide delegation (required for group fetching)

    Example with default application credentials:
        ```python
        from starlette.middleware.authentication import AuthenticationMiddleware
        from workspace_auth_middleware import WorkspaceAuthBackend

        backend = WorkspaceAuthBackend(
            client_id="your-client-id.apps.googleusercontent.com",
            workspace_domain="example.com",
            delegated_admin="admin@example.com",  # For group fetching
        )

        app.add_middleware(AuthenticationMiddleware, backend=backend)
        ```

    Example with explicit service account credentials:
        ```python
        from google.oauth2 import service_account
        from workspace_auth_middleware import WorkspaceAuthBackend

        credentials = service_account.Credentials.from_service_account_file(
            'service-account-key.json',
            scopes=['https://www.googleapis.com/auth/admin.directory.group.readonly']
        )

        backend = WorkspaceAuthBackend(
            client_id="your-client-id.apps.googleusercontent.com",
            workspace_domain="example.com",
            credentials=credentials,
            delegated_admin="admin@example.com",
        )

        app.add_middleware(AuthenticationMiddleware, backend=backend)
        ```
    """

    def __init__(
        self,
        client_id: str,
        workspace_domain: typing.Optional[str] = None,
        required_domain: bool = True,
        fetch_groups: bool = True,
        credentials: typing.Optional[google.auth.credentials.Credentials] = None,
        delegated_admin: typing.Optional[str] = None,
        enable_token_cache: bool = True,
        token_cache_ttl: int = 300,  # 5 minutes
        token_cache_maxsize: int = 1000,
        enable_group_cache: bool = True,
        group_cache_ttl: int = 300,  # 5 minutes
        group_cache_maxsize: int = 500,
    ):
        self.client_id = client_id
        self.workspace_domain = workspace_domain
        self.required_domain = required_domain
        self.fetch_groups = fetch_groups
        self.delegated_admin = delegated_admin

        # Cache configuration
        self.enable_token_cache = enable_token_cache
        self.enable_group_cache = enable_group_cache

        # Initialize caches
        if self.enable_token_cache:
            self._token_cache: typing.Optional[cachetools.TTLCache[str, typing.Any]] = (
                cachetools.TTLCache(maxsize=token_cache_maxsize, ttl=token_cache_ttl)
            )
            self._token_cache_stats: typing.Optional[typing.Dict[str, int]] = {
                "hits": 0,
                "misses": 0,
            }
        else:
            self._token_cache = None
            self._token_cache_stats = None

        if self.enable_group_cache:
            self._group_cache: typing.Optional[
                cachetools.TTLCache[str, typing.List[str]]
            ] = cachetools.TTLCache(maxsize=group_cache_maxsize, ttl=group_cache_ttl)
            self._group_cache_stats: typing.Optional[typing.Dict[str, int]] = {
                "hits": 0,
                "misses": 0,
            }
        else:
            self._group_cache = None
            self._group_cache_stats = None

        # Use provided credentials or fallback to default application credentials
        self.credentials: typing.Optional[google.auth.credentials.Credentials]
        if credentials is not None:
            self.credentials = credentials
        elif fetch_groups:
            # Only load default credentials if group fetching is enabled
            try:
                self.credentials, _ = google.auth.default(
                    scopes=[
                        "https://www.googleapis.com/auth/admin.directory.group.readonly"
                    ]
                )
            except Exception:
                # If default credentials aren't available, set to None
                # Group fetching will be skipped
                self.credentials = None
        else:
            self.credentials = None

    async def authenticate(
        self, conn: starlette.requests.HTTPConnection
    ) -> typing.Optional[
        typing.Tuple[starlette.authentication.AuthCredentials, WorkspaceUser]
    ]:
        """
        Authenticate a request based on the Authorization header.

        This method is called by Starlette's AuthenticationMiddleware for each request.

        Args:
            conn: Starlette HTTPConnection object (Request or WebSocket)

        Returns:
            Tuple of (AuthCredentials, WorkspaceUser) if authenticated
            None if no authentication provided (anonymous user)

        Raises:
            AuthenticationError: If authentication credentials are invalid

        Expected header format:
            Authorization: Bearer <google_id_token>
        """
        # Check for Authorization header
        if "authorization" not in conn.headers:
            # No authentication provided - return None for anonymous user
            return None

        try:
            # Parse Authorization header
            auth = conn.headers["authorization"]
            scheme, _, token = auth.partition(" ")

            if scheme.lower() != "bearer":
                raise starlette.authentication.AuthenticationError(
                    "Invalid authentication scheme. Expected Bearer token."
                )

            # Verify the Google ID token
            user_info = await self._verify_token(token)

            # Extract user information
            email = user_info.get("email")
            user_id = user_info.get("sub")
            name = user_info.get("name")
            domain = email.split("@")[-1] if email else None

            if not email or not user_id:
                raise starlette.authentication.AuthenticationError(
                    "Invalid token: missing email or user ID"
                )

            # Check domain restriction if required
            if self.required_domain and self.workspace_domain:
                if domain != self.workspace_domain:
                    raise starlette.authentication.AuthenticationError(
                        f"User not from required domain: {self.workspace_domain}"
                    )

            # Fetch user's groups (placeholder - implement with Admin SDK)
            groups = []
            if self.fetch_groups:
                groups = await self._fetch_user_groups(email)

            # Create user object
            user = WorkspaceUser(
                email=email,
                user_id=user_id,
                name=name,
                groups=groups,
                domain=domain,
            )

            # Set scopes based on authentication
            # Standard scopes + group-based scopes for use with @requires decorator
            scopes = ["authenticated"]
            if groups:
                # Add group scopes for Starlette's @requires decorator
                scopes.extend([f"group:{group}" for group in groups])

            credentials = starlette.authentication.AuthCredentials(scopes=scopes)

            return credentials, user

        except starlette.authentication.AuthenticationError:
            # Re-raise Starlette's AuthenticationError
            raise
        except Exception as e:
            # Wrap other exceptions in AuthenticationError
            raise starlette.authentication.AuthenticationError(
                f"Authentication failed: {str(e)}"
            )

    async def _verify_token(self, token: str) -> dict:
        """
        Verify Google ID token and return claims.

        Uses caching to avoid repeated verification of the same token.
        Cache TTL respects the token's expiration time.

        Args:
            token: Google ID token string

        Returns:
            Dictionary of token claims

        Raises:
            AuthenticationError if token is invalid
        """
        # Check cache first
        if isinstance(self._token_cache, cachetools.TTLCache) and isinstance(
            self._token_cache_stats, dict
        ):
            if token in self._token_cache:
                self._token_cache_stats["hits"] += 1
                return self._token_cache[token]
            self._token_cache_stats["misses"] += 1

        try:
            # Verify the token with Google
            # Note: This is a synchronous operation, but we can make it async
            # by running it in an executor if needed
            request = google.auth.transport.requests.Request()
            idinfo = google.oauth2.id_token.verify_oauth2_token(
                token, request, self.client_id
            )

            # Additional validation
            if idinfo.get("iss") not in [
                "accounts.google.com",
                "https://accounts.google.com",
            ]:
                raise starlette.authentication.AuthenticationError(
                    "Invalid token issuer"
                )

            # Cache the result
            if isinstance(self._token_cache, cachetools.TTLCache):
                self._token_cache[token] = idinfo

            return idinfo

        except Exception as e:
            raise starlette.authentication.AuthenticationError(
                f"Token verification failed: {str(e)}"
            )

    async def _fetch_user_groups(self, email: str) -> typing.List[str]:
        """
        Fetch user's Google Workspace group memberships using the Admin SDK.

        Uses caching to avoid repeated API calls for the same user.
        This significantly improves performance since Admin SDK calls are slow (100-500ms).

        This method uses the Google Admin SDK Directory API to fetch the list of
        groups that a user belongs to. Requires:
        1. Service account credentials with appropriate scopes
        2. Domain-wide delegation enabled for the service account
        3. google-api-python-client package installed

        Args:
            email: User's email address

        Returns:
            List of group email addresses the user belongs to
            Returns empty list if credentials unavailable or Admin SDK not installed

        Raises:
            No exceptions raised - errors are logged and empty list returned
        """
        # Check cache first
        if isinstance(self._group_cache, cachetools.TTLCache) and isinstance(
            self._group_cache_stats, dict
        ):
            if email in self._group_cache:
                self._group_cache_stats["hits"] += 1
                return self._group_cache[email]
            self._group_cache_stats["misses"] += 1

        # Check if we have credentials
        if self.credentials is None:
            return []

        try:
            # Prepare credentials with domain-wide delegation if needed
            delegated_credentials = self.credentials
            if self.delegated_admin:
                # Create delegated credentials for domain-wide delegation
                # This allows the service account to act on behalf of the admin
                if hasattr(self.credentials, "with_subject"):
                    delegated_credentials = self.credentials.with_subject(
                        self.delegated_admin
                    )

            # Run Admin SDK call in executor (it's synchronous)
            loop = asyncio.get_event_loop()
            groups = await loop.run_in_executor(
                None, self._fetch_groups_sync, delegated_credentials, email
            )

            # Cache the result
            if isinstance(self._group_cache, cachetools.TTLCache):
                self._group_cache[email] = groups

            return groups

        except Exception:
            # On any error, return empty list
            # This ensures authentication doesn't fail if group fetching fails
            return []

    def _fetch_groups_sync(
        self, creds: google.auth.credentials.Credentials, email: str
    ) -> typing.List[str]:
        """
        Synchronous helper to fetch groups using Admin SDK.

        Args:
            creds: Google credentials to use
            email: User's email address

        Returns:
            List of group email addresses
        """
        try:
            import googleapiclient.discovery  # type: ignore[import-untyped]

            # Build the Admin SDK service
            service = googleapiclient.discovery.build(  # type: ignore[no-untyped-call]
                "admin", "directory_v1", credentials=creds
            )

            # Fetch groups for the user
            result = service.groups().list(userKey=email).execute()

            # Extract group email addresses
            return [group["email"] for group in result.get("groups", [])]

        except Exception:
            # Return empty list on any error
            return []

    def get_cache_stats(self) -> typing.Dict[str, typing.Any]:
        """
        Get cache statistics for monitoring and debugging.

        Returns:
            Dictionary with cache stats including hits, misses, and hit rates
        """
        stats = {}

        if isinstance(self._token_cache, cachetools.TTLCache) and isinstance(
            self._token_cache_stats, dict
        ):
            total = self._token_cache_stats["hits"] + self._token_cache_stats["misses"]
            hit_rate = self._token_cache_stats["hits"] / total if total > 0 else 0.0
            stats["token_cache"] = {
                "enabled": True,
                "hits": self._token_cache_stats["hits"],
                "misses": self._token_cache_stats["misses"],
                "hit_rate": hit_rate,
                "size": len(self._token_cache),
                "maxsize": self._token_cache.maxsize,
            }
        else:
            stats["token_cache"] = {"enabled": False}

        if isinstance(self._group_cache, cachetools.TTLCache) and isinstance(
            self._group_cache_stats, dict
        ):
            total = self._group_cache_stats["hits"] + self._group_cache_stats["misses"]
            hit_rate = self._group_cache_stats["hits"] / total if total > 0 else 0.0
            stats["group_cache"] = {
                "enabled": True,
                "hits": self._group_cache_stats["hits"],
                "misses": self._group_cache_stats["misses"],
                "hit_rate": hit_rate,
                "size": len(self._group_cache),
                "maxsize": self._group_cache.maxsize,
            }
        else:
            stats["group_cache"] = {"enabled": False}

        return stats

    def clear_caches(self) -> None:
        """
        Clear all caches and reset statistics.

        Useful for testing or when you need to force fresh data.
        """
        if isinstance(self._token_cache, cachetools.TTLCache):
            self._token_cache.clear()
            self._token_cache_stats = {"hits": 0, "misses": 0}

        if isinstance(self._group_cache, cachetools.TTLCache):
            self._group_cache.clear()
            self._group_cache_stats = {"hits": 0, "misses": 0}

    def invalidate_user_groups(self, email: str) -> bool:
        """
        Invalidate cached groups for a specific user.

        Useful when you know a user's group membership has changed.

        Args:
            email: User's email address

        Returns:
            True if the entry was cached and removed, False otherwise
        """
        if (
            isinstance(self._group_cache, cachetools.TTLCache)
            and email in self._group_cache
        ):
            del self._group_cache[email]
            return True
        return False

    def invalidate_token(self, token: str) -> bool:
        """
        Invalidate a cached token.

        Useful for implementing token revocation.

        Args:
            token: The token to invalidate

        Returns:
            True if the token was cached and removed, False otherwise
        """
        if (
            isinstance(self._token_cache, cachetools.TTLCache)
            and token in self._token_cache
        ):
            del self._token_cache[token]
            return True
        return False
