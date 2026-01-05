# DeviceVault

A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.

## Features

- **Multi-Manufacturer Support**: Cisco, Fortigate, Dell, Sophos, Mikrotik, and more
- **Flexible Connectivity**: SSH, API, and TFTP backup reception
- **Multiple Storage Backends**: Git (default), Local Filesystem, S3, Azure, GCS
- **RBAC**: Role-based access control with label-based visibility
- **Authentication**: LDAP, SAML, Entra ID, and Local Auth support
- **Retention Policies**: Configurable backup retention by count, time, or size
- **Audit Logging**: Complete audit trail of all activities
- **Dashboard**: Real-time statistics and backup success rate charts
- **Backup Comparison**: Side-by-side diff view of configuration changes

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

1. **Set Up Python Virtual Environment**
```bash
cd /home/jac/devicevault
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
python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('admin', 'admin@example.com', 'admin') if not User.objects.filter(username='admin').exists() else print('Admin user already exists')"
```

## Running the Application

### Using the Management Script (Recommended)

```bash
cd /home/jac/devicevault

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

- **Frontend**: http://localhost:9000 or http://ansible.home.173crs.com:9000
- **Backend API**: http://localhost:8000/api/
- **Django Admin**: http://localhost:8000/admin/

**Default Credentials:**
- Username: `admin`
- Password: `admin`

## Admin Pages

1. **Dashboard** - Statistics, charts, and recent activity
2. **Devices** - Device management with filtering
3. **Device Types** - Manage device type categories
4. **Manufacturers** - Manage device manufacturers
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