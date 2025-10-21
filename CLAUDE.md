# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python package that provides ASGI middleware for authentication against Google Workspace. The project uses Poetry for dependency management and includes comprehensive pre-commit hooks for code quality.

## ASGI Middleware Architecture

This middleware is built on top of [Starlette's AuthenticationMiddleware](https://www.starlette.io/authentication/), making it compatible with FastAPI, Starlette, and other ASGI frameworks.

### Architecture Overview

The package follows Starlette's authentication patterns:

1. **Authentication Backend** (`WorkspaceAuthBackend`): Implements `AuthenticationBackend` interface
   - Validates Google OAuth2 ID tokens
   - Fetches user's Google Workspace groups
   - Returns `(AuthCredentials, WorkspaceUser)` tuple

2. **Middleware** (`WorkspaceAuthMiddleware`): Extends `AuthenticationMiddleware`
   - Convenience wrapper around Starlette's middleware
   - Automatically configures backend with Google Workspace settings
   - Populates `request.user` and `request.auth`

3. **User Model** (`WorkspaceUser`): Extends `BaseUser`
   - Provides Starlette-compatible interface (`.is_authenticated`, `.display_name`)
   - Adds Google Workspace-specific properties (`.groups`, `.domain`)
   - Helper methods for group checks (`.has_group()`, `.has_any_group()`, `.has_all_groups()`)

### Authentication Backend Pattern

```python
from starlette.authentication import AuthenticationBackend, AuthCredentials
from starlette.requests import HTTPConnection

class WorkspaceAuthBackend(AuthenticationBackend):
    async def authenticate(self, conn: HTTPConnection):
        # Extract and validate Google ID token from Authorization header
        # Returns: (AuthCredentials, WorkspaceUser) or None
        pass
```

The backend:
- Returns `(AuthCredentials, WorkspaceUser)` for valid authentication
- Returns `None` for anonymous/unauthenticated requests
- Raises `AuthenticationError` for invalid credentials

Scopes are automatically populated:
- `"authenticated"` - User is authenticated
- `"group:<group_email>"` - User belongs to specific group

### Integration with Frameworks

**Option 1: Use convenience wrapper**
```python
from workspace_auth_middleware import WorkspaceAuthMiddleware

app.add_middleware(
    WorkspaceAuthMiddleware,
    client_id="...",
    required_domains=["example.com"],
)
```

**Option 2: Use Starlette's middleware directly**
```python
from starlette.middleware.authentication import AuthenticationMiddleware
from workspace_auth_middleware import WorkspaceAuthBackend

backend = WorkspaceAuthBackend(client_id="...", required_domains=["example.com"])
app.add_middleware(AuthenticationMiddleware, backend=backend)
```

### Decorator Patterns

Two approaches for route protection:

**1. Custom decorators (Google Workspace-specific)**
```python
from workspace_auth_middleware import require_auth, require_group

@require_auth
async def protected_route(request): ...

@require_group("admins@example.com")
async def admin_route(request): ...
```

**2. Starlette's scope-based decorator**
```python
from workspace_auth_middleware import requires  # Re-exported

@requires("authenticated")
async def protected_route(request): ...

@requires("group:admins@example.com")
async def admin_route(request): ...
```

### Key Design Principles

1. **Extends Starlette**: Built on Starlette's authentication system for maximum compatibility
2. **Stateless**: Backend doesn't modify state outside `__init__`
3. **ASGI Spec Compliance**: Works with any ASGI framework
4. **Type-Safe**: Full type hints using Starlette's interfaces
5. **Async First**: All operations are async-aware
6. **High Performance**: Built-in caching reduces API calls and response times

### Performance and Caching

The backend includes built-in TTL-based caching to dramatically improve performance:

**Without caching:**
- Token verification: ~50-200ms per request (hits Google's API)
- Group fetching: ~100-500ms per request (hits Admin SDK)
- Total: 100-700ms per authenticated request

**With caching (enabled by default):**
- Token verification: <1ms for cache hits
- Group fetching: <1ms for cache hits
- Total: <5ms for repeated requests

**Configuration:**
```python
backend = WorkspaceAuthBackend(
    client_id="...",
    # Token cache (default: enabled)
    enable_token_cache=True,
    token_cache_ttl=300,        # 5 minutes
    token_cache_maxsize=1000,   # Max 1000 tokens
    # Group cache (default: enabled)
    enable_group_cache=True,
    group_cache_ttl=300,        # 5 minutes
    group_cache_maxsize=500,    # Max 500 users
)
```

**Cache management:**
```python
# Get statistics
stats = backend.get_cache_stats()
print(f"Hit rate: {stats['token_cache']['hit_rate']:.2%}")

# Clear caches
backend.clear_caches()

# Invalidate specific entries
backend.invalidate_token("token_to_remove")
backend.invalidate_user_groups("user@example.com")
```

**Trade-offs:**
- Slightly stale data (group changes take up to TTL to reflect)
- Memory usage (configurable via maxsize)
- Token revocation delay (revoked tokens remain valid until cache expires)

Use shorter TTLs (60-120s) for security-sensitive applications, longer (300-900s) for better performance.

### Credentials Configuration

The backend supports multiple credential sources:

**1. Default Application Credentials (easiest)**
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```
The backend automatically loads these credentials when `fetch_groups=True`.

**2. Explicit credentials**
```python
from google.oauth2 import service_account

credentials = service_account.Credentials.from_service_account_file(
    'service-account-key.json',
    scopes=['https://www.googleapis.com/auth/admin.directory.group.readonly']
)

backend = WorkspaceAuthBackend(
    client_id="...",
    credentials=credentials,
    delegated_admin="admin@example.com",
)
```

**3. No credentials (group fetching disabled)**
```python
backend = WorkspaceAuthBackend(
    client_id="...",
    fetch_groups=False,  # No credentials needed
)
```

Group fetching requires:
- Service account with domain-wide delegation
- Admin SDK scope: `https://www.googleapis.com/auth/admin.directory.group.readonly`
- Admin email for delegation (`delegated_admin` parameter)
- `google-api-python-client` package installed

## Development Environment Setup

```bash
# Install dependencies
poetry install

# Install pre-commit hooks
poetry run pre-commit install
```

## Common Commands

### Testing
```bash
# Run all tests in parallel (excludes performance tests)
poetry run pytest -n 4 tests

# Run tests with coverage
poetry run pytest --cov=workspace_auth_middleware tests

# Run a single test file
poetry run pytest tests/test_filename.py

# Run tests in verbose mode
poetry run pytest -v tests

# Run performance benchmarks
poetry run pytest tests/test_performance.py --benchmark-only

# Save benchmark baseline
poetry run pytest tests/test_performance.py --benchmark-only --benchmark-save=baseline

# Compare against baseline
poetry run pytest tests/test_performance.py --benchmark-only --benchmark-compare=0001

# Run integration tests with real credentials
export RUN_INTEGRATION_TESTS=true
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_WORKSPACE_DOMAIN="example.com"
poetry run pytest tests/test_integration_adc.py -v

# Or use the convenience script
./run_integration_tests.sh

# Check credential configuration
./check_credentials.sh
```

### Code Quality
```bash
# Format code with Ruff
poetry run ruff format

# Lint code with Ruff
poetry run ruff check

# Type check with MyPy (excludes docs and tests)
poetry run mypy --config-file pyproject.toml

# Validate YAML files
poetry run yamllint .

# Check all quality tools at once (via pre-commit)
poetry run pre-commit run --all-files
```

### Package Management
```bash
# Validate Poetry configuration
poetry check

# Check license compliance (ignores MPL 2.0)
poetry run licensecheck -0 --ignore-licenses "MPL 2.0"
```

## Project Structure

- `workspace_auth_middleware/` - Main package source code
  - `__init__.py` - Package initialization and exports
  - `middleware.py` - WorkspaceAuthMiddleware implementation
  - `auth.py` - WorkspaceAuthBackend with token validation and caching
  - `models.py` - WorkspaceUser and AnonymousUser models
  - `decorators.py` - Route protection decorators (@require_auth, @require_group, @require_scope)
- `tests/` - Comprehensive test suite
  - `test_auth_backend.py` - Authentication backend tests
  - `test_decorators.py` - Decorator functionality tests
  - `test_middleware.py` - Middleware integration tests
  - `test_integration_adc.py` - Integration tests with real Google credentials
  - `test_performance.py` - Performance benchmarking tests
  - `conftest.py` - Shared pytest fixtures
- `examples/` - Example applications and testing tools
  - `manual_testing.py` - FastAPI test server for real credential testing
  - `caching_example.py` - Caching configuration examples
  - `setup_env.sh` - Interactive environment configuration wizard
  - `README.md` - Examples documentation
- `pyproject.toml` - Project configuration and dependencies
- `pytest.ini` - Pytest configuration including benchmark settings
- `TESTING_GUIDE.md` - Complete guide for testing with real credentials
- `check_credentials.sh` - Credential verification script
- `run_integration_tests.sh` - Integration test runner

## Key Dependencies

### Required
- `google-auth` (>=2.41.1, <3.0.0) - Google authentication library for OAuth2 ID token validation
- `starlette` (>=0.27.0, <1.0.0) - ASGI framework providing authentication interfaces
- `google-api-python-client` (>=2.0.0, <3.0.0) - Required for group fetching via Admin SDK
- `cachetools` (>=5.0.0, <7.0.0) - TTL-based caching for performance optimization
- `requests` (>=2.32.5, <3.0.0) - HTTP library for API calls
- Python 3.12+ required

### Development Dependencies
- `pytest` - Testing framework with async support
- `pytest-xdist` - Parallel test execution
- `pytest-benchmark` - Performance benchmarking
- `pytest-cov` - Test coverage reporting
- `ruff` - Fast Python linter and formatter
- `mypy` - Static type checker
- `pre-commit` - Git hook management
- `uvicorn` - ASGI server for testing
- `fastapi` - For example applications

## Pre-commit Hooks

All commits automatically run:
1. Poetry configuration validation
2. Ruff formatting and linting
3. YAML linting
4. MyPy type checking (excludes docs/tests)
5. License compliance checking
6. Full pytest suite with 4 parallel workers

These same checks will run in CI/CD, so ensure pre-commit is installed to catch issues early.

## Testing with Real Google Credentials

The project includes comprehensive tools for testing with real Google Workspace credentials:

### Quick Start

1. **Check current configuration:**
   ```bash
   ./check_credentials.sh
   ```

2. **Run interactive setup:**
   ```bash
   cd examples && ./setup_env.sh
   source .env
   cd ..
   ```

3. **Start test server:**
   ```bash
   poetry run python examples/manual_testing.py
   ```

4. **Get a token and test:**
   ```bash
   TOKEN=$(gcloud auth print-identity-token)
   curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/me
   ```

### Integration Tests

Integration tests verify the middleware works with real Google APIs:

```bash
# Set required environment variables
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_WORKSPACE_DOMAIN="example.com"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
export GOOGLE_DELEGATED_ADMIN="admin@example.com"
export TEST_USER_EMAIL="testuser@example.com"

# Run integration tests
./run_integration_tests.sh

# Or run specific test
./run_integration_tests.sh TestADCIntegration::test_group_fetching_with_adc
```

See `TESTING_GUIDE.md` for complete documentation including:
- Getting Google ID tokens (3 different methods)
- Service account setup
- Troubleshooting common issues
- Testing scenarios

## Reference Documentation

### ASGI Middleware Implementation
- **Starlette Middleware**: https://www.starlette.dev/middleware/
  - Pure ASGI middleware patterns
  - BaseHTTPMiddleware class
  - Middleware state management best practices
- **FastAPI Middleware**: https://fastapi.tiangolo.com/advanced/middleware/
  - Using `app.add_middleware()` for proper integration
  - Middleware execution order
  - Built-in middleware examples (HTTPS, TrustedHost, GZip)

### Authentication Patterns
- **Starlette Authentication**: https://www.starlette.dev/authentication/
  - AuthenticationBackend interface
  - AuthenticationMiddleware usage
  - request.user and request.auth population
  - Custom authentication error handling

### Framework Documentation
- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **Starlette Docs**: https://www.starlette.dev/
