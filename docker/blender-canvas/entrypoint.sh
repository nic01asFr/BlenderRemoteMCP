#!/bin/bash
set -e

echo "Starting Blender Canvas Container..."

# Clean up stale X11 lock files (important for container restarts)
echo "Cleaning up stale X11 locks..."
rm -f /tmp/.X99-lock
rm -f /tmp/.X11-unix/X99

# Start Xvfb (virtual display)
#
# 1280x720 par defaut plutot que 1920x1080 : chaque pixel est dessine par le
# processeur (llvmpipe), relu par x11vnc, encode, puis relaye. Passer de 2,07 a
# 0,92 million de pixels retire 55 % de ce travail a chaque image. Relever par
# DISPLAY_GEOMETRY quand le confort prime sur la fluidite.
GEOMETRIE="${DISPLAY_GEOMETRY:-1280x720}"
echo "Starting Xvfb on display :99 (${GEOMETRIE})..."
Xvfb :99 -screen 0 "${GEOMETRIE}x24" -ac &
sleep 2

# Wait for display
until xdpyinfo -display :99 > /dev/null 2>&1; do
    echo "Waiting for display :99..."
    sleep 1
done
echo "Display :99 ready"

# Quota CPU reel du container, pour borner l'ordonnanceur de Blender.
# Dans un pod, nproc montre les CPU de la MACHINE et non le quota du cgroup.
if [ -r /sys/fs/cgroup/cpu.max ]; then
    read -r QUOTA PERIODE < /sys/fs/cgroup/cpu.max
    [ "$QUOTA" != "max" ] && BLENDER_THREADS=$(( QUOTA / PERIODE ))
elif [ -r /sys/fs/cgroup/cpu/cpu.cfs_quota_us ]; then
    QUOTA=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us)
    PERIODE=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us)
    [ "$QUOTA" -gt 0 ] && BLENDER_THREADS=$(( QUOTA / PERIODE ))
fi
# Repli sur nproc si aucun quota n'est lisible : sans limite de cgroup, les
# CPU de la machine SONT ceux du container.
BLENDER_THREADS="${BLENDER_THREADS:-$(nproc)}"
[ "$BLENDER_THREADS" -lt 1 ] && BLENDER_THREADS=1
export BLENDER_THREADS
echo "Quota CPU detecte : ${BLENDER_THREADS} fil(s) pour Blender"

# Start supervisor (manages all processes)
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
