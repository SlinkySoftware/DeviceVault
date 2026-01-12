# DeviceVault

A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.

## License

This project is licensed under the terms of the **GNU General Public License v3.0** (GPLv3) or later version.

You can find the full text of the license in the [LICENSE](LICENSE.md) file or read it online at the [GNU Operating System website](https://www.gnu.org/licenses/gpl-3.0.html).

## Features

- **Plugin-Based Backup Methods**: Extensible architecture for supporting multiple device types
- **Flexible Connectivity**: SSH, API, and TFTP backup reception
- **Multiple Storage Backends**: Git (default), Local Filesystem, S3, Azure, GCS
- **RBAC**: Role-based access control with device group-based visibility
- **Authentication**: LDAP, SAML, Entra ID, and Local Auth support
- **Retention Policies**: Configurable backup retention by count, time, or size
- **Audit Logging**: Complete audit trail of all activities
- **Dashboard**: Real-time statistics and backup success rate charts
- **Backup Comparison**: Side-by-side diff view of configuration changes
- **Distributed Storage Pipeline**: Celery workers offload backup storage to Git or filesystem backends with strict worker routing and synchronous retrieval

## Architecture Documentation

- **[Storage Pipeline](docs/STORAGE_PIPELINE.md)**: Device collection → storage → retrieval workflow with Celery worker routing

## Technology Stack

- **Backend**: Python 3.13+ with Django 6.0
- **Frontend**: Vue 3 with Quasar Framework
- **Database**: SQLite (default), PostgreSQL, or MySQL
- **API**: Django REST Framework

## Quick Start

```bash
# Start the application
./devicevault.sh start

# Access at http://localhost:9000
# Login: admin / admin
```

## Installation

See detailed installation instructions below.

### Prerequisites

On Debian Linux 13:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.13
sudo apt install python3 python3-pip python3-venv -y

# Install Node.js 18+ and npm
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install nodejs -y

# Verify installations
python3 --version  # Should be 3.13+
node --version     # Should be 18+
npm --version
```

### Application Setup

0. **Clone the repository**
```bash
# clone into /opt/devicevault (requires sudo to write to /opt)
sudo git clone https://github.com/SlinkySoftware/DeviceVault.git /opt/devicevault
cd /opt/devicevault
```

1. **Set Up Python Virtual Environment**
```bash
cd /opt/devicevault
python3 -m venv .venv
source .venv/bin/activate
```

2. **Install Python Dependencies**
```bash
cd backend
pip install -r requirements.txt
```

3. **Install Frontend Dependencies**
```bash
cd ../frontend
npm install
npm install -g @quasar/cli
```

4. **Initialize Database**
```bash
cd ../backend
python manage.py migrate --run-syncdb
```

5. **Create Admin User**
```bash
# Preferred: run the supplied idempotent helper (from repo root)
chmod +x setup/create-initial-configuration.sh
./setup/create-initial-configuration.sh

# Alternatively (manual):
cd backend
python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('admin', 'admin@example.com', 'admin') if not User.objects.filter(username='admin').exists() else print('Admin user already exists')"
```

## Running the Application

### Using the Management Script (Recommended)

```bash
cd /opt/devicevault

# Start both frontend and backend
./devicevault.sh start

# Check status
./devicevault.sh status

# View logs
./devicevault.sh logs          # Both services
./devicevault.sh logs backend  # Backend only
./devicevault.sh logs frontend # Frontend only

# Restart services
./devicevault.sh restart

# Stop services
./devicevault.sh stop
```

## Accessing the Application

- **Frontend**: http://localhost:9000
- **Backend API**: http://localhost:8000/api/
- **Django Admin**: http://localhost:8000/admin/

**Default Credentials:**
- Username: `admin`
- Password: `admin`

## Admin Pages

1. **Dashboard** - Statistics, charts, and recent activity
2. **Devices** - Device management with filtering
3. **Device Types** - Manage device type categories
4. **Backup Methods** - View available backup method plugins
5. **Credentials** - Credential storage and management
6. **Backup Locations** - Configure storage backends
7. **Retention Policies** - Define backup retention rules

## Troubleshooting

### View Logs

```bash
./devicevault.sh logs
```

### Restart Services

```bash
./devicevault.sh restart
```

### Database Issues

```bash
cd backend
python manage.py migrate --run-syncdb
```

For more information, see the full documentation in this file.

## Running in Production

This project is developed for local and container-based development. For production deployments follow these concise notes:

- Build the frontend with Quasar and serve the compiled files from nginx.
	```bash
	# from repo root
	cd frontend
	npm ci
	npm run build
	# Quasar produces a `dist/` tree (commonly `dist/spa` for SPA mode).
	```

- Build and run a WSGI server for Django (recommended: `gunicorn`) and ensure static files are collected.
	```bash
	# in a Python virtualenv on the host or container
	pip install -r backend/requirements.txt gunicorn
	cd backend
	python manage.py collectstatic --noinput
	gunicorn --bind 0.0.0.0:8000 devicevault.wsgi:application
	```

- Nginx should serve the frontend build directory as static files and reverse-proxy API and admin endpoints to the Django WSGI server.
	Example (minimal) nginx site config:
	```nginx
	server {
			listen 80;
			server_name example.com;

			root /opt/devicevault/frontend/dist/spa; # adjust to actual quasar dist path
			index index.html;

			location /api/ {
					proxy_pass http://127.0.0.1:8000/api/;
					proxy_set_header Host $host;
					proxy_set_header X-Real-IP $remote_addr;
					proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
					proxy_set_header X-Forwarded-Proto $scheme;
			}

			location /admin/ {
					proxy_pass http://127.0.0.1:8000/admin/;
					proxy_set_header Host $host;
					proxy_set_header X-Real-IP $remote_addr;
					proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
					proxy_set_header X-Forwarded-Proto $scheme;
			}

			# Serve the SPA (fallback to index.html for history mode)
			location / {
					try_files $uri $uri/ /index.html;
			}
	}
	```

- Notes and recommendations:
	- Run Django behind a process manager (systemd, supervisord) or container orchestrator.
	- Use HTTPS in front of nginx (Let's Encrypt + certbot recommended).
	- If serving static media from object storage (S3/GCS), configure storage backends in `backend/config/config.yaml` and in `backend/settings.py` as needed.
	- Verify `frontend/quasar.config.js` for router mode (`history`) — nginx fallback to `index.html` is required for SPA routes.
