# DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
# Copyright (C) 2026, Slinky Software
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_admin(user) -> bool:
    """Application administrators: staff or superusers."""
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


class IsAdmin(BasePermission):
    """Only application administrators."""

    def has_permission(self, request, view):
        return is_admin(request.user)


class IsAdminOrReadOnly(BasePermission):
    """Any authenticated user may read; only administrators may write.

    For reference data that device editors need to choose from (types,
    policies, locations...) but must not change.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return is_admin(request.user)
