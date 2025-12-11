#!/bin/bash
set -e

# Function to fix permissions on app directories
fix_permissions() {
    echo "Fixing permissions on application directories..."
    
    # Ensure required directories exist
    mkdir -p /app/src/instance /app/src/instance/data /app/src/instance/data/in /app/src/instance/data/srv /app/src/instance/config /app/src/instance/db /app/src/instance/logs
    mkdir -p /app/processing
    
    # Set permissions for all application directories
    APP_DIRS="/home/appuser /app/processing /app/src/instance"
    chown -R appuser:appuser $APP_DIRS 2>/dev/null || true
    
    # Ensure log file exists and has correct permissions
    touch /app/src/instance/logs/app.log
    chmod 664 /app/src/instance/logs/app.log
    chown appuser:appuser /app/src/instance/logs/app.log 2>/dev/null || true
}

# Check if running as root
if [ "$(id -u)" = "0" ]; then
    # Check if PUID/PGID env variables are set for custom user mapping
    if [ -n "${PUID}" ] && [ -n "${PGID}" ]; then
        echo "Using custom UID:GID = ${PUID}:${PGID}"
        
        # Update user/group IDs if needed
        usermod -o -u "$PUID" appuser
        groupmod -o -g "$PGID" appuser
    fi
    
    # Always fix permissions when running as root
    fix_permissions
    
    # Run as appuser
    export HOME=/home/appuser
    exec gosu appuser "$@"
else
    # Not running as root - just run the command
    exec "$@"
fi