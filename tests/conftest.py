"""
Pytest configuration and fixtures for workspace-auth-middleware tests.
"""

import pytest
from unittest.mock import Mock
from google.auth import credentials as google_credentials


@pytest.fixture
def mock_google_credentials():
    """
    Mock Google credentials for testing.

    Returns a mock Credentials object that can be used with the backend.
    """
    creds = Mock(spec=google_credentials.Credentials)
    creds.token = "mock_access_token"
    creds.valid = True
    creds.expired = False

    # Mock the with_subject method for domain-wide delegation
    delegated_creds = Mock(spec=google_credentials.Credentials)
    delegated_creds.token = "delegated_token"
    delegated_creds.valid = True
    delegated_creds.expired = False

    creds.with_subject = Mock(return_value=delegated_creds)

    return creds


@pytest.fixture
def valid_id_token_claims():
    """
    Sample claims from a valid Google ID token.
    """
    return {
        "iss": "https://accounts.google.com",
        "azp": "client-id.apps.googleusercontent.com",
        "aud": "client-id.apps.googleusercontent.com",
        "sub": "1234567890",
        "email": "user@example.com",
        "email_verified": True,
        "name": "Test User",
        "picture": "https://example.com/photo.jpg",
        "given_name": "Test",
        "family_name": "User",
        "iat": 1234567890,
        "exp": 1234571490,
    }


@pytest.fixture
def mock_id_token():
    """
    Generate a mock Google ID token string.
    """
    return "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJzdWIiOiIxMjM0NTY3ODkwIiwiZW1haWwiOiJ1c2VyQGV4YW1wbGUuY29tIiwibmFtZSI6IlRlc3QgVXNlciJ9.signature"


@pytest.fixture
def sample_groups():
    """
    Sample Google Workspace groups.
    """
    return [
        "admins@example.com",
        "developers@example.com",
        "team-leads@example.com",
    ]


@pytest.fixture
def mock_admin_sdk_service(sample_groups):
    """
    Mock Google Admin SDK service for testing group fetching.
    """
    service = Mock()
    groups_resource = Mock()
    list_method = Mock()

    # Mock the groups().list().execute() chain
    list_method.execute.return_value = {
        "groups": [{"email": group} for group in sample_groups]
    }
    groups_resource.list.return_value = list_method
    service.groups.return_value = groups_resource

    return service


@pytest.fixture
def client_id():
    """Test Google OAuth2 client ID."""
    return "test-client-id.apps.googleusercontent.com"


@pytest.fixture
def required_domains():
    """Test Google Workspace domains."""
    return ["example.com"]


@pytest.fixture
def delegated_admin():
    """Test admin email for domain-wide delegation."""
    return "admin@example.com"
