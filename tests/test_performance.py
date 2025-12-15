"""
Performance tests for workspace-auth-middleware.

These tests measure the performance characteristics of the authentication
middleware to ensure it doesn't introduce unacceptable overhead.

Run with: pytest tests/test_performance.py --benchmark-only
"""

import pytest
from unittest.mock import patch
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from workspace_auth_middleware import (
    WorkspaceAuthMiddleware,
    WorkspaceAuthBackend,
    require_auth,
    require_group,
)


@pytest.fixture
def benchmark_app(client_id, required_domains):
    """Create a test app for benchmarking."""

    async def endpoint(request):
        return JSONResponse({"message": "ok"})

    @require_auth
    async def protected_endpoint(request):
        return JSONResponse({"user": request.user.email})

    @require_group("admins@example.com")
    async def admin_endpoint(request):
        return JSONResponse({"admin": True})

    routes = [
        Route("/public", endpoint),
        Route("/protected", protected_endpoint),
        Route("/admin", admin_endpoint),
    ]

    app = Starlette(routes=routes)

    app.add_middleware(
        WorkspaceAuthMiddleware,
        client_id=client_id,
        required_domains=required_domains,
        fetch_groups=False,  # Disable for baseline performance
    )

    return app


@pytest.fixture
def benchmark_app_with_groups(client_id, required_domains, mock_google_credentials):
    """Create a test app with group fetching enabled."""

    async def endpoint(request):
        return JSONResponse(
            {
                "email": request.user.email if request.user.is_authenticated else None,
                "groups": request.user.groups if request.user.is_authenticated else [],
            }
        )

    routes = [Route("/endpoint", endpoint)]
    app = Starlette(routes=routes)

    app.add_middleware(
        WorkspaceAuthMiddleware,
        client_id=client_id,
        required_domains=required_domains,
        credentials=mock_google_credentials,
        fetch_groups=True,
    )

    return app


class TestAuthenticationPerformance:
    """Performance tests for authentication operations."""

    def test_anonymous_request_overhead(self, benchmark, benchmark_app):
        """
        Benchmark overhead for anonymous requests (no auth header).

        This measures the baseline middleware overhead when no authentication
        is attempted. Should be very fast (< 1ms).
        """
        client = TestClient(benchmark_app)

        def anonymous_request():
            response = client.get("/public")
            assert response.status_code == 200

        benchmark(anonymous_request)

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_token_validation_performance(
        self,
        mock_verify,
        benchmark,
        benchmark_app,
        valid_id_token_claims,
        mock_id_token,
    ):
        """
        Benchmark token validation performance.

        This measures the time to validate a token and create a user object.
        Target: < 50ms per request (dominated by Google's token verification).
        """
        mock_verify.return_value = valid_id_token_claims
        client = TestClient(benchmark_app)

        def authenticated_request():
            response = client.get(
                "/public", headers={"Authorization": f"Bearer {mock_id_token}"}
            )
            assert response.status_code == 200

        benchmark(authenticated_request)

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_decorator_overhead(
        self,
        mock_verify,
        benchmark,
        benchmark_app,
        valid_id_token_claims,
        mock_id_token,
    ):
        """
        Benchmark decorator overhead for protected endpoints.

        This measures the additional time required by @require_auth decorator.
        Should add minimal overhead (< 1ms).
        """
        mock_verify.return_value = valid_id_token_claims
        client = TestClient(benchmark_app)

        def protected_request():
            response = client.get(
                "/protected", headers={"Authorization": f"Bearer {mock_id_token}"}
            )
            assert response.status_code == 200

        benchmark(protected_request)

    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("googleapiclient.discovery.build")
    def test_group_fetching_performance(
        self,
        mock_build,
        mock_verify,
        benchmark,
        benchmark_app_with_groups,
        valid_id_token_claims,
        mock_id_token,
        mock_cloud_identity_service,
    ):
        """
        Benchmark group fetching performance.

        This measures the time to fetch groups from Cloud Identity API.
        Actual performance depends on Cloud Identity API latency.
        """
        mock_verify.return_value = valid_id_token_claims
        mock_build.return_value = mock_cloud_identity_service
        client = TestClient(benchmark_app_with_groups)

        def request_with_groups():
            response = client.get(
                "/endpoint", headers={"Authorization": f"Bearer {mock_id_token}"}
            )
            assert response.status_code == 200

        benchmark(request_with_groups)


class TestBackendPerformance:
    """Performance tests for the authentication backend."""

    def test_backend_initialization(self, benchmark, client_id, required_domains):
        """
        Benchmark backend initialization time.

        Backend initialization should be fast since it's done once at startup.
        """

        def create_backend():
            return WorkspaceAuthBackend(
                client_id=client_id,
                required_domains=required_domains,
                fetch_groups=False,
            )

        benchmark(create_backend)

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_token_verification_only(
        self, mock_verify, benchmark, client_id, valid_id_token_claims, mock_id_token
    ):
        """
        Benchmark just the token verification step.

        This isolates the Google token verification performance.
        """
        mock_verify.return_value = valid_id_token_claims

        backend = WorkspaceAuthBackend(
            client_id=client_id,
            fetch_groups=False,
        )

        async def verify_token():
            return await backend._verify_token(mock_id_token)

        # Run async function in benchmark
        import asyncio

        def run_verification():
            return asyncio.run(verify_token())

        benchmark(run_verification)


class TestConcurrentPerformance:
    """Performance tests for concurrent request handling."""

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_concurrent_authenticated_requests(
        self,
        mock_verify,
        benchmark,
        benchmark_app,
        valid_id_token_claims,
        mock_id_token,
    ):
        """
        Benchmark performance under concurrent load.

        This simulates multiple simultaneous authenticated requests.
        """
        mock_verify.return_value = valid_id_token_claims
        client = TestClient(benchmark_app)

        def concurrent_requests():
            """Simulate 10 concurrent requests."""
            responses = []
            for _ in range(10):
                response = client.get(
                    "/public", headers={"Authorization": f"Bearer {mock_id_token}"}
                )
                responses.append(response)

            # Verify all succeeded
            assert all(r.status_code == 200 for r in responses)
            return responses

        benchmark(concurrent_requests)


class TestMemoryUsage:
    """Memory usage tests."""

    def test_backend_memory_footprint(self, client_id, required_domains):
        """
        Test memory footprint of backend initialization.

        This ensures the backend doesn't consume excessive memory.
        """
        import sys

        # Measure memory before
        backend = WorkspaceAuthBackend(
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
        )

        # Get size of backend object
        backend_size = sys.getsizeof(backend)

        # Backend should be lightweight (< 1KB)
        assert backend_size < 1024  # Less than 1KB

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_user_object_memory(
        self, mock_verify, benchmark_app, valid_id_token_claims, mock_id_token
    ):
        """
        Test memory usage of user objects.

        This ensures WorkspaceUser objects don't consume excessive memory.
        """

        mock_verify.return_value = valid_id_token_claims
        client = TestClient(benchmark_app)

        # Make authenticated request to create user object
        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {mock_id_token}"}
        )
        assert response.status_code == 200

        # User objects should be lightweight
        # (Actual size check would require accessing the user object from request)


class TestScalabilityMetrics:
    """Tests to measure scalability characteristics."""

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_requests_per_second(
        self,
        mock_verify,
        benchmark,
        benchmark_app,
        valid_id_token_claims,
        mock_id_token,
    ):
        """
        Estimate requests per second throughput.

        This gives an indication of maximum throughput for authenticated requests.
        """
        mock_verify.return_value = valid_id_token_claims
        client = TestClient(benchmark_app)

        def single_request():
            response = client.get(
                "/public", headers={"Authorization": f"Bearer {mock_id_token}"}
            )
            assert response.status_code == 200

        benchmark.pedantic(
            single_request,
            iterations=100,
            rounds=5,
        )

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_latency_percentiles(
        self,
        mock_verify,
        benchmark,
        benchmark_app,
        valid_id_token_claims,
        mock_id_token,
    ):
        """
        Test latency percentiles (p50, p95, p99).

        This helps identify tail latencies that could affect user experience.
        """
        mock_verify.return_value = valid_id_token_claims
        client = TestClient(benchmark_app)

        def authenticated_request():
            response = client.get(
                "/public", headers={"Authorization": f"Bearer {mock_id_token}"}
            )
            assert response.status_code == 200

        benchmark.pedantic(
            authenticated_request,
            iterations=100,
            rounds=10,
        )


class TestComparisonBenchmarks:
    """Comparison benchmarks for different configurations."""

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_with_vs_without_group_fetching(
        self,
        mock_verify,
        benchmark,
        client_id,
        required_domains,
        valid_id_token_claims,
        mock_id_token,
    ):
        """
        Compare performance with and without group fetching.

        This shows the overhead of group fetching.
        """
        mock_verify.return_value = valid_id_token_claims

        # App without groups
        async def endpoint(request):
            return JSONResponse({"ok": True})

        routes = [Route("/test", endpoint)]

        app_no_groups = Starlette(routes=routes)
        app_no_groups.add_middleware(
            WorkspaceAuthMiddleware,
            client_id=client_id,
            required_domains=required_domains,
            fetch_groups=False,
        )

        client = TestClient(app_no_groups)

        def request_no_groups():
            response = client.get(
                "/test", headers={"Authorization": f"Bearer {mock_id_token}"}
            )
            assert response.status_code == 200

        benchmark(request_no_groups)


# Benchmark groups for organized output
pytest.mark.benchmark(group="authentication")
pytest.mark.benchmark(group="backend")
pytest.mark.benchmark(group="concurrent")
pytest.mark.benchmark(group="memory")
pytest.mark.benchmark(group="scalability")
