"""
Pytest configuration and fixtures for workspace-auth-middleware tests.
"""

import pytest
import google.auth.credentials
from unittest.mock import Mock, MagicMock


@pytest.fixture
def mock_google_credentials():
    """
    Mock Google credentials for testing.

    Returns a mock Credentials object that can be used with the backend.
    """
    creds = Mock(spec=google.auth.credentials.Credentials)
    creds.token = "mock_access_token"
    creds.valid = True
    creds.expired = False
    creds.refresh = Mock()

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
def mock_cloud_identity_service(sample_groups):
    """
    Mock Google Cloud Identity service for testing group fetching.
    """
    service = MagicMock()

    # Mock the groups().memberships().searchTransitiveGroups().execute() chain
    # Cloud Identity API returns memberships with groupKey containing the id
    api_response = {
        "memberships": [{"groupKey": {"id": group}} for group in sample_groups]
    }

    # Configure the chain with explicit return values
    service.groups.return_value.memberships.return_value.searchTransitiveGroups.return_value.execute.return_value = api_response

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
    """Test delegated admin email for Admin SDK."""
    return "admin@example.com"


@pytest.fixture
def mock_admin_directory_service():
    """
    Mock Admin SDK Directory API service for testing group fetching.

    Flat structure (no nesting):
    - user@example.com is a direct member of team-a@example.com, devs@example.com
    """
    service = MagicMock()

    # groups().list(userKey=email) returns direct groups
    service.groups.return_value.list.return_value.execute.return_value = {
        "groups": [
            {"email": "team-a@example.com", "name": "Team A"},
            {"email": "devs@example.com", "name": "Developers"},
        ]
    }

    return service


@pytest.fixture
def mock_admin_directory_service_with_nesting():
    """
    Mock Admin SDK Directory API service with nested group structure.

    Structure:
    - user@example.com -> direct member of [team-a@example.com, devs@example.com]
    - user@example.com -> transitive member of all-teams@example.com (via team-a)
    - user@example.com -> transitive member of org@example.com (via team-a -> all-teams)
    - user@example.com -> NOT a member of unrelated@example.com
    """
    service = MagicMock()

    # groups().list(userKey=email) returns user's direct groups
    service.groups.return_value.list.return_value.execute.return_value = {
        "groups": [
            {"email": "team-a@example.com", "name": "Team A"},
            {"email": "devs@example.com", "name": "Developers"},
        ]
    }

    # members().hasMember(groupKey=..., memberKey=...) checks transitive membership
    def has_member_side_effect(groupKey, memberKey):
        mock_request = MagicMock()
        # user@example.com is a transitive member of these groups
        membership = {
            ("all-teams@example.com", "user@example.com"): True,
            ("org@example.com", "user@example.com"): True,
        }
        is_member = membership.get((groupKey, memberKey), False)
        mock_request.execute.return_value = {"isMember": is_member}
        return mock_request

    service.members.return_value.hasMember.side_effect = has_member_side_effect

    return service
