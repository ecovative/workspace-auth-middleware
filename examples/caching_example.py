"""
Example demonstrating caching functionality for improved performance.

This example shows:
1. How to enable/disable caching
2. Cache configuration options
3. How to monitor cache statistics
4. Cache invalidation
"""

import asyncio
import logging
from workspace_auth_middleware import WorkspaceAuthBackend

# Set up module-specific logger
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Create backend with caching enabled (default)
backend = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    workspace_domain="example.com",
    delegated_admin="admin@example.com",
    # Caching options (all optional, these are the defaults)
    enable_token_cache=True,
    token_cache_ttl=300,  # 5 minutes
    token_cache_maxsize=1000,  # Max tokens to cache
    enable_group_cache=True,
    group_cache_ttl=300,  # 5 minutes
    group_cache_maxsize=500,  # Max users to cache groups for
)


async def demo_caching():
    """Demonstrate caching behavior."""

    # First request - cache miss
    # This will hit Google's token verification API
    token = "mock_token_123"
    try:
        claims = await backend._verify_token(token)
        logger.info(f"First verification: {claims}")
    except Exception as e:
        logger.error(f"Token verification failed: {e}")

    # Second request with same token - cache hit!
    # This will return from cache without hitting Google
    try:
        claims = await backend._verify_token(token)
        logger.info(f"Second verification (from cache): {claims}")
    except Exception as e:
        logger.error(f"Token verification failed: {e}")

    # Get cache statistics
    stats = backend.get_cache_stats()
    logger.info("Cache Statistics:")
    logger.info(f"Token cache: {stats['token_cache']}")
    logger.info(f"Group cache: {stats['group_cache']}")

    # Cache invalidation example
    backend.invalidate_token(token)
    logger.info(f"Invalidated token: {token}")

    # This will be another cache miss
    try:
        claims = await backend._verify_token(token)
    except Exception:
        pass

    # Check stats again
    stats = backend.get_cache_stats()
    logger.info("Cache Statistics after invalidation:")
    logger.info(f"Token cache hits: {stats['token_cache']['hits']}")
    logger.info(f"Token cache misses: {stats['token_cache']['misses']}")
    logger.info(f"Cache hit rate: {stats['token_cache']['hit_rate']:.2%}")


# Configuration examples

# Disable caching entirely
backend_no_cache = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    workspace_domain="example.com",
    enable_token_cache=False,
    enable_group_cache=False,
)

# Custom cache TTLs
backend_custom_ttl = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    workspace_domain="example.com",
    token_cache_ttl=60,  # 1 minute (more aggressive)
    group_cache_ttl=900,  # 15 minutes (less aggressive)
)

# Larger cache sizes for high-traffic applications
backend_large_cache = WorkspaceAuthBackend(
    client_id="your-client-id.apps.googleusercontent.com",
    workspace_domain="example.com",
    token_cache_maxsize=10000,  # 10k tokens
    group_cache_maxsize=5000,  # 5k users
)


if __name__ == "__main__":
    # Caching is always available with workspace-auth-middleware
    logger.info("Caching is available and enabled!")
    asyncio.run(demo_caching())
