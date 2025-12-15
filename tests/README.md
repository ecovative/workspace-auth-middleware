# Tests for workspace-auth-middleware

This directory contains comprehensive tests for the workspace-auth-middleware package.

## Test Structure

- **`conftest.py`**: Shared pytest fixtures for all tests
- **`test_auth_backend.py`**: Tests for the authentication backend, including ADC loading and caching
- **`test_middleware.py`**: Tests for middleware integration with Starlette
- **`test_decorators.py`**: Tests for authentication and authorization decorators (@require_auth, @require_group, @require_scope)
- **`test_integration_adc.py`**: Integration tests using real Application Default Credentials
- **`test_performance.py`**: Performance benchmarks for authentication overhead, caching, and throughput

## Running Tests

### Install Test Dependencies

```bash
poetry install
```

### Run All Tests

```bash
# Run all tests except integration tests
poetry run pytest

# Run tests in parallel (faster)
poetry run pytest -n 4

# Run with coverage
poetry run pytest --cov=workspace_auth_middleware --cov-report=html
```

### Run Specific Test Files

```bash
# Run only backend tests
poetry run pytest tests/test_auth_backend.py

# Run only middleware tests
poetry run pytest tests/test_middleware.py

# Run only decorator tests
poetry run pytest tests/test_decorators.py
```

### Run Specific Tests

```bash
# Run a specific test class
poetry run pytest tests/test_auth_backend.py::TestWorkspaceAuthBackend

# Run a specific test method
poetry run pytest tests/test_auth_backend.py::TestWorkspaceAuthBackend::test_init_with_explicit_credentials
```

## Integration Tests with Application Default Credentials

The `test_integration_adc.py` file contains tests that use real Google credentials from your environment. These tests are **skipped by default** and must be explicitly enabled.

### Setup for ADC Integration Tests

1. **Set up Application Default Credentials** following the [official guide](https://cloud.google.com/docs/authentication/set-up-adc-local-dev-environment):

   ```bash
   # Option 1: Use gcloud CLI
   gcloud auth application-default login

   # Option 2: Set environment variable to service account key
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
   ```

2. **Ensure your service account has**:
   - Groups Reader role granted in Google Workspace Admin Console
   - Cloud Identity scope: `https://www.googleapis.com/auth/cloud-identity.groups.readonly`
   - Cloud Identity API enabled in Google Cloud Console

3. **Set required environment variables**:

   ```bash
   # Required for integration tests
   export RUN_INTEGRATION_TESTS=true
   export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
   export GOOGLE_WORKSPACE_DOMAIN="example.com"
   export GOOGLE_DELEGATED_ADMIN="admin@example.com"

   # Optional: test user email for group fetching tests
   export TEST_USER_EMAIL="testuser@example.com"
   ```

4. **Install dependencies** (if not already installed):

   ```bash
   poetry install
   ```

   Note: All required dependencies (including `google-api-python-client` and `cachetools`) are now installed by default.

### Run Integration Tests

```bash
# Run only integration tests
poetry run pytest tests/test_integration_adc.py

# Run all tests including integration tests
RUN_INTEGRATION_TESTS=true poetry run pytest
```

### What Integration Tests Verify

- ADC credentials can be loaded automatically
- Backend properly initializes with ADC
- Group fetching works with real Admin SDK API calls
- Middleware correctly uses ADC for authentication
- Error handling works when ADC is not available

## Performance Testing

The `test_performance.py` file contains comprehensive performance benchmarks to measure the middleware's overhead and ensure it doesn't introduce unacceptable latency.

### What Performance Tests Measure

- **Anonymous request overhead**: Baseline middleware overhead when no authentication is attempted (target: <10ms)
- **Token validation performance**: Time to validate a token and create user object (target: <50ms)
- **Decorator overhead**: Additional time required by `@require_auth` decorator (target: <1ms)
- **Group fetching performance**: Time to fetch groups from Admin SDK
- **Concurrent request handling**: Performance under simultaneous load
- **Memory usage**: Backend and user object memory footprint (target: <1KB for backend)
- **Requests per second**: Throughput estimation (target: >100 RPS with mocked services)
- **Latency percentiles**: p50, p95, p99 latencies to identify tail latencies

### Running Performance Tests

```bash
# Run only performance benchmarks
poetry run pytest tests/test_performance.py --benchmark-only

# Run benchmarks with specific comparisons
poetry run pytest tests/test_performance.py --benchmark-compare

# Run benchmarks and save results
poetry run pytest tests/test_performance.py --benchmark-autosave

# Generate benchmark histogram
poetry run pytest tests/test_performance.py --benchmark-histogram

# Run specific benchmark test
poetry run pytest tests/test_performance.py::TestAuthenticationPerformance::test_token_validation_performance --benchmark-only
```

### Understanding Benchmark Results

Pytest-benchmark provides detailed statistics for each test:

```
------------------------------------------------------------------------------------------ benchmark: 8 tests -----------------------------------------------------------------------------------------
Name (time in ms)                                      Min                 Max                Mean            StdDev              Median               IQR            Outliers     OPS            Rounds  Iterations
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
test_anonymous_request_overhead                     1.2345 (1.0)        2.3456 (1.0)        1.5678 (1.0)      0.1234 (1.0)        1.5432 (1.0)      0.0987 (1.0)          3;2  637.8947 (1.0)          50          10
test_token_validation_performance                  10.2345 (8.29)      15.3456 (6.54)      12.5678 (8.02)     0.8234 (6.67)      12.4321 (8.06)     0.9876 (10.0)         2;1   79.5678 (0.12)         40           5
```

Key metrics:
- **Mean**: Average execution time - primary metric for comparison
- **Min/Max**: Best and worst case timings
- **StdDev**: Standard deviation - lower is more consistent
- **Median**: Middle value - less affected by outliers
- **OPS**: Operations per second (1 / mean)

### Performance Baselines

Expected performance with mocked services:

| Test Category | Target | Notes |
|--------------|--------|-------|
| Anonymous requests | < 10ms | Baseline middleware overhead |
| Token validation | < 50ms | With mocked Google verification |
| Decorator overhead | < 1ms | Additional time for `@require_auth` |
| Group fetching | < 100ms | With mocked Admin SDK |
| Concurrent (10 reqs) | < 500ms | 10 sequential requests |
| Backend initialization | < 1ms | One-time startup cost |
| Throughput | > 100 RPS | With mocked services |

**Note**: Real-world performance will be slower due to:
- Actual Google token verification API calls (~50-200ms)
- Real Admin SDK API calls (~100-500ms)
- Network latency and external service response times

### Comparing Performance Across Changes

pytest-benchmark automatically numbers saved benchmarks (0001, 0002, etc.). When you save with a name, it becomes part of the filename like `0001_baseline.json`.

```bash
# Run benchmarks and save with a label
poetry run pytest tests/test_performance.py --benchmark-only --benchmark-save=baseline

# This creates: .benchmarks/Linux-CPython-3.12-64bit/0001_baseline.json

# Make code changes...

# Compare against the most recent benchmark (last run)
poetry run pytest tests/test_performance.py --benchmark-only --benchmark-compare

# Compare against a specific numbered benchmark
poetry run pytest tests/test_performance.py --benchmark-only --benchmark-compare=0001

# Compare and fail if performance degrades by more than 10%
poetry run pytest tests/test_performance.py --benchmark-only --benchmark-compare=0001 --benchmark-compare-fail=mean:10%

# List all saved benchmarks
poetry run pytest tests/test_performance.py --benchmark-only --benchmark-list
```

**Note**: Use the numbered prefix (e.g., `0001`) when comparing, not the label name (e.g., `baseline`).

**Workflow Example**:

```bash
# 1. Run initial baseline
poetry run pytest tests/test_performance.py --benchmark-only --benchmark-save=baseline
# Saves to: .benchmarks/Linux-CPython-3.12-64bit/0001_baseline.json

# 2. Make code changes to improve performance
# ... edit code ...

# 3. Run benchmarks again
poetry run pytest tests/test_performance.py --benchmark-only
# Auto-saves to: .benchmarks/Linux-CPython-3.12-64bit/0002_.json

# 4. Compare against baseline
poetry run pytest tests/test_performance.py --benchmark-only --benchmark-compare=0001
# Shows side-by-side comparison: NOW vs 0001_baseline

# 5. If satisfied, you can make this the new baseline (optional)
# Just commit 0001_baseline.json to git and ignore other benchmark files
```

### Memory Profiling

For detailed memory analysis:

```bash
# Run memory profiling on specific test
poetry run python -m memory_profiler tests/test_performance.py

# Profile specific function
poetry run mprof run pytest tests/test_performance.py::TestMemoryUsage
poetry run mprof plot
```

### Performance Test Categories

Run specific performance test categories:

```bash
# Authentication performance
poetry run pytest tests/test_performance.py::TestAuthenticationPerformance --benchmark-only

# Backend performance
poetry run pytest tests/test_performance.py::TestBackendPerformance --benchmark-only

# Concurrent performance
poetry run pytest tests/test_performance.py::TestConcurrentPerformance --benchmark-only

# Memory usage
poetry run pytest tests/test_performance.py::TestMemoryUsage --benchmark-only

# Scalability metrics
poetry run pytest tests/test_performance.py::TestScalabilityMetrics --benchmark-only

# Comparison benchmarks
poetry run pytest tests/test_performance.py::TestComparisonBenchmarks --benchmark-only
```

### CI/CD Integration

Example GitHub Actions configuration for performance testing:

```yaml
- name: Run performance tests
  run: |
    poetry run pytest tests/test_performance.py --benchmark-only --benchmark-json=benchmark.json

- name: Store benchmark results
  uses: benchmark-action/github-action-benchmark@v1
  with:
    tool: 'pytest'
    output-file-path: benchmark.json
    fail-on-alert: true
    alert-threshold: '150%'  # Alert if performance degrades by 50%
```

### Troubleshooting Performance Issues

If benchmarks fail or show unexpected results:

1. **High variability (large StdDev)**: System may be under load, close other applications
2. **Consistently slow**: Check if mocks are properly configured
3. **Memory tests failing**: Ensure clean test environment, run tests in isolation
4. **Concurrent tests failing**: May indicate thread-safety issues

```bash
# Run performance tests in isolation
poetry run pytest tests/test_performance.py::test_name --benchmark-only -x

# Increase warmup rounds for more stable results
poetry run pytest tests/test_performance.py --benchmark-only --benchmark-warmup=on

# Disable automatic comparison if baseline is stale
poetry run pytest tests/test_performance.py --benchmark-only --benchmark-disable-gc
```

## Test Categories

Tests are organized into categories using pytest markers:

```bash
# Run only integration tests
poetry run pytest -m integration

# Run only ADC tests
poetry run pytest -m adc

# Run only benchmark tests
poetry run pytest -m benchmark

# Skip slow tests
poetry run pytest -m "not slow"
```

## Mocking Strategy

Unit tests use mocking extensively to avoid external dependencies:

- **Google ID token verification** is mocked to avoid hitting Google's servers
- **Admin SDK calls** are mocked to avoid requiring real credentials
- **HTTP requests** use Starlette's TestClient for fast, synchronous testing

Integration tests use real credentials and may make actual API calls.

## Test Fixtures

Key fixtures available in `conftest.py`:

- `mock_google_credentials`: Mock credentials for testing
- `valid_id_token_claims`: Sample claims from a Google ID token
- `mock_id_token`: Mock token string
- `sample_groups`: Sample Google Workspace groups
- `mock_cloud_identity_service`: Mock Cloud Identity service for group fetching

## Debugging Failed Tests

### View detailed output

```bash
# Show print statements
poetry run pytest -s

# Show full traceback
poetry run pytest --tb=long

# Stop on first failure
poetry run pytest -x
```

### Run with debugging

```bash
# Drop into debugger on failure
poetry run pytest --pdb
```

### Check specific functionality

```bash
# Test only ADC loading
poetry run pytest tests/test_auth_backend.py::TestWorkspaceAuthBackend::test_init_with_default_credentials -v

# Test only group fetching
poetry run pytest tests/test_auth_backend.py::TestGroupFetching -v
```

## CI/CD Integration

Tests are configured to run in CI/CD pipelines:

- **Fast unit tests** run on every commit
- **Integration tests** can be enabled with environment variables
- **Coverage reports** can be generated for code quality metrics

```yaml
# Example GitHub Actions configuration
- name: Run tests
  run: |
    poetry run pytest -n 4 --cov=workspace_auth_middleware
  env:
    RUN_INTEGRATION_TESTS: false  # Disable in CI by default
```

## Contributing

When adding new tests:

1. Add unit tests for all new functionality
2. Mock external dependencies
3. Add docstrings explaining what's being tested
4. Update this README if adding new test categories
5. Ensure tests pass locally before submitting PR

```bash
# Run all quality checks
poetry run pre-commit run --all-files

# Run tests
poetry run pytest -n 4
```
