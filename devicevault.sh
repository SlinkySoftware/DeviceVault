#!/bin/bash

/*
* DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
* Copyright (C) 2026, Slinky Software
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU General Public License as published by
* the Free Software Foundation, either version 3 of the License, or
* (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU General Public License for more details.
*
* You should have received a copy of the GNU General Public License
* along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

# DeviceVault Management Script
# Starts and stops both frontend and backend services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
PID_DIR="$SCRIPT_DIR/.pids"

mkdir -p "$PID_DIR"

BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

function print_status() {
    echo -e "${GREEN}[DeviceVault]${NC} $1"
}

function print_error() {
    echo -e "${RED}[DeviceVault]${NC} $1"
}

function print_warning() {
    echo -e "${YELLOW}[DeviceVault]${NC} $1"
}

function check_requirements() {
    print_status "Checking requirements..."
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed"
        exit 1
    fi
    
    # Check Node.js
    if ! command -v node &> /dev/null; then
        print_error "Node.js is not installed"
        exit 1
    fi
    
    # Check npm
    if ! command -v npm &> /dev/null; then
        print_error "npm is not installed"
        exit 1
    fi
    
    # Check virtual environment
    if [ ! -d "$SCRIPT_DIR/.venv" ]; then
        print_warning "Python virtual environment not found. Creating one..."
        cd "$BACKEND_DIR"
        python3 -m venv "$SCRIPT_DIR/.venv"
        "$SCRIPT_DIR/.venv/bin/pip" install --upgrade pip
        if [ -f requirements.txt ]; then
            "$SCRIPT_DIR/.venv/bin/pip" install -r requirements.txt
        fi
    fi
    
    print_status "All requirements satisfied"
}

function start_backend() {
    if [ -f "$BACKEND_PID_FILE" ] && kill -0 $(cat "$BACKEND_PID_FILE") 2>/dev/null; then
        print_warning "Backend is already running (PID: $(cat $BACKEND_PID_FILE))"
        return 0
    fi
    
    print_status "Starting backend..."
    cd "$BACKEND_DIR"
    
    # Use virtual environment Python directly
    local PYTHON="$SCRIPT_DIR/.venv/bin/python"
    if [ ! -f "$PYTHON" ]; then
        print_error "Virtual environment not found at $SCRIPT_DIR/.venv"
        return 1
    fi
    
    # Start Django server in background
    nohup "$PYTHON" manage.py runserver 0.0.0.0:8000 > "$PID_DIR/backend.log" 2>&1 &
    echo $! > "$BACKEND_PID_FILE"
    
    sleep 2
    
    if kill -0 $(cat "$BACKEND_PID_FILE") 2>/dev/null; then
        print_status "Backend started successfully (PID: $(cat $BACKEND_PID_FILE))"
        print_status "Backend URL: http://localhost:8000"
    else
        print_error "Failed to start backend. Check logs at $PID_DIR/backend.log"
        return 1
    fi
}

function start_frontend() {
    if [ -f "$FRONTEND_PID_FILE" ] && kill -0 $(cat "$FRONTEND_PID_FILE") 2>/dev/null; then
        print_warning "Frontend is already running (PID: $(cat $FRONTEND_PID_FILE))"
        return 0
    fi
    
    print_status "Starting frontend..."
    cd "$FRONTEND_DIR"
    
    # Check if node_modules exists
    if [ ! -d "node_modules" ]; then
        print_status "Installing frontend dependencies..."
        npm install
    fi
    
    # Start Quasar dev server in background (using npm run dev)
    nohup npm run dev > "$PID_DIR/frontend.log" 2>&1 &
    echo $! > "$FRONTEND_PID_FILE"
    
    sleep 3
    
    if kill -0 $(cat "$FRONTEND_PID_FILE") 2>/dev/null; then
        print_status "Frontend started successfully (PID: $(cat $FRONTEND_PID_FILE))"
        print_status "Frontend URL: http://localhost:9000"
    else
        print_error "Failed to start frontend. Check logs at $PID_DIR/frontend.log"
        return 1
    fi
}

function stop_backend() {
    print_status "Stopping backend..."
    
    # Kill by PID file if it exists
    if [ -f "$BACKEND_PID_FILE" ]; then
        local PID=$(cat "$BACKEND_PID_FILE")
        if kill -0 $PID 2>/dev/null; then
            # Kill process group (parent and all children)
            kill -TERM -$PID 2>/dev/null || true
            sleep 2
            # Force kill if still running
            kill -9 -$PID 2>/dev/null || true
        fi
        rm -f "$BACKEND_PID_FILE"
    fi
    
    # Kill all Django server processes as fallback
    pkill -f "manage.py runserver" 2>/dev/null || true
    pkill -f "python.*manage.py" 2>/dev/null || true
    pkill -f "runserver" 2>/dev/null || true
    
    sleep 1
    print_status "Backend stopped"
}

function stop_frontend() {
    print_status "Stopping frontend..."
    
    # Kill by PID file if it exists
    if [ -f "$FRONTEND_PID_FILE" ]; then
        local PID=$(cat "$FRONTEND_PID_FILE")
        if kill -0 $PID 2>/dev/null; then
            # Kill process group (parent and all children)
            kill -TERM -$PID 2>/dev/null || true
            sleep 2
            # Force kill if still running
            kill -9 -$PID 2>/dev/null || true
        fi
        rm -f "$FRONTEND_PID_FILE"
    fi
    
    # Kill all npm/Node.js processes related to frontend as fallback
    pkill -f "npm run dev" 2>/dev/null || true
    pkill -f "quasar dev" 2>/dev/null || true
    pkill -f "node.*quasar" 2>/dev/null || true
    lsof -ti:9000,9001 | xargs kill -9 2>/dev/null || true
    
    sleep 1
    print_status "Frontend stopped"
}

function status() {
    echo "=== DeviceVault Status ==="
    echo ""
    
    # Backend status
    if [ -f "$BACKEND_PID_FILE" ] && kill -0 $(cat "$BACKEND_PID_FILE") 2>/dev/null; then
        print_status "Backend: ${GREEN}Running${NC} (PID: $(cat $BACKEND_PID_FILE))"
    else
        print_status "Backend: ${RED}Stopped${NC}"
    fi
    
    # Frontend status
    if [ -f "$FRONTEND_PID_FILE" ] && kill -0 $(cat "$FRONTEND_PID_FILE") 2>/dev/null; then
        print_status "Frontend: ${GREEN}Running${NC} (PID: $(cat $FRONTEND_PID_FILE))"
    else
        print_status "Frontend: ${RED}Stopped${NC}"
    fi
    
    echo ""
}

function restart() {
    print_status "Restarting DeviceVault..."
    stop
    sleep 2
    start
}

function start() {
    check_requirements
    start_backend
    start_frontend
    echo ""
    print_status "DeviceVault started successfully!"
    print_status "Access the application at: http://localhost:9000"
    print_status "Backend API available at: http://localhost:8000"
    echo ""
}

function stop() {
    print_status "Stopping DeviceVault..."
    stop_frontend
    stop_backend
    print_status "DeviceVault stopped"
}

function logs() {
    local service=$1
    
    if [ "$service" == "backend" ] || [ -z "$service" ]; then
        echo "=== Backend Logs ==="
        if [ -f "$PID_DIR/backend.log" ]; then
            tail -n 50 "$PID_DIR/backend.log"
        else
            print_warning "No backend logs found"
        fi
        echo ""
    fi
    
    if [ "$service" == "frontend" ] || [ -z "$service" ]; then
        echo "=== Frontend Logs ==="
        if [ -f "$PID_DIR/frontend.log" ]; then
            tail -n 50 "$PID_DIR/frontend.log"
        else
            print_warning "No frontend logs found"
        fi
        echo ""
    fi
}

function usage() {
    echo "DeviceVault Management Script"
    echo ""
    echo "Usage: $0 {start|stop|restart|status|logs [backend|frontend]}"
    echo ""
    echo "Commands:"
    echo "  start     - Start both frontend and backend services"
    echo "  stop      - Stop both frontend and backend services"
    echo "  restart   - Restart both services"
    echo "  status    - Show status of services"
    echo "  logs      - Show logs (optionally specify 'backend' or 'frontend')"
    echo ""
}

# Main script logic
case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs $2
        ;;
    *)
        usage
        exit 1
        ;;
esac

exit 0
