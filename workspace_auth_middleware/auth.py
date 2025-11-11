"""
Google Workspace authentication backend.

This module provides a Starlette-compatible authentication backend for
validating Google OAuth2 ID tokens and extracting Google Workspace group memberships.
"""

import asyncio
import logging
import typing

import google.auth.credentials
import google.auth
import google.oauth2.id_token
import google.oauth2.service_account
import google.auth.transport.requests
import starlette.authentication
import starlette.requests
import cachetools

from .models import WorkspaceUser

# Module-level logger - can be reconfigured by parent application
logger = logging.getLogger(__name__)

__all__ = [
    "WorkspaceAuthBackend",
]


def _authenticate_from_session(
    conn: starlette.requests.HTTPConnection,
    required_domains: typing.Optional[typing.List[str]] = None,
) -> typing.Optional[
    typing.Tuple[starlette.authentication.AuthCredentials, WorkspaceUser]
]:
    """
    Authenticate user from Starlette session data.

    This function reads user data from request.session["user"] (populated by
    OAuth2 login flow) and creates a WorkspaceUser object.

    Args:
        conn: The HTTP connection (Request or WebSocket)
        required_domains: Optional list of allowed domains

    Returns:
        Tuple of (AuthCredentials, WorkspaceUser) if authenticated, None otherwise
    """
    logger.debug("Attempting session-based authentication")

    try:
        user_data = conn.session.get("user")
    except (AssertionError, AttributeError, RuntimeError) as e:
        # SessionMiddleware not installed
        logger.debug(f"Session not available: {type(e).__name__}")
        return None

    if not isinstance(user_data, dict):
        logger.debug(f"Session user data is not a dict: {type(user_data)}")
        return None

    # Extract required fields
    email = user_data.get("email")
    user_id = user_data.get("user_id")

    logger.debug(f"Session data found - email: {email}, user_id: {user_id}")

    if not email or not user_id:
        logger.warning(f"Session missing required fields - email: {bool(email)}, user_id: {bool(user_id)}")
        return None

    # Validate domain if required
    if required_domains:
        domain = email.split("@")[-1]
        if domain not in required_domains:
            logger.warning(f"Domain '{domain}' not in required domains: {required_domains}")
            return None

    # Extract groups (ensure it's a list)
    groups = user_data.get("groups", [])
    if not isinstance(groups, list):
        logger.warning(f"Session groups is not a list: {type(groups)}, converting to empty list")
        groups = []

    logger.info(f"Session auth successful for {email} with {len(groups)} groups: {groups}")

    # Create user
    user = WorkspaceUser(
        email=email,
        user_id=user_id,
        name=user_data.get("name", email),
        domain=user_data.get("domain", email.split("@")[-1]),
        groups=groups,
    )

    # Create scopes
    scopes = ["authenticated"]
    scopes.extend([f"group:{group}" for group in groups])

    return starlette.authentication.AuthCredentials(scopes), user


class WorkspaceAuthBackend(starlette.authentication.AuthenticationBackend):
    """
    Authentication backend for Google Workspace users.

    Extends Starlette's AuthenticationBackend to provide Google Workspace-specific
    authentication using Google OAuth2 ID tokens and group-based authorization.

    This backend supports TWO authentication methods:
    1. Session-based (via Starlette's SessionMiddleware and request.session)
    2. Bearer token (Google ID token in Authorization header)

    Args:
        client_id: Google OAuth2 client ID for token validation
        required_domains: Optional list of allowed Google Workspace domains (e.g., ["example.com", "partner.com"]).
                         If specified, only users from these domains will be allowed.
                         If None, users from any domain are allowed.
        fetch_groups: If True, fetch user's group memberships (requires Admin SDK)
        credentials: Google credentials for Admin SDK calls. If None, uses default
                    application credentials. Must have appropriate scopes for Admin SDK.
        delegated_admin: Admin email for domain-wide delegation (required for group fetching)
        enable_session_auth: If True, check request.session for user data (requires SessionMiddleware)

    Example with session authentication:
        ```python
        from starlette.middleware import Middleware
        from starlette.middleware.sessions import SessionMiddleware
        from starlette.middleware.authentication import AuthenticationMiddleware
        from workspace_auth_middleware import WorkspaceAuthBackend

        # Add SessionMiddleware FIRST
        middleware = [
            Middleware(SessionMiddleware, secret_key="your-secret-key"),
            Middleware(
                AuthenticationMiddleware,
                backend=WorkspaceAuthBackend(
                    client_id="your-client-id.apps.googleusercontent.com",
                    required_domains=["example.com"],
                    enable_session_auth=True,  # Enable session support
                ),
            ),
        ]

        app = Starlette(routes=routes, middleware=middleware)
        ```

    Example with bearer token only:
        ```python
        from starlette.middleware.authentication import AuthenticationMiddleware
        from workspace_auth_middleware import WorkspaceAuthBackend

        backend = WorkspaceAuthBackend(
            client_id="your-client-id.apps.googleusercontent.com",
            required_domains=["example.com"],
            enable_session_auth=False,  # Disable session support
        )

        app.add_middleware(AuthenticationMiddleware, backend=backend)
        ```
    """

    def __init__(
        self,
        client_id: str,
        required_domains: typing.Optional[typing.List[str]] = None,
        fetch_groups: bool = True,
        credentials: typing.Optional[google.auth.credentials.Credentials] = None,
        delegated_admin: typing.Optional[str] = None,
        enable_token_cache: bool = True,
        token_cache_ttl: int = 300,  # 5 minutes
        token_cache_maxsize: int = 1000,
        enable_group_cache: bool = True,
        group_cache_ttl: int = 300,  # 5 minutes
        group_cache_maxsize: int = 500,
        enable_session_auth: bool = True,
    ):
        logger.info(
            f"Initializing WorkspaceAuthBackend - "
            f"client_id: {client_id[:20]}..., "
            f"required_domains: {required_domains}, "
            f"fetch_groups: {fetch_groups}, "
            f"delegated_admin: {delegated_admin}, "
            f"enable_session_auth: {enable_session_auth}, "
            f"enable_token_cache: {enable_token_cache}, "
            f"enable_group_cache: {enable_group_cache}"
        )

        self.client_id = client_id
        self.required_domains = required_domains
        self.fetch_groups = fetch_groups
        self.delegated_admin = delegated_admin
        self.enable_session_auth = enable_session_auth

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
            logger.info("Using provided credentials for group fetching")
            self.credentials = credentials
        elif fetch_groups:
            # Only load default credentials if group fetching is enabled
            try:
                logger.info("Attempting to load default application credentials for group fetching")
                tmp_credentials, project = google.auth.default()

                request = google.auth.transport.requests.Request()
                tmp_credentials.refresh(request)
                signer = google.auth.iam.Signer(request, tmp_credentials, tmp_credentials.service_account_email)

                credentials = google.oauth2.service_account.Credentials(
                    signer,
                    tmp_credentials.service_account_email,
                    scopes = [
                        "https://www.googleapis.com/auth/admin.directory.group.readonly",
                        "https://www.googleapis.com/auth/admin.directory.group.member.readonly",
                    ],
                     subject = delegated_admin,
                )
                logger.info(f"Successfully loaded default credentials for project: {project}")
            except Exception as e:
                # If default credentials aren't available, set to None
                # Group fetching will be skipped
                logger.warning(f"Failed to load default credentials: {type(e).__name__}: {e}")
                logger.warning("Group fetching will be disabled")
                self.credentials = None
        else:
            logger.info("Group fetching disabled - no credentials needed")
            self.credentials = None

    async def authenticate(
        self, conn: starlette.requests.HTTPConnection
    ) -> typing.Optional[
        typing.Tuple[starlette.authentication.AuthCredentials, WorkspaceUser]
    ]:
        """
        Authenticate a request based on Starlette session or Authorization header.

        This method is called by Starlette's AuthenticationMiddleware for each request.
        It supports two authentication methods (in priority order):
        1. Session data from request.session (populated via OAuth2 authorization code flow)
        2. Bearer token (Google ID token) in Authorization header

        Args:
            conn: Starlette HTTPConnection object (Request or WebSocket)

        Returns:
            Tuple of (AuthCredentials, WorkspaceUser) if authenticated
            None if no authentication provided (anonymous user)

        Raises:
            AuthenticationError: If authentication credentials are invalid

        Expected formats:
            - Session: request.session["user"] = {"email": ..., "user_id": ..., ...}
            - Authorization: Bearer <google_id_token>
        """
        logger.debug(f"authenticate() called for path: {conn.url.path}")

        # Try session authentication first (if enabled)
        if self.enable_session_auth:
            logger.debug("Session authentication is enabled, attempting session auth")
            try:
                session_result = _authenticate_from_session(conn, self.required_domains)
                if session_result is not None:
                    logger.info(f"Successfully authenticated via session: {session_result[1].email}")
                    return session_result
                else:
                    logger.debug("No valid session data found, will try bearer token")
            except (AssertionError, AttributeError, RuntimeError) as e:
                # SessionMiddleware not installed - skip session auth
                logger.debug(f"Session auth failed with {type(e).__name__}, will try bearer token")
                pass
        else:
            logger.debug("Session authentication is disabled")

        # Fall back to bearer token authentication
        if "authorization" not in conn.headers:
            # No authentication provided - return None for anonymous user
            logger.debug("No Authorization header found - anonymous request")
            return None

        logger.debug("Authorization header found, attempting bearer token auth")

        try:
            # Parse Authorization header
            auth = conn.headers["authorization"]
            scheme, _, token = auth.partition(" ")

            if scheme.lower() != "bearer":
                raise starlette.authentication.AuthenticationError(
                    "Invalid authentication scheme. Expected Bearer token."
                )

            # Verify the Google ID token
            logger.debug("Verifying Google ID token")
            user_info = await self._verify_token(token)

            # Extract user information
            email = user_info.get("email")
            user_id = user_info.get("sub")
            name = user_info.get("name")
            domain = email.split("@")[-1] if email else None

            logger.debug(f"Token verified - email: {email}, user_id: {user_id}, domain: {domain}")

            if not email or not user_id:
                logger.error("Token verification succeeded but missing email or user_id")
                raise starlette.authentication.AuthenticationError(
                    "Invalid token: missing email or user ID"
                )

            # Check domain restriction if required
            if self.required_domains and domain not in self.required_domains:
                logger.warning(f"Domain restriction failed: {domain} not in {self.required_domains}")
                raise starlette.authentication.AuthenticationError(
                    f"User domain '{domain}' not in allowed domains: {', '.join(self.required_domains)}"
                )

            # Fetch user's groups (placeholder - implement with Admin SDK)
            groups = []
            if self.fetch_groups:
                logger.debug(f"fetch_groups=True, attempting to fetch groups for {email}")
                groups = await self._fetch_user_groups(email)
                logger.info(f"Fetched {len(groups)} groups for {email}: {groups}")
            else:
                logger.debug("fetch_groups=False, skipping group fetching")

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

            logger.info(f"Successfully authenticated {email} with {len(scopes)} scopes: {scopes}")

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
        token_preview = token[:20] + "..." if len(token) > 20 else token
        logger.debug(f"_verify_token() called for token: {token_preview}")

        # Check cache first
        if isinstance(self._token_cache, cachetools.TTLCache) and isinstance(
            self._token_cache_stats, dict
        ):
            if token in self._token_cache:
                self._token_cache_stats["hits"] += 1
                logger.debug(f"Token cache HIT for {token_preview}")
                return self._token_cache[token]
            self._token_cache_stats["misses"] += 1
            logger.debug(f"Token cache MISS for {token_preview}")

        try:
            # Verify the token with Google
            # Note: This is a synchronous operation, but we can make it async
            # by running it in an executor if needed
            logger.debug("Verifying token with Google OAuth2 API")
            request = google.auth.transport.requests.Request()
            idinfo = google.oauth2.id_token.verify_oauth2_token(
                token, request, self.client_id
            )

            logger.debug(f"Token verified successfully - email: {idinfo.get('email')}, sub: {idinfo.get('sub')}")

            # Additional validation
            if idinfo.get("iss") not in [
                "accounts.google.com",
                "https://accounts.google.com",
            ]:
                logger.error(f"Invalid token issuer: {idinfo.get('iss')}")
                raise starlette.authentication.AuthenticationError(
                    "Invalid token issuer"
                )

            # Cache the result
            if isinstance(self._token_cache, cachetools.TTLCache):
                self._token_cache[token] = idinfo
                logger.debug(f"Cached token for {idinfo.get('email')}")

            return idinfo

        except Exception as e:
            logger.error(f"Token verification failed: {type(e).__name__}: {e}")
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
        logger.debug(f"_fetch_user_groups() called for {email}")

        # Check cache first
        if isinstance(self._group_cache, cachetools.TTLCache) and isinstance(
            self._group_cache_stats, dict
        ):
            if email in self._group_cache:
                self._group_cache_stats["hits"] += 1
                cached_groups = self._group_cache[email]
                logger.debug(f"Group cache HIT for {email}: {cached_groups}")
                return cached_groups
            self._group_cache_stats["misses"] += 1
            logger.debug(f"Group cache MISS for {email}")

        # Check if we have credentials
        if self.credentials is None:
            logger.warning(f"No credentials available for group fetching - returning empty list for {email}")
            return []

        try:
            # Prepare credentials with domain-wide delegation if needed
            delegated_credentials = self.credentials
            if self.delegated_admin:
                logger.debug(f"Using domain-wide delegation with admin: {self.delegated_admin}")
                # Create delegated credentials for domain-wide delegation
                # This allows the service account to act on behalf of the admin
                if hasattr(self.credentials, "with_subject"):
                    delegated_credentials = self.credentials.with_subject(
                        self.delegated_admin
                    )
                    logger.debug(f"Created delegated credentials for {self.delegated_admin}")
                else:
                    logger.warning(f"Credentials do not support with_subject() - cannot delegate to {self.delegated_admin}")
            else:
                logger.warning("No delegated_admin configured - group fetching may fail without domain-wide delegation")

            # Run Admin SDK call in executor (it's synchronous)
            logger.debug(f"Calling Admin SDK to fetch groups for {email}")
            loop = asyncio.get_event_loop()
            groups = await loop.run_in_executor(
                None, self._fetch_groups_sync, delegated_credentials, email
            )

            logger.info(f"Successfully fetched {len(groups)} groups for {email}: {groups}")

            # Cache the result
            if isinstance(self._group_cache, cachetools.TTLCache):
                self._group_cache[email] = groups
                logger.debug(f"Cached groups for {email}")

            return groups

        except Exception as e:
            # On any error, return empty list
            # This ensures authentication doesn't fail if group fetching fails
            logger.error(f"Failed to fetch groups for {email}: {type(e).__name__}: {e}", exc_info=True)
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
            logger.debug(f"_fetch_groups_sync() called for {email}")
            import googleapiclient.discovery  # type: ignore[import-untyped]

            # Build the Admin SDK service
            logger.debug("Building Admin SDK service (admin/directory_v1)")
            service = googleapiclient.discovery.build(  # type: ignore[no-untyped-call]
                "admin", "directory_v1", credentials=creds
            )

            # Fetch groups for the user
            logger.debug(f"Calling service.groups().list(userKey={email})")
            result = service.groups().list(userKey=email).execute()

            logger.debug(f"Admin SDK response: {result}")

            # Extract group email addresses
            groups = [group["email"] for group in result.get("groups", [])]
            logger.debug(f"Extracted {len(groups)} group emails from Admin SDK response")
            return groups

        except ImportError as e:
            logger.error(f"Failed to import googleapiclient: {e}")
            logger.error("Install google-api-python-client to enable group fetching: pip install google-api-python-client")
            return []
        except Exception as e:
            # Return empty list on any error
            logger.error(f"Admin SDK call failed for {email}: {type(e).__name__}: {e}", exc_info=True)
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
