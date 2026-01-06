#!/usr/bin/env bash
set -euo pipefail

# Resolve repo root (script is in setup/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT/backend"

# Ensure Python uses system python3 (virtualenvs ok if activated)
PYTHON=${PYTHON:-python3}

# Idempotent: create admin user if missing, otherwise reset password
$PYTHON manage.py shell <<'PY'
from django.contrib.auth import get_user_model
User = get_user_model()
u = User.objects.filter(username='admin').first()
if not u:
	User.objects.create_superuser('admin', 'admin@example.com', 'admin')
	print('Created admin / admin')
else:
	u.set_password('admin')
	u.save()
	print('Password reset to: admin')
PY

echo "Done. Admin username: admin, password: admin"
