# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**BlenderRemoteMCP** - a cloud Blender service exposed over the Model Context Protocol. An MCP client (Claude Desktop, etc.) authenticates with a Bearer API key and gets its own isolated Blender 4.0 Docker container, plus an interactive noVNC canvas in the browser.

Naming note: the repo is `BlenderRemoteMCP` (https://github.com/nic01asFr/BlenderRemoteMCP.git). Prefer that name in docs and remotes; legacy `BigBlender` / `BigBlenderMCP` may still appear in old commits.

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

Tests: `python -m pytest tests/ -q` - 26 tests, no Docker and no Blender needed
(`tests/test_bridge.py` for the bridge framing and main-thread execution,
`tests/test_transport.py` for the transport, sessions and modes).

Smoke test against a running server:

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

```bash
# Image tout-en-un (mode mono, forme deployable sur pod)
docker build -t blender-canvas:latest docker/blender-canvas/
docker build -t blender-remote-mcp:latest -f docker/all-in-one/Dockerfile .
docker run -d -p 8100:8100 -p 6080:6080 blender-remote-mcp:latest
```

Live canvas: `http://localhost:8100/canvas?token=<api_key>`.

## Architecture - the call chain

Every MCP tool call crosses four process boundaries. Knowing them is what makes debugging tractable:

```
MCP client
  | POST /mcp, Authorization: Bearer blender_xxx, mcp-session-id
  v
main_mcp.py         mcp_handler (transport Streamable HTTP, ecrit a la main)
                    -> handle_mcp_request (protocole seul, ignore le canal)
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

37 tools are registered today, grouped as: scene objects, collections, materials, projects/undo, scene setup (`initialize_scene`, `setup_studio_lighting`, `setup_camera`), introspection (`get_scene_info`, `list_meshes`, `cleanup_unused`), GUI (`get_screenshot`, `get_canvas_url`, `blender_desktop_ui`, `send_keypress`, `send_click`, `restart_blender`), and render config (`detect_gpu`, `configure_render`).

`get_screenshot` is the one exception to the string contract: it returns a dict tagged `_type: "image"` and is special-cased before the generic text wrapping, emitting an MCP `image` content block. `blender_desktop_ui` declares `_meta.ui.resourceUri` (`ui://blenderremotemcp/desktop`) for MCP Apps hosts.

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

## Modes and sessions

`MULTI_USER_MODE=true` (default) is the gateway: one container per authenticated
user, spawned through the host Docker socket. `MULTI_USER_MODE=false` runs the
server in the **same container** as Blender and reaches it on localhost - the
form that deploys on an Onyxia pod, where there is no Docker daemon. The mode
governs data isolation, not access: **authentication is required in both**.

Sessions are a third tier of state, distinct from the user and from the Blender
instance. Several agents open their own session on the same user, hence on the
same instance, and work in parallel - verified with two concurrent
`create_object` calls landing in one scene. Closing a session touches no
container. `_points_d_acces(user_id)` is the single place that resolves host and
ports for either mode.

Transport is Streamable HTTP, protocol `2025-06-18` with negotiation down to
`2025-03-26` and `2024-11-05`. Responses go out as SSE when the client accepts
it, plain JSON otherwise - `mcp-remote` proxies do not announce
`text/event-stream` and cannot read a stream. `GET /mcp` with an SSE `Accept`
opens the legacy transport; without it, it returns server metadata. `DELETE`
closes a session. Notifications are acknowledged with `202`.

## Gotchas

- `get_screenshot` captures the X11 display with ffmpeg, not a render. The render path remains as a fallback and the response carries `method` (`x11` or `render`). The fallback forces Workbench and raises the camera `clip_end`, then **restores both** - the scene can be shared between sessions.
- The bridge executes every command on Blender's **main thread** via `bpy.app.timers`; the socket thread only queues and waits. Never call `bpy` from the socket thread - `bpy` is not thread-safe. Messages are length-prefixed (4-byte big-endian), on both sides.
- `execute_python` runs `exec()` in a namespace holding `bpy`, `mathutils` and `result`; the tool returns whatever the code assigns to `result`, serialized by `_serialize` - Blender vectors and matrices come back as lists, not as `repr` strings. There is no sandbox: arbitrary code runs as root inside the container. That is structural for a Blender service, and assumed rather than fenced - disposable container, no Docker socket in pod mode, CPU and memory capped.
- `/api/files/list` and friends implement file management by injecting Python through `execute_python` rather than by a dedicated container endpoint.
- CORS accepts credentials only when `CORS_ORIGINS` lists explicit origins; otherwise it falls back to `*` without credentials, the pairing browsers reject anyway.
- `docker/blender-canvas/startup.py` is copied into `/root/.config/blender/4.0/scripts/startup/` at image build time - editing it requires a rebuild, not a restart.
- `data/`, `.wikichat/` and `nul` are gitignored; `nul` is a stray Windows artifact.

## Deployment on Onyxia / SSPCloud

`deploy/onyxia/blender-remote-mcp.yaml` deploys the mono mode: PVC, Secret,
StatefulSet, Service, Ingress. Running at
`https://user-nic01asfr-blender-mcp.user.lab.sspcloud.fr`.

Three things there are not decoration, each learned the hard way:

- **nginx timeouts at 600s.** A tool call can outlast a minute - a render, a
  cold Blender. Without them the ingress returns 504 while the service is still
  working.
- **`/health/ready` for startup and readiness, `/health` for liveness.**
  `/health` only says this server answers; `/health/ready` reaches Blender.
  Probing readiness on the shallow one marks the pod ready as soon as uvicorn
  listens. Liveness stays shallow on purpose: if Blender dies, supervisord
  restarts it inside the container - restarting the whole pod would risk a
  crash loop.
- **PVC on `/projects`** with `AUTH_DATA_FILE=/projects/auth.json`, so accounts
  survive a pod restart.

Measured on the cluster: image pull 34s, Blender's bridge answering 11s after
pod start under a 4-CPU limit, SSE passing the real ingress over HTTP/2.

The service does **not** appear in Onyxia's "Mes services" - that needs a Helm
chart and its `sh.onyxia.release.v1.<release>` metadata Secret.

Image push is cheap after the first: Docker only sends missing layers, so a
code change re-pushes seconds' worth of thin layers.

### Image drifts from your local environment

The all-in-one image installs its own Python dependencies, and they are newer
than a typical local checkout - `starlette 1.6` in the image against `0.48`
locally at the time of writing. A call that passes every local test can still
fail in the pod when an API changed between majors: that is exactly how
`TemplateResponse(name, context)` reached production, where Starlette 1.x
rejects it with `unhashable type: dict`.

Versions are bounded in `docker/all-in-one/Dockerfile` to keep the drift from
being silent, but bounds are not equality. **After any change touching a
framework API, smoke-test the deployed service, not just `pytest`.**

## History

`main_mcp.py` is the only entry point. Seven modules from earlier iterations
(`main_multiuser.py`, `src/mcp_server.py`, `src/mcp_blender_service.py`,
`src/blender_manager.py`, `src/proxy.py`, `src/port_manager.py`,
`src/models.py`) were removed in `6e99ba1` - they imported only each other, and
`src/proxy.py` imported a `main` module that never existed. Recoverable from
git history if ever needed.

`docs/` describes design intent from that era and disagrees with the code in
places; `ARCHITECTURE.md` was rewritten (v3) and is current.
