#!/usr/bin/env bash
#
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
#

set -euo pipefail

# Script location helpers
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT/backend"

# Allow overriding python executable
PYTHON=${PYTHON:-python3}

echo "Running database migrations..."
$PYTHON manage.py migrate --run-syncdb

echo "Creating initial users (admin/admin and user/user)..."
$PYTHON manage.py shell <<'PY'
from django.contrib.auth import get_user_model
User = get_user_model()

# Admin (superuser)
admin = User.objects.filter(username='admin').first()
if not admin:
    User.objects.create_superuser('admin', 'admin@example.com', 'admin')
    print('Created admin / admin')
else:
    admin.set_password('admin')
    admin.is_staff = True
    admin.is_superuser = True
    admin.save()
    print('Reset admin password to: admin')

# Non-admin demonstration user
user = User.objects.filter(username='user').first()
if not user:
    User.objects.create_user('user', 'user@example.com', 'user')
    print('Created user / user')
else:
    user.set_password('user')
    user.is_staff = False
    user.is_superuser = False
    user.save()
    print('Reset user password to: user')

# Default dashboard layout (matches frontend defaultOrder)
from core.models import DashboardLayout
default_layout = [
    { 'id': 'devices', 'width': 3, 'height': 220 },
    { 'id': 'backups', 'width': 3, 'height': 220 },
    { 'id': 'avgtime', 'width': 3, 'height': 220 },
    { 'id': 'successrate', 'width': 3, 'height': 220 },
    { 'id': 'chart', 'width': 12, 'height': 300 },
    { 'id': 'activity', 'width': 12, 'height': 300 }
]

# Ensure admin has a dashboard layout
if admin:
    layout_obj, created = DashboardLayout.objects.get_or_create(user=admin, defaults={'layout': default_layout})
    if not created:
        layout_obj.layout = default_layout
        layout_obj.save()
    print(f"Admin dashboard {'created' if created else 'updated'}")

# Ensure demo user has a dashboard layout
if user:
    layout_obj, created = DashboardLayout.objects.get_or_create(user=user, defaults={'layout': default_layout})
    if not created:
        layout_obj.layout = default_layout
        layout_obj.save()
    print(f"User dashboard {'created' if created else 'updated'}")
PY

echo "Initial configuration complete."
