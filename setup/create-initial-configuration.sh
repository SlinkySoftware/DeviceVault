#!/usr/bin/env bash
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
