"""
Google Workspace authentication backend.

This module provides a Starlette-compatible authentication backend for
validating Google OAuth2 ID tokens and extracting Google Workspace group memberships.
"""

import asyncio
import logging
import typing
import urllib.parse

import google.auth
import google.auth.credentials
import google.auth.transport.requests
import google.oauth2.id_token
import googleapiclient.discovery  # type: ignore[import-untyped]
import starlette.authentication
import starlette.requests
import cachetools

from .models import WorkspaceUser

# Module-level logger - can be reconfigured by parent application
logger = logging.getLogger("workspace_auth_middleware")
logger.propagate = True
logger.setLevel(logging.DEBUG)
logger.handlers = []

_SENTINEL = object()

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
        logger.debug("Session not available: %s", type(e).__name__)
        return None

    if not isinstance(user_data, dict):
        logger.debug("Session user data is not a dict: %s", type(user_data))
        return None

    # Extract required fields
    email = user_data.get("email")
    user_id = user_data.get("user_id")

    logger.debug("Session data found - email: %s, user_id: %s", email, user_id)

    if not email or not user_id:
        logger.warning(
            "Session missing required fields - email: %s, user_id: %s",
            bool(email),
            bool(user_id),
        )
        return None

    # Validate domain if required
    if required_domains:
        domain = email.split("@")[-1]
        if domain not in required_domains:
            logger.warning(
                "Domain '%s' not in required domains: %s", domain, required_domains
            )
            return None

    # Extract groups (ensure it's a list)
    groups = user_data.get("groups", [])
    if not isinstance(groups, list):
        logger.warning(
            "Session groups is not a list: %s, converting to empty list", type(groups)
        )
        groups = []

    logger.info(
        "Session auth successful for %s with %d groups: %s", email, len(groups), groups
    )

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
        fetch_groups: If True, fetch user's group memberships (requires Cloud Identity Groups API).
                     The service account must have the Groups Administrator role assigned.
        credentials: Google credentials for Cloud Identity API calls. If None, uses default
                    application credentials with cloud-identity.groups scope.
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
        client_id: typing.Union[str, typing.List[str]],
        required_domains: typing.Optional[typing.List[str]] = None,
        fetch_groups: bool = True,
        credentials: typing.Optional[google.auth.credentials.Credentials] = None,
        customer_id: typing.Optional[str] = None,
        enable_token_cache: bool = True,
        token_cache_ttl: int = 300,  # 5 minutes
        token_cache_maxsize: int = 1000,
        enable_group_cache: bool = True,
        group_cache_ttl: int = 300,  # 5 minutes
        group_cache_maxsize: int = 500,
        enable_session_auth: bool = True,
    ):
        # Normalize client_id to a list
        self.client_ids: typing.List[str] = (
            [client_id] if isinstance(client_id, str) else list(client_id)
        )
        # Backwards compatibility: expose first client_id
        self.client_id = self.client_ids[0] if self.client_ids else ""

        logger.info(
            "Initializing WorkspaceAuthBackend - "
            "client_ids: %s, required_domains: %s, fetch_groups: %s, "
            "enable_session_auth: %s, enable_token_cache: %s, enable_group_cache: %s",
            [c[:20] + "..." for c in self.client_ids],
            required_domains,
            fetch_groups,
            enable_session_auth,
            enable_token_cache,
            enable_group_cache,
        )
        self.required_domains = required_domains
        self.fetch_groups = fetch_groups
        self.customer_id = customer_id
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
            try:
                logger.info("Using application default credentials for group fetching")

                request = google.auth.transport.requests.Request()
                self.credentials, _ = google.auth.default(
                    scopes=[
                        "https://www.googleapis.com/auth/cloud-identity.groups.readonly",
                    ]
                )
                self.credentials.refresh(request)  # type: ignore[no-untyped-call]

                logger.info("Credential building complete")
            except Exception:
                logger.warning("Error getting credentials", exc_info=True)
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
        logger.debug("authenticate() called for path: %s", conn.url.path)

        # Try session authentication first (if enabled)
        if self.enable_session_auth:
            logger.debug("Session authentication is enabled, attempting session auth")
            try:
                session_result = _authenticate_from_session(conn, self.required_domains)
                if session_result is not None:
                    logger.info(
                        "Successfully authenticated via session: %s",
                        session_result[1].email,
                    )
                    return session_result
                else:
                    logger.debug("No valid session data found, will try bearer token")
            except (AssertionError, AttributeError, RuntimeError) as e:
                # SessionMiddleware not installed - skip session auth
                logger.debug(
                    "Session auth failed with %s, will try bearer token",
                    type(e).__name__,
                )
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

            logger.debug(
                "Token verified - email: %s, user_id: %s, domain: %s",
                email,
                user_id,
                domain,
            )

            if not email or not user_id:
                logger.error(
                    "Token verification succeeded but missing email or user_id"
                )
                raise starlette.authentication.AuthenticationError(
                    "Invalid token: missing email or user ID"
                )

            # Check email_verified claim
            if not user_info.get("email_verified", False):
                logger.warning(
                    "Email not verified for user: %s",
                    email,
                )
                raise starlette.authentication.AuthenticationError(
                    "Email address has not been verified"
                )

            # Check domain restriction if required
            if self.required_domains and domain not in self.required_domains:
                logger.warning(
                    "Domain restriction failed: %s not in %s",
                    domain,
                    self.required_domains,
                )
                raise starlette.authentication.AuthenticationError(
                    f"User domain '{domain}' not in allowed domains: {', '.join(self.required_domains)}"
                )

            # Fetch user's groups (placeholder - implement with Admin SDK)
            groups = []
            if self.fetch_groups:
                logger.debug(
                    "fetch_groups=True, attempting to fetch groups for %s", email
                )
                groups = await self._fetch_user_groups(email)
                logger.info("Fetched %d groups for %s: %s", len(groups), email, groups)
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

            logger.info(
                "Successfully authenticated %s with %d scopes: %s",
                email,
                len(scopes),
                scopes,
            )

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

    def _verify_token_sync(self, token: str) -> dict[str, typing.Any]:
        """
        Synchronous helper to verify a Google ID token.

        Tries each configured client_id and validates the issuer.
        This runs in an executor to avoid blocking the event loop.

        Args:
            token: Google ID token string

        Returns:
            Dictionary of token claims

        Raises:
            AuthenticationError if token is invalid
        """
        logger.debug("Verifying token with Google OAuth2 API")
        request = google.auth.transport.requests.Request()

        # Try each client_id until one succeeds
        last_error: typing.Optional[ValueError] = None
        for cid in self.client_ids:
            try:
                idinfo: dict[str, typing.Any] = (
                    google.oauth2.id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
                        token, request, cid
                    )
                )
                logger.debug("Token verified with client_id: %s...", cid[:20])
                break
            except ValueError as e:
                last_error = e
                logger.debug(
                    "Token verification failed for client_id %s...: %s", cid[:20], e
                )
        else:
            raise starlette.authentication.AuthenticationError(
                f"Token verification failed: {last_error}"
            )

        logger.debug(
            "Token verified successfully - email: %s, sub: %s",
            idinfo.get("email"),
            idinfo.get("sub"),
        )

        # Additional validation
        if idinfo.get("iss") not in [
            "accounts.google.com",
            "https://accounts.google.com",
        ]:
            logger.error("Invalid token issuer: %s", idinfo.get("iss"))
            raise starlette.authentication.AuthenticationError("Invalid token issuer")

        return idinfo

    async def _verify_token(self, token: str) -> dict[str, typing.Any]:
        """
        Verify Google ID token and return claims.

        Uses caching to avoid repeated verification of the same token.
        Runs the synchronous verification in an executor to avoid blocking.

        Args:
            token: Google ID token string

        Returns:
            Dictionary of token claims

        Raises:
            AuthenticationError if token is invalid
        """
        token_preview = token[:20] + "..." if len(token) > 20 else token
        logger.debug("_verify_token() called for token: %s", token_preview)

        # Check cache first
        if isinstance(self._token_cache, cachetools.TTLCache) and isinstance(
            self._token_cache_stats, dict
        ):
            cached = self._token_cache.get(token, _SENTINEL)
            if cached is not _SENTINEL:
                self._token_cache_stats["hits"] += 1
                logger.debug("Token cache HIT for %s", token_preview)
                return typing.cast(dict[str, typing.Any], cached)
            self._token_cache_stats["misses"] += 1
            logger.debug("Token cache MISS for %s", token_preview)

        try:
            loop = asyncio.get_running_loop()
            idinfo: dict[str, typing.Any] = await loop.run_in_executor(
                None, self._verify_token_sync, token
            )

            # Cache the result
            if isinstance(self._token_cache, cachetools.TTLCache):
                self._token_cache[token] = idinfo
                logger.debug("Cached token for %s", idinfo.get("email"))

            return idinfo

        except starlette.authentication.AuthenticationError:
            raise
        except Exception as e:
            logger.error("Token verification failed", exc_info=True)
            raise starlette.authentication.AuthenticationError(
                f"Token verification failed: {str(e)}"
            )

    async def _fetch_user_groups(self, email: str) -> typing.List[str]:
        """
        Fetch user's Google Workspace group memberships using the Cloud Identity Groups API.

        Uses caching to avoid repeated API calls for the same user.
        This significantly improves performance since API calls are slow (100-500ms).

        This method uses the Cloud Identity Groups API to fetch the list of
        groups that a user belongs to. Requires:
        1. Service account with Groups Administrator role assigned in Google Workspace
        2. cloud-identity.groups scope
        3. google-api-python-client package installed

        Note: This approach does NOT require domain-wide delegation. The service account
        acts as itself with the Groups Administrator role.

        Args:
            email: User's email address

        Returns:
            List of group email addresses the user belongs to
            Returns empty list if credentials unavailable or API client not installed

        Raises:
            No exceptions raised - errors are logged and empty list returned
        """
        logger.debug("_fetch_user_groups() called for %s", email)

        # Check cache first
        if isinstance(self._group_cache, cachetools.TTLCache) and isinstance(
            self._group_cache_stats, dict
        ):
            cached_groups = self._group_cache.get(email, _SENTINEL)
            if cached_groups is not _SENTINEL:
                self._group_cache_stats["hits"] += 1
                logger.debug("Group cache HIT for %s: %s", email, cached_groups)
                return typing.cast(typing.List[str], cached_groups)
            self._group_cache_stats["misses"] += 1
            logger.debug("Group cache MISS for %s", email)

        # Check if we have credentials
        if self.credentials is None:
            logger.warning(
                "No credentials available for group fetching - returning empty list for %s",
                email,
            )
            return []

        try:
            # Run Cloud Identity API call in executor (it's synchronous)
            logger.debug(
                "Calling Cloud Identity Groups API to fetch groups for %s", email
            )
            loop = asyncio.get_running_loop()
            groups = await loop.run_in_executor(
                None,
                self._fetch_groups_sync,
                self.credentials,
                email,
            )

            logger.info(
                "Successfully fetched %d groups for %s: %s", len(groups), email, groups
            )

            # Cache the result
            if isinstance(self._group_cache, cachetools.TTLCache):
                self._group_cache[email] = groups
                logger.debug("Cached groups for %s", email)

            return groups

        except Exception:
            # On any error, return empty list
            # This ensures authentication doesn't fail if group fetching fails
            logger.error("Failed to fetch groups for %s", email, exc_info=True)
            return []

    def _fetch_groups_sync(
        self, creds: google.auth.credentials.Credentials, email: str
    ) -> typing.List[str]:
        """
        Synchronous helper to fetch groups using Cloud Identity Groups API.

        This uses the Cloud Identity Groups API to search for all security groups
        that a user is a transitive member of. Requires the cloud-identity.groups.readonly scope.

        The service account must have the Groups Reader role assigned in Google
        Workspace Admin Console. No domain-wide delegation is required.

        Args:
            creds: Google credentials to use (with cloud-identity.groups.readonly scope)
            email: User's email address

        Returns:
            List of group email addresses
        """
        try:
            logger.debug("_fetch_groups_sync() called for %s", email)

            # Build the Cloud Identity Groups API service
            logger.debug(
                "Building Cloud Identity Groups API service (cloudidentity/v1)"
            )
            service = googleapiclient.discovery.build(
                "cloudidentity", "v1", credentials=creds
            )

            logger.debug("Searching transitive security groups for %s", email)
            groups = []
            next_page_token = ""

            query_parts = [
                f"member_key_id == '{email.strip()}'",
                "'cloudidentity.googleapis.com/groups.discussion_forum' in labels",
            ]
            if self.customer_id:
                query_parts.append(f"parent == 'customers/{self.customer_id}'")
            query_str = " && ".join(query_parts)

            while True:
                query_params = urllib.parse.urlencode(
                    {
                        "query": query_str,
                        "page_size": 200,
                        "page_token": next_page_token,
                    }
                )
                request = (
                    service.groups()
                    .memberships()
                    .searchTransitiveGroups(parent="groups/-")
                )
                request.uri += "&" + query_params

                logger.debug(request.uri)
                response = request.execute()

                if "memberships" in response:
                    groups += [m["groupKey"]["id"] for m in response["memberships"]]

                if "nextPageToken" in response:
                    next_page_token = response["nextPageToken"]
                else:
                    next_page_token = ""

                if len(next_page_token) == 0:
                    break

            logger.debug(
                "Extracted %d group emails from Cloud Identity API response",
                len(groups),
            )
            return groups

        except Exception:
            # Return empty list on any error
            logger.error("Cloud Identity API call failed for %s", email, exc_info=True)
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
        if isinstance(self._group_cache, cachetools.TTLCache):
            return self._group_cache.pop(email, _SENTINEL) is not _SENTINEL
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
        if isinstance(self._token_cache, cachetools.TTLCache):
            return self._token_cache.pop(token, _SENTINEL) is not _SENTINEL
        return False
