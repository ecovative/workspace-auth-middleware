# Caching Configuration

Caching is enabled by default and dramatically reduces latency by avoiding repeated Google API calls.

## Performance Impact

| Operation | Without Cache | With Cache (hit) |
|-----------|--------------|-------------------|
| Token verification | 50-200ms | <1ms |
| Group fetching | 100-500ms | <1ms |

## Configuration

```python
backend = WorkspaceAuthBackend(
    client_id="...",
    # Token cache (default: enabled)
    enable_token_cache=True,
    token_cache_ttl=300,        # seconds (default: 5 minutes)
    token_cache_maxsize=1000,   # max entries (default: 1000)
    # Group cache (default: enabled)
    enable_group_cache=True,
    group_cache_ttl=300,        # seconds (default: 5 minutes)
    group_cache_maxsize=500,    # max entries (default: 500)
)
```

## Disable Caching

```python
backend = WorkspaceAuthBackend(
    client_id="...",
    enable_token_cache=False,
    enable_group_cache=False,
)
```

## TTL Guidelines

- **Security-sensitive apps**: 60-120s (faster revocation)
- **Standard apps**: 300s (default, good balance)
- **Performance-focused**: 600-900s (fewer API calls)

## Cache Management

```python
# Statistics
stats = backend.get_cache_stats()
stats["token_cache"]["hit_rate"]  # float, e.g. 0.95
stats["token_cache"]["size"]      # current entries
stats["group_cache"]["hit_rate"]

# Clear all caches
backend.clear_caches()

# Invalidate specific entries
backend.invalidate_token("specific_token")
backend.invalidate_user_groups("user@example.com")
```

## Monitoring Endpoint Example

```python
@app.get("/cache/stats")
@require_group("admins@example.com")
async def cache_stats(request):
    return backend.get_cache_stats()
```

## Trade-offs

- Group membership changes take up to TTL to reflect
- Revoked tokens remain valid until cache expires
- Memory usage scales with maxsize (configurable)
