# TODO: Codebase Improvements

## Critical / High Severity

- [x] **1. Hardcoded customer ID in Cloud Identity query** — `auth.py` — The customer ID `C028qv0z5` was hardcoded in the group-fetching query. Added configurable `customer_id` parameter to `WorkspaceAuthBackend` and `WorkspaceAuthMiddleware`. Query now omits `parent ==` clause when `customer_id` is `None`.

- [x] **2. `email_verified` claim is never checked** — `auth.py` — Added `email_verified` check after token verification. Rejects tokens where `email_verified` is `False` or absent.

- [x] **3. Synchronous token verification blocks the event loop** — `auth.py` — Extracted `_verify_token_sync` and wrapped in `asyncio.get_running_loop().run_in_executor()`, matching the existing `_fetch_groups_sync` pattern.

- [x] **4. `PermissionDenied` results in 500 errors** — `decorators.py` — Changed `PermissionDenied` base class from `Exception` to `starlette.exceptions.HTTPException` with `status_code=403`. Starlette/FastAPI handle it automatically.

## Security

- [x] **5. Token stored as raw JWT in cache key** — `auth.py` — Cache keys are now SHA-256 hashes of tokens instead of raw JWTs. `invalidate_token()` API unchanged (hashing is internal).

- [x] **6. Email interpolated directly into Cloud Identity query** — `auth.py` — Added regex validation of email format before interpolation into Cloud Identity query. Invalid emails return empty groups.

- [x] **7. Allowed domains leaked in error messages** — `auth.py` — Error message changed to generic `"Domain not allowed: {domain}"`. Full domain list remains in WARNING log for operators.

- [x] **8. Sensitive data logged at INFO level** — `auth.py` — Changed 5 happy-path `logger.info()` calls that logged emails, groups, and scopes to `logger.debug()`.

## Bugs

- [x] **9. Double exception wrapping in `_verify_token`** — `auth.py` — Added `except AuthenticationError: raise` before the broad `except Exception` block in `_verify_token_sync`.

- [x] **10. TOCTOU race in cache access** — `auth.py` — Replaced `if x in cache` / `cache[x]` with `.get(key, _SENTINEL)` pattern. Replaced `if x in cache: del cache[x]` with `.pop(x, None)` in invalidation methods.

- [x] **11. Deprecated `asyncio.get_event_loop()`** — `auth.py` — Replaced with `asyncio.get_running_loop()`.

## API Design

- [x] **12. Middleware wrapper missing cache/session parameters** — `middleware.py` — `WorkspaceAuthMiddleware` now forwards all cache params (`enable_token_cache`, `token_cache_ttl`, `token_cache_maxsize`, `enable_group_cache`, `group_cache_ttl`, `group_cache_maxsize`) and `enable_session_auth` to the backend.

- [x] **13. Middleware wrapper restricts `client_id` to `str`** — `middleware.py` — `client_id` now accepts `Union[str, List[str]]`, matching the backend.

- [x] **14. `require_scope` vs `require_group` inconsistency** — `decorators.py` — Added `require_all: bool = True` parameter to `require_scope`. Also fixed pre-existing bug where `require_scope` used nonexistent `AuthCredentials.has_scope()` instead of checking `auth.scopes`.

## Performance

- [x] **15. Google API service rebuilt on every group fetch** — `auth.py` — Cloud Identity service is now lazily built once and stored as `self._cloud_identity_service` for reuse across group fetches.

## Dependencies & Configuration

- [x] **16. `authlib` is a production dependency but only used in examples** — `pyproject.toml` — Moved `authlib` from production to dev dependencies via `poetry remove`/`poetry add --group dev`.

- [x] **17. `requests` listed but not directly imported** — `pyproject.toml` — Removed `requests` from production dependencies. Still available transitively via `google-auth`.

- [x] **18. Typo in project description** — `pyproject.toml` — Fixed "middlware" → "middleware".

- [x] **19. Module-level logger overrides application config** — `auth.py` — Replaced `setLevel(DEBUG)` and `handlers = []` with standard library pattern: `getLogger(__name__)` + `NullHandler()`.

## Testing Gaps

- [x] **20. Missing tests for:** Added tests for session-based authentication (8 tests), cache behavior including stats/invalidation/disabled mode (7 tests), `require_scope` decorator (4 tests), multi-client-ID fallback (2 tests), paginated group responses (1 test), and empty bearer token edge cases (2 tests).
