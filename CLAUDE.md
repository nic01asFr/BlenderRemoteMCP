# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**BlenderRemoteMCP** - a cloud Blender service exposed over the Model Context Protocol. An MCP client (Claude Desktop, etc.) authenticates with a Bearer API key and gets its own isolated Blender 4.0 Docker container, plus an interactive noVNC canvas in the browser.

Naming note: the repo was renamed to `BlenderRemoteMCP` (https://github.com/nic01asFr/BlenderRemoteMCP.git). `README.md`, `BRAND_ARCHITECTURE.md`, `NAMING_OPTIONS.md` and the `origin` remote still say `BigBlender` / `BigBlenderMCP` - update them when touching those files.

## Commands

```bash
# Full stack (builds blender-canvas:latest, then the MCP server)
docker-compose up -d --build
docker-compose logs -f mcp
docker-compose down

# Local server against a local Docker daemon (image must exist first)
docker build -t blender-canvas:latest docker/blender-canvas/
pip install -r requirements.txt
python main_mcp.py          # or ./start.sh --local / start.bat --local
```

Hot reload: `main_mcp.py`, `src/`, `templates/`, `static/` are bind-mounted read-only into the `mcp` container, so `docker-compose restart mcp` picks up edits. Changes under `docker/blender-canvas/` need `docker-compose build blender-base`, then stopping the running `blender-user-*` containers so the next session pulls the new image.

**Ports**: compose publishes the server on **8100** (mapped to 8000 inside). `start.sh` / `start.bat` and several docs still print 8000 - the compose value is authoritative. Per-user containers get host ports allocated from 9000 (API), 9100 (MJPEG), 9200 (noVNC).

Smoke test (no test suite exists in this repo):

```bash
# 1. register, keep the returned api_key
curl -X POST http://localhost:8100/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"a@b.c","password":"pw"}'

# 2. list tools
curl -X POST http://localhost:8100/mcp -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":1}'

# 3. exercise the full chain down to bpy
curl -X POST http://localhost:8100/mcp -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"create_object","arguments":{"type":"CUBE"}},"id":2}'
```

Live canvas: `http://localhost:8100/canvas?token=<api_key>`.

## Architecture - the call chain

Every MCP tool call crosses four process boundaries. Knowing them is what makes debugging tractable:

```
MCP client
  | HTTP POST /mcp, Authorization: Bearer blender_xxx
  v
main_mcp.py         mcp_handler -> handle_mcp_request (hand-written JSON-RPC, no SDK)
  |                 mcp_<tool>() coroutine -> _call_blender(user_id, endpoint, ...)
  v
src/container_manager.py   execute_on_container -> httpx to <host_address>:<api_port>
  |
  v
docker/blender-canvas/api_server.py    FastAPI on :8080 inside the container
  | send_to_blender() over the Unix socket /tmp/blender_api.sock
  v
docker/blender-canvas/blender_addon.py  SocketServer thread inside the Blender process
  | BlenderAPIHandler.handlers dispatch
  v
bpy
```

The addon is launched as `blender --python /app/blender_addon.py` by supervisord, so it runs in Blender's own interpreter with a live GUI on the Xvfb display `:99`.

### Adding an MCP tool

A single tool touches three places in `main_mcp.py`, and two more if Blender does not already expose the capability:

1. `async def mcp_<name>(user_id, ...)` - the implementation, returning a **string** (error strings must start with `"Error:"`, the dispatcher uses that to set `isError`).
2. An entry in the `MCP_TOOLS` dict (~line 975) with `description` + `inputSchema` - this is what `tools/list` serves.
3. An `elif tool_name == "<name>"` branch in `handle_mcp_request` (~line 1340) that unpacks `arguments` positionally. **Forgetting this branch silently falls through to `f"Tool {tool_name} not implemented"`.**
4. If new: a route in `docker/blender-canvas/api_server.py` calling `send_to_blender({"action": ...})`.
5. If new: an entry in `BlenderAPIHandler.handlers` in `blender_addon.py`, then rebuild the image.

35 tools are registered today, grouped as: scene objects, collections, materials, projects/undo, scene setup (`initialize_scene`, `setup_studio_lighting`, `setup_camera`), introspection (`get_scene_info`, `list_meshes`, `cleanup_unused`), GUI input (`send_keypress`, `send_click`, `restart_blender`), and render config (`detect_gpu`, `configure_render`).

`get_screenshot` is the one exception to the string contract: it returns a dict tagged `_type: "image"` and is special-cased before the generic text wrapping, emitting an MCP `image` content block.

MCP resources (`blender://scene`, `blender://projects`) are declared in `resources/list`; `blender://projects` currently returns an empty list.

### Container lifecycle (`src/container_manager.py`)

- One container per `user_id`, named `blender-user-<first 8 chars of user_id>`, `mem_limit=4g`, 2 CPUs, `remove=True`, on the `blender-net` network, with a named volume `blender-projects-<user_id[:8]>` mounted at `/projects`.
- Started lazily by `_ensure_session()` on the first tool call, and eagerly on the `notifications/initialized` MCP notification. Readiness is polled against the container's `/health` for up to 120s (Blender boot is slow).
- `_cleanup_loop` stops sessions idle for more than 30 min; `_cleanup_stale_containers()` wipes leftover `blender-user*` containers at server startup so restarts always pick up a freshly built image.
- `_detect_host_address()` returns `host.docker.internal` when `/.dockerenv` exists, `localhost` otherwise - the server reaches user containers through the **host-published ports**, not over the Docker network.
- `_start_autosave()` writes `/projects/autosave.blend` every 5 min per user.

### Canvas / VNC path

`/canvas` renders `templates/blender_canvas.html`, which loads the vendored noVNC RFB client from `/static/novnc/core/rfb.js` and opens `ws://<host>/ws/<user_id>`. `vnc_websocket_proxy` in `main_mcp.py` bridges that to the container's websockify on the allocated noVNC port, which fronts `x11vnc` on `:5900` against the Xvfb display. `templates/canvas.html` is an older variant that no route serves.

Inside the container, `supervisord.conf` runs, in priority order: fluxbox, blender (with the addon), x11vnc, api_server, websockify/noVNC, stream_server (FFmpeg `x11grab` -> MJPEG on 8081). `entrypoint.sh` starts Xvfb and clears stale `/tmp/.X99-lock` before handing over to supervisord.

### Auth (`src/auth.py`)

Registration returns both a JWT (`access_token`, web UI) and a long-lived API key (`blender_<token>`, MCP). Users are persisted as JSON to `data/auth.json` (`AUTH_DATA_FILE`), and `data/` is gitignored. Web routes (`/canvas`, `/api/files/*`, `/api/session/info`) accept the API key from an `Authorization` header, a `blender_token` cookie, or a `?token=` query param - see `_get_user_from_request`.

## Gotchas

- `JWT_SECRET` is a **hardcoded module constant** in `src/auth.py`; the `JWT_SECRET` env var set by docker-compose is ignored. Fix before any real deployment.
- The `/stream/{user_id}` MJPEG proxy hardcodes `http://localhost:{stream_port}` instead of `container_manager.host_address`, so it only works when the server runs outside Docker.
- `get_screenshot` performs a **full `bpy.ops.render.render`** with the scene's current engine (Eevee by default), not a viewport grab - it can be slow, and `configure_render` / `detect_gpu` change what it costs.
- `execute_python` runs `exec()` in a namespace holding only `bpy` and `result`; the tool returns whatever the code assigns to `result`, stringified if it is not JSON-serializable. There is no sandbox - arbitrary code runs as root inside the user's container.
- `/api/files/list` and friends implement file management by injecting Python through `execute_python` rather than by a dedicated container endpoint.
- CORS is `allow_origins=["*"]` with credentials enabled.
- `docker/blender-canvas/startup.py` is copied into `/root/.config/blender/4.0/scripts/startup/` at image build time - editing it requires a rebuild, not a restart.
- `data/`, `.wikichat/` and `nul` are gitignored; `nul` is a stray Windows artifact.

## Legacy code - do not extend

`main_mcp.py` is the only entry point. These are earlier iterations kept in the tree and imported by nothing that runs:

- `main_multiuser.py` + `src/mcp_server.py` (FastMCP-based server) and `src/mcp_blender_service.py`
- `src/blender_manager.py`, `src/proxy.py`, `src/port_manager.py`, `src/models.py` (pre-Docker, local-process design)

`ARCHITECTURE.md` and `docs/` describe design intent from that era and disagree with the code in places; trust `main_mcp.py` and `src/container_manager.py`.
