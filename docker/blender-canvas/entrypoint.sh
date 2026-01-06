#!/bin/bash
set -e

echo "Starting Blender Canvas Container..."

# Start Xvfb (virtual display)
echo "Starting Xvfb on display :99..."
Xvfb :99 -screen 0 1920x1080x24 -ac &
sleep 2

# Wait for display
until xdpyinfo -display :99 > /dev/null 2>&1; do
    echo "Waiting for display :99..."
    sleep 1
done
echo "Display :99 ready"

# Start supervisor (manages all processes)
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
