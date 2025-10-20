"""
Models for Google Workspace authentication.

This module provides user models that extend Starlette's authentication interfaces.
"""

import typing
import starlette.authentication

__all__ = [
    "WorkspaceUser",
    "AnonymousUser",
]


class WorkspaceUser(starlette.authentication.BaseUser):
    """
    Represents an authenticated Google Workspace user.

    Extends Starlette's BaseUser to provide Google Workspace-specific attributes
    and methods for group-based authorization.

    Attributes:
        email: User's email address
        user_id: Google user ID
        name: User's display name
        groups: List of Google Workspace groups the user belongs to
        domain: The Google Workspace domain
    """

    def __init__(
        self,
        email: str,
        user_id: str,
        name: typing.Optional[str] = None,
        groups: typing.Optional[typing.List[str]] = None,
        domain: typing.Optional[str] = None,
    ):
        self.email = email
        self.user_id = user_id
        self.name = name or email
        self.groups = groups or []
        self.domain = domain

    @property
    def is_authenticated(self) -> bool:
        """Returns True if the user is authenticated (Starlette interface)."""
        return True

    @property
    def display_name(self) -> str:
        """Returns the user's display name (Starlette interface)."""
        return self.name

    @property
    def identity(self) -> str:
        """Returns the user's unique identifier (Starlette interface)."""
        return self.user_id

    def has_group(self, group: str) -> bool:
        """
        Check if user belongs to a specific group.

        Args:
            group: Google Workspace group email (e.g., "admins@example.com")

        Returns:
            True if user is a member of the group
        """
        return group in self.groups

    def has_any_group(self, groups: typing.List[str]) -> bool:
        """
        Check if user belongs to any of the specified groups.

        Args:
            groups: List of Google Workspace group emails

        Returns:
            True if user belongs to at least one of the groups
        """
        return any(group in self.groups for group in groups)

    def has_all_groups(self, groups: typing.List[str]) -> bool:
        """
        Check if user belongs to all of the specified groups.

        Args:
            groups: List of Google Workspace group emails

        Returns:
            True if user belongs to all of the groups
        """
        return all(group in self.groups for group in groups)

    def __repr__(self) -> str:
        return f"WorkspaceUser(email={self.email}, groups={self.groups})"


# Export Starlette's UnauthenticatedUser directly
# It provides the standard interface for anonymous users
AnonymousUser = starlette.authentication.UnauthenticatedUser
