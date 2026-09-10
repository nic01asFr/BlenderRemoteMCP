# Blender Canvas Container
# Includes: Blender GUI + Xvfb + noVNC + Software OpenGL + HTTP API

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV BLENDER_VERSION=4.0

# Software OpenGL configuration (Mesa llvmpipe)
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV GALLIUM_DRIVER=llvmpipe
ENV LP_NUM_THREADS=4

# Force X11 and disable Wayland
ENV WAYLAND_DISPLAY=
ENV XDG_RUNTIME_DIR=/tmp
ENV LIBGL_ALWAYS_INDIRECT=0
ENV QT_X11_NO_MITSHM=1

# Install dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    xvfb \
    x11vnc \
    ffmpeg \
    python3 \
    python3-pip \
    libxkbcommon-x11-0 \
    libxcb-xinerama0 \
    libxcb-cursor0 \
    libegl1 \
    libgl1-mesa-glx \
    libglu1-mesa \
    supervisor \
    x11-xserver-utils \
    xdotool \
    mesa-utils \
    libgl1-mesa-dri \
    libosmesa6 \
    libglapi-mesa \
    fluxbox \
    websockify \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# Install Blender
RUN wget -q https://download.blender.org/release/Blender4.0/blender-4.0.2-linux-x64.tar.xz \
    && tar -xf blender-4.0.2-linux-x64.tar.xz \
    && mv blender-4.0.2-linux-x64 /opt/blender \
    && rm blender-4.0.2-linux-x64.tar.xz \
    && ln -s /opt/blender/blender /usr/local/bin/blender

# Install noVNC for browser-based VNC access
RUN wget -qO- https://github.com/novnc/noVNC/archive/v1.4.0.tar.gz | tar xz -C /opt \
    && mv /opt/noVNC-1.4.0 /opt/novnc \
    && ln -s /opt/novnc/vnc.html /opt/novnc/index.html

# Install Python dependencies
RUN pip3 install fastapi uvicorn aiofiles

# Create directories
RUN mkdir -p /app /projects /tmp/blender

WORKDIR /app

# Copy application files
COPY api_server.py /app/
COPY stream_server.py /app/
COPY blender_addon.py /app/
COPY startup.py /app/
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY entrypoint.sh /app/

RUN chmod +x /app/entrypoint.sh

# Configure Blender startup script (auto-runs on launch)
RUN mkdir -p /root/.config/blender/4.0/scripts/startup && \
    cp /app/startup.py /root/.config/blender/4.0/scripts/startup/

# Configure Fluxbox : pas de toolbar ; forcer LF (COPY Windows peut injecter CR
# et casser session.appsFile / toolbar.visible — Blender se retrouvait a y=42).
RUN mkdir -p /root/.fluxbox
COPY fluxbox-apps /root/.fluxbox/apps
COPY fluxbox-init /root/.fluxbox/init
RUN sed -i 's/\r$//' /root/.fluxbox/init /root/.fluxbox/apps

COPY fit-blender.sh /app/fit-blender.sh
RUN chmod +x /app/fit-blender.sh && sed -i 's/\r$//' /app/fit-blender.sh /etc/supervisor/conf.d/supervisord.conf

# Bornes de parallelisme et geometrie de l'affichage.
#
# Placees ici, apres les COPY : une ENV en tete de fichier invalide toutes les
# couches suivantes, donc le telechargement de Blender et l'apt install.
#
# Dans un pod, nproc montre les CPU de la MACHINE et non le quota du cgroup —
# 104 contre 4 mesures ici. Sans bornes, les bibliotheques dimensionnent leurs
# fils sur le mauvais nombre et se sur-souscrivent.
#
# La geometrie est le premier levier de fluidite : chaque pixel est dessine par
# le processeur (llvmpipe), relu par x11vnc, encode, puis relaye.
ENV OMP_NUM_THREADS=4 \
    DISPLAY_GEOMETRY=1280x720

# Expose ports
# 6080: noVNC web interface (browser VNC client)
# 8080: HTTP API for Blender control
# 8081: MJPEG video stream
EXPOSE 6080 8080 8081

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
