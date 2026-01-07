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
PY

echo "Initial configuration complete."
