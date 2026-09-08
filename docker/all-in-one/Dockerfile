# BlenderRemoteMCP — image tout-en-un, mode mono-utilisateur.
#
# Couche mince par-dessus blender-canvas : elle ajoute le serveur MCP dans le
# MEME container que Blender. C'est la forme deployable sur un pod Onyxia, ou
# il n'y a pas de demon Docker a piloter.
#
# Deux images, deux roles :
#   blender-canvas    -> instance Blender seule, utilisee comme worker par la
#                        passerelle en mode multi-utilisateur ;
#   blender-remote-mcp -> celle-ci, qui porte en plus le serveur MCP.
#
# Construction, depuis la racine du depot :
#   docker build -t blender-canvas:latest docker/blender-canvas/
#   docker build -t blender-remote-mcp:latest -f docker/all-in-one/Dockerfile .

FROM blender-canvas:latest

# Dependances du serveur MCP. fastapi, uvicorn et aiofiles viennent de l'image
# de base. Le SDK docker reste necessaire : main_mcp importe container_manager
# au chargement, meme quand le mode mono ne s'en sert pas.
RUN pip3 install --no-cache-dir \
        httpx \
        pyjwt \
        "pydantic[email]" \
        websockets \
        docker \
        jinja2 \
        python-multipart

WORKDIR /app

COPY main_mcp.py /app/
COPY src/ /app/src/
COPY templates/ /app/templates/
COPY static/ /app/static/

# Le serveur MCP rejoint les programmes deja geres par supervisord. On ajoute
# le bloc a la configuration existante plutot que de la dupliquer : elle reste
# la source unique pour Xvfb, fluxbox, Blender, x11vnc, l'API et le flux.
RUN printf '%s\n' \
    '' \
    '[program:mcp_server]' \
    'command=python3 /app/main_mcp.py' \
    'directory=/app' \
    'environment=PYTHONUNBUFFERED="1"' \
    'autostart=%(ENV_MCP_AUTOSTART)s' \
    'autorestart=true' \
    'startsecs=5' \
    'stdout_logfile=/var/log/supervisor/mcp.log' \
    'stderr_logfile=/var/log/supervisor/mcp_err.log' \
    'priority=40' \
    >> /etc/supervisor/conf.d/supervisord.conf

# Mode mono par defaut : c'est la raison d'etre de cette image.
ENV MULTI_USER_MODE=false \
    MCP_AUTOSTART=true \
    PORT=8100 \
    BLENDER_HOST=localhost \
    BLENDER_API_PORT=8080 \
    BLENDER_STREAM_PORT=8081 \
    BLENDER_NOVNC_PORT=6080 \
    AUTH_DATA_FILE=/projects/auth.json

# 8100 : serveur MCP — les autres ports viennent de l'image de base
# (6080 noVNC, 8080 API Blender, 8081 flux MJPEG).
EXPOSE 8100

# La sante du service, c'est celle du serveur MCP : il ne repond que si la
# chaine complete jusqu'a Blender repond.
HEALTHCHECK --interval=15s --timeout=10s --start-period=90s \
    CMD curl -f http://localhost:8100/health || exit 1
