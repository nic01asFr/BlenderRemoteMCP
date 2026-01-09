# Plan d'implémentation - Interface Blender Canvas Pure

## Vue d'ensemble

Transformer l'accès noVNC actuel en une expérience Blender immersive sans chrome UI.

```
AVANT:                              APRÈS:
┌─────────────────────────┐        ┌─────────────────────────┐
│ noVNC Control Bar       │        │                         │
├─────────────────────────┤        │                         │
│                         │        │   BLENDER VIEWPORT      │
│   Blender dans iframe   │   →    │   (Plein écran)         │
│   avec barre noVNC      │        │                         │
│                         │        │   Keyboard Lock API     │
├─────────────────────────┤        │   Pointer Lock API      │
│ Connect / Settings      │        │                         │
└─────────────────────────┘        └─────────────────────────┘
```

---

## Architecture Technique

### 1. Flux de connexion utilisateur

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Browser    │────▶│  MCP Server  │────▶│  Container   │
│              │     │  (FastAPI)   │     │  (Blender)   │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │
       │  1. GET /canvas    │                    │
       │◀───────────────────│                    │
       │     HTML + JS      │                    │
       │                    │                    │
       │  2. WebSocket      │                    │
       │────────────────────▶  3. Proxy to VNC  │
       │    /ws/{user_id}   │───────────────────▶│
       │                    │     port 5900      │
       │◀───────────────────│◀───────────────────│
       │   VNC Stream       │   VNC Protocol     │
```

### 2. Endpoints à créer

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/canvas` | GET | Page HTML canvas pure (auth via cookie/token) |
| `/ws/{user_id}` | WS | WebSocket proxy vers VNC du container |
| `/api/files/list` | GET | Liste des fichiers utilisateur |
| `/api/files/upload` | POST | Upload fichier (.blend, textures) |
| `/api/files/download/{name}` | GET | Download fichier |
| `/api/session/info` | GET | Info session (ports, URLs) |

---

## Implémentation Détaillée

### Phase 1: Page Canvas Pure

**Fichier: `templates/blender_canvas.html`**

```html
<!DOCTYPE html>
<html>
<head>
    <title>Blender Canvas</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body { width: 100%; height: 100%; overflow: hidden; background: #1a1a1a; }
        #canvas { width: 100%; height: 100%; display: block; }
        #loading { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: #fff; }
        #controls { position: fixed; bottom: 20px; right: 20px; z-index: 1000; display: none; }
        #controls button { padding: 10px 15px; margin: 5px; background: #333; color: #fff; border: none; cursor: pointer; }
        #controls button:hover { background: #555; }
    </style>
</head>
<body>
    <div id="loading">Connecting to Blender...</div>
    <div id="canvas"></div>
    <div id="controls">
        <button onclick="toggleFullscreen()">Fullscreen</button>
        <button onclick="resetView()">Reset View</button>
    </div>

    <script type="module">
        import RFB from '/static/novnc/core/rfb.js';

        const wsUrl = 'ws://' + window.location.host + '/ws/{{ user_id }}';
        const container = document.getElementById('canvas');
        const loading = document.getElementById('loading');
        const controls = document.getElementById('controls');

        let rfb = null;

        async function connect() {
            try {
                rfb = new RFB(container, wsUrl, {
                    scaleViewport: true,
                    resizeSession: true,
                    focusOnClick: true,
                    clipViewport: false,
                    showDotCursor: false,
                });

                rfb.addEventListener('connect', () => {
                    loading.style.display = 'none';
                    controls.style.display = 'block';
                    enableFullscreenControls();
                });

                rfb.addEventListener('disconnect', () => {
                    loading.textContent = 'Disconnected. Reconnecting...';
                    loading.style.display = 'block';
                    setTimeout(connect, 2000);
                });

                rfb.addEventListener('credentialsrequired', () => {
                    rfb.sendCredentials({ password: '' });
                });

            } catch (e) {
                loading.textContent = 'Connection failed: ' + e.message;
            }
        }

        function enableFullscreenControls() {
            // Auto-fullscreen on first click
            container.addEventListener('click', async () => {
                if (!document.fullscreenElement) {
                    await container.requestFullscreen();

                    // Keyboard Lock for all shortcuts
                    if ('keyboard' in navigator && 'lock' in navigator.keyboard) {
                        await navigator.keyboard.lock();
                    }
                }
                rfb.focus();
            }, { once: true });

            // Handle fullscreen change
            document.addEventListener('fullscreenchange', () => {
                if (!document.fullscreenElement) {
                    controls.style.display = 'block';
                } else {
                    controls.style.display = 'none';
                }
            });
        }

        window.toggleFullscreen = async () => {
            if (!document.fullscreenElement) {
                await container.requestFullscreen();
                if ('keyboard' in navigator && 'lock' in navigator.keyboard) {
                    await navigator.keyboard.lock();
                }
            } else {
                await document.exitFullscreen();
            }
        };

        window.resetView = () => {
            // Send Home key to Blender (reset view)
            rfb.sendKey(0xff50); // Home key
        };

        connect();
    </script>
</body>
</html>
```

### Phase 2: WebSocket Proxy VNC

**Ajout à `main_mcp.py`:**

```python
from starlette.websockets import WebSocket, WebSocketDisconnect
import websockets

@app.websocket("/ws/{user_id}")
async def vnc_websocket_proxy(websocket: WebSocket, user_id: str):
    """WebSocket proxy to user's VNC server"""

    # Verify user has active session
    session = container_manager.get_session(user_id)
    if not session:
        await websocket.close(code=4004)
        return

    await websocket.accept()

    # Connect to container's VNC WebSocket (via noVNC's websockify)
    vnc_ws_url = f"ws://localhost:{session.novnc_port}/websockify"

    try:
        async with websockets.connect(vnc_ws_url) as vnc_ws:
            async def client_to_vnc():
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await vnc_ws.send(data)
                except WebSocketDisconnect:
                    pass

            async def vnc_to_client():
                try:
                    async for data in vnc_ws:
                        await websocket.send_bytes(data)
                except Exception:
                    pass

            await asyncio.gather(client_to_vnc(), vnc_to_client())
    except Exception as e:
        logger.error(f"VNC proxy error: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass
```

### Phase 3: API Gestion Fichiers

```python
from fastapi import UploadFile, File
from fastapi.responses import FileResponse

@app.get("/api/files/list")
async def list_files(request: Request):
    """List user's files"""
    user_id = await get_user_from_request(request)
    result = await _call_blender(user_id, "/api/execute", "POST", {
        "code": """
import os
files = []
for f in os.listdir('/projects'):
    path = os.path.join('/projects', f)
    files.append({
        'name': f,
        'size': os.path.getsize(path),
        'is_blend': f.endswith('.blend')
    })
result = files
"""
    })
    return result.get("result", [])

@app.post("/api/files/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...)
):
    """Upload file to user's project folder"""
    user_id = await get_user_from_request(request)
    session = await _ensure_session(user_id)

    # Save to temp then copy to container
    content = await file.read()
    # ... implementation

    return {"success": True, "filename": file.filename}

@app.get("/api/files/download/{filename}")
async def download_file(request: Request, filename: str):
    """Download file from user's project"""
    # ... implementation
```

### Phase 4: Configuration Blender pour Input

**Fichier: `docker/blender-canvas/startup.py` (mise à jour)**

```python
def configure_blender():
    """Configure Blender for optimal web canvas experience"""

    # ... existing config ...

    # Enable 3-button mouse emulation for laptops
    try:
        bpy.context.preferences.inputs.use_mouse_emulate_3_button = True
    except Exception:
        pass

    # Enable continuous grab for better orbit
    try:
        bpy.context.preferences.inputs.use_mouse_continuous = True
    except Exception:
        pass

    # Disable region overlap for cleaner viewport
    try:
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces[0].overlay.show_overlays = True
                area.spaces[0].show_gizmo = True
    except Exception:
        pass
```

---

## Authentification Web

### Option A: Token dans URL (simple)
```
/canvas?token=blender_xxx...
```

### Option B: Cookie de session (recommandé)
```python
@app.get("/canvas")
async def canvas_page(request: Request):
    # Check cookie or redirect to login
    token = request.cookies.get("blender_token")
    if not token:
        return RedirectResponse("/login")

    user = await auth_manager.verify_api_key(token)
    if not user:
        return RedirectResponse("/login")

    # Start session if needed
    await _ensure_session(user.id)
    session = container_manager.get_session(user.id)

    return templates.TemplateResponse("blender_canvas.html", {
        "request": request,
        "user_id": user.id,
        "session": session.to_dict()
    })
```

---

## Contrôles Clavier/Souris

### Raccourcis Blender supportés

| Action | Desktop | Laptop (Emulation) |
|--------|---------|-------------------|
| Orbit | Middle Mouse | Alt + Left Mouse |
| Zoom | Scroll | Ctrl + Middle / Scroll |
| Pan | Shift + Middle | Shift + Alt + Left |
| Select | Left Click | Left Click |
| Context Menu | Right Click | Right Click |
| Frame Selected | Numpad . | Home |

### Keyboard Lock API

En fullscreen, tous les raccourcis sont capturés:
- Tab, G, R, S (transform modes)
- X, Y, Z (axis constraints)
- Ctrl+Z (undo)
- Shift+D (duplicate)
- etc.

**Exception**: ESC maintenu 2 secondes = sortie de sécurité navigateur

---

## Stockage Données

### Structure volumes Docker

```
/projects/
├── autosave.blend          # Sauvegarde automatique
├── project_name.blend      # Projets utilisateur
├── textures/               # Textures importées
│   ├── wood.png
│   └── metal.jpg
├── hdri/                   # HDR environments
└── exports/                # Renders exportés
    ├── render_001.png
    └── animation/
```

### Persistance

- **Docker Volume**: `blender-projects-{user_id[:8]}`
- **Backup**: API pour export ZIP du dossier complet
- **Quota**: Configurable (ex: 1GB par utilisateur)

---

## Ordre d'implémentation

1. **WebSocket Proxy** (requis pour RFB library)
2. **Page Canvas HTML** (avec RFB)
3. **Auth Cookie/Session**
4. **Test contrôles clavier/souris**
5. **API fichiers**
6. **Polish UX**

---

## Tests

```bash
# 1. Vérifier WebSocket proxy
wscat -c ws://localhost:8000/ws/{user_id}

# 2. Tester page canvas
open http://localhost:8000/canvas?token=blender_xxx

# 3. Vérifier keyboard lock (en fullscreen)
# - Tester Tab, G, R, S, Ctrl+Z

# 4. Tester upload/download fichiers
curl -X POST http://localhost:8000/api/files/upload \
  -H "Authorization: Bearer xxx" \
  -F "file=@model.blend"
```
