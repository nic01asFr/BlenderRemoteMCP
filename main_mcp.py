#!/usr/bin/env python3
"""
Blender MCP Server
==================
Main entry point for the Blender MCP service.

Standard MCP HTTP server with Bearer token authentication.
Each authenticated user gets their own isolated Blender container.

Configuration for Claude Desktop:
{
  "mcpServers": {
    "blender": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}

Start: python main_mcp.py
Test:  Configure Claude Desktop and ask "Create a red cube"
"""

from contextlib import asynccontextmanager
from contextvars import ContextVar
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import uvicorn
import httpx
import json
import logging
import os
import asyncio
import time
import uuid
import websockets

from src.container_manager import ContainerManager
from src.auth import (AuthManager, UserCreate, UserLogin, TokenResponse,
                      SCOPED_PREFIX, TOUS_LES_OUTILS)
from src import oauth_mcp
from src import guidance as guidance_mod
from src.guidance import build_context, infer_phase, substitute_params

# Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Context variable for current user
current_user_id: ContextVar[str] = ContextVar('current_user_id', default=None)

# Managers
container_manager = ContainerManager()
auth_manager = AuthManager()

# Autosave tasks per user
_autosave_tasks = {}


# =============================================================================
# SESSIONS MCP
# =============================================================================
#
# Une session n'est PAS un utilisateur. Plusieurs agents peuvent ouvrir chacun
# leur session sur le meme utilisateur, donc sur la meme instance Blender, et y
# travailler en parallele : c'est ce que le transport Streamable HTTP rend
# possible et que l'ancien POST sans session interdisait.
#
# L'etat se repartit en trois etages, deliberement distincts :
#   - global et immuable : partage par toutes les sessions ;
#   - par instance Blender : la scene et le projet, qui vivent dans le
#     container et sont donc partages entre les sessions du meme utilisateur ;
#   - par session MCP : ce dictionnaire, purement une vue. Une session qui
#     disparait ne doit rien modifier de l'instance.

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SESSION_IDLE_SECONDS = 3600

# session_id -> {"user_id", "created_at", "last_seen", "client", "protocol"}
_sessions: dict = {}

# Methodes qui supposent une session deja initialisee.
_STATEFUL_METHODS = frozenset({
    "tools/list", "tools/call",
    "resources/list", "resources/read",
    "prompts/list", "prompts/get",
})


def _touch_session(session_id: str, user_id: str, **champs) -> dict:
    """Cree ou rafraichit une session."""
    session = _sessions.get(session_id)
    if session is None:
        session = {
            "user_id": user_id,
            "created_at": time.time(),
            "client": None,
            "protocol": PROTOCOL_VERSION,
        }
        _sessions[session_id] = session
    session["last_seen"] = time.time()
    session.update({k: v for k, v in champs.items() if v is not None})
    return session


def _evict_idle_sessions() -> int:
    """Oublie les sessions inactives. Ne touche a aucun container : l'instance
    Blender a son propre cycle de vie, gere par container_manager."""
    limite = time.time() - SESSION_IDLE_SECONDS
    perimees = [sid for sid, s in _sessions.items() if s["last_seen"] < limite]
    for sid in perimees:
        _sessions.pop(sid, None)
    return len(perimees)


def _accepts_sse(accept_header: str) -> bool:
    """Vrai si le client accepte text/event-stream.

    Analyse les types un a un : une comparaison par sous-chaine ferait passer
    'text/event-stream-autre-chose' pour un flux SSE.
    """
    for partie in (accept_header or "").split(","):
        if partie.split(";")[0].strip().lower() == "text/event-stream":
            return True
    return False


def _sse_response(payload: dict, session_id: str) -> Response:
    """Reponse SSE a evenement unique, forme attendue par Streamable HTTP."""
    return Response(
        content=f"event: message\ndata: {json.dumps(payload)}\n\n",
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # sinon nginx accumule le flux
            "mcp-session-id": session_id,
        },
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    logger.info("Starting Blender MCP Server...")
    if MULTI_USER_MODE:
        await container_manager.initialize()
    else:
        logger.info("Mode mono-utilisateur : instance Blender locale, pas de Docker")
    logger.info("=" * 50)
    logger.info("Server ready at http://localhost:8000")
    logger.info("MCP endpoint: http://localhost:8000/mcp")
    logger.info("=" * 50)

    async def _concierge_sessions():
        """Oublie les sessions MCP inactives. N'arrete aucun container : les
        instances Blender ont leur propre cycle de vie."""
        while True:
            await asyncio.sleep(300)
            oubliees = _evict_idle_sessions()
            if oubliees:
                logger.info(f"{oubliees} session(s) MCP inactive(s) oubliee(s)")

    concierge = asyncio.create_task(_concierge_sessions())

    yield

    logger.info("Shutting down...")
    concierge.cancel()
    # Cancel all autosave tasks
    for task in _autosave_tasks.values():
        task.cancel()
    await container_manager.cleanup()


# Create FastAPI app
app = FastAPI(
    title="Blender MCP Server",
    description="Cloud Blender access via MCP protocol",
    version="1.0.0",
    lifespan=lifespan
)

# CORS. Le couple allow_origins=["*"] + allow_credentials=True est refuse
# par les navigateurs et ouvre inutilement la surface : les identifiants ne
# sont acceptes que si des origines sont explicitement declarees.
_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=bool(_cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
if os.path.exists("templates"):
    templates = Jinja2Templates(directory="templates")
else:
    templates = None


# =============================================================================
# MCP IMPLEMENTATION
# =============================================================================

# =============================================================================
# MODES MONO ET MULTI-UTILISATEUR
# =============================================================================
#
# MULTI_USER_MODE=true  : une passerelle qui demarre un container par
#                         utilisateur authentifie, via le socket Docker de
#                         l'hote. C'est le mode historique, hors pod.
# MULTI_USER_MODE=false : une seule instance Blender, dans le MEME container
#                         que ce serveur. C'est le mode deployable sur un pod
#                         Onyxia, ou il n'y a pas de demon Docker.
#
# Le mode ne touche PAS a l'authentification, requise dans les deux cas : il
# regle l'isolation des donnees, pas l'acces au service. Plusieurs agents
# peuvent travailler en parallele dans les deux modes, chacun avec sa session.

MULTI_USER_MODE: bool = os.environ.get("MULTI_USER_MODE", "true").lower() == "true"

# Ports de l'instance locale en mode mono, tels que les expose supervisord.
MONO_HOST = os.environ.get("BLENDER_HOST", "localhost")
MONO_API_PORT = int(os.environ.get("BLENDER_API_PORT", "8080"))
MONO_STREAM_PORT = int(os.environ.get("BLENDER_STREAM_PORT", "8081"))
MONO_NOVNC_PORT = int(os.environ.get("BLENDER_NOVNC_PORT", "6080"))


def _points_d_acces(user_id: str):
    """Ou joindre l'instance Blender de cet utilisateur.

    Retourne (hote, port_api, port_flux, port_novnc), ou leve si le mode multi
    n'a pas de session prete.
    """
    if not MULTI_USER_MODE:
        return MONO_HOST, MONO_API_PORT, MONO_STREAM_PORT, MONO_NOVNC_PORT

    session = container_manager.get_session(user_id)
    if not session:
        raise Exception("Aucune session active")
    return (container_manager.host_address,
            session.api_port, session.stream_port, session.novnc_port)


async def _ensure_session(user_id: str):
    """Ensure user has an active Blender container"""
    if not MULTI_USER_MODE:
        # L'instance est locale et demarree par supervisord : rien a allouer.
        return None

    session = container_manager.get_session(user_id)

    if not session:
        logger.info(f"Starting Blender for user {user_id[:8]}...")
        session = await container_manager.start_session(user_id)

        # Wait for ready
        for _ in range(60):
            session = container_manager.get_session(user_id)
            if session and session.status == "ready":
                logger.info(f"Blender ready for {user_id[:8]}")
                _start_autosave(user_id)
                return session
            await asyncio.sleep(1)

        raise Exception("Blender failed to start")

    return session


async def _call_blender(user_id: str, endpoint: str, method: str = "GET", data: dict = None):
    """Appelle l'API de l'instance Blender de cet utilisateur."""
    if not MULTI_USER_MODE:
        url = f"http://{MONO_HOST}:{MONO_API_PORT}{endpoint}"
        async with httpx.AsyncClient() as client:
            reponse = await client.request(method, url, json=data, timeout=180.0)
            if reponse.status_code >= 400:
                try:
                    corps = reponse.json()
                    detail = corps.get("detail", corps.get("error", reponse.status_code))
                except Exception:
                    detail = f"HTTP {reponse.status_code}"
                raise Exception(f"Blender API error: {detail}")
            return reponse.json()

    await _ensure_session(user_id)
    return await container_manager.execute_on_container(user_id, endpoint, method, data)


def _start_autosave(user_id: str):
    """Start background autosave for user"""
    if user_id in _autosave_tasks:
        return

    async def autosave_loop():
        while True:
            await asyncio.sleep(300)  # 5 minutes
            try:
                await _call_blender(user_id, "/api/save", "POST", {
                    "filepath": "/projects/autosave.blend"
                })
                logger.debug(f"Autosaved for user {user_id[:8]}")
            except Exception:
                pass

    _autosave_tasks[user_id] = asyncio.create_task(autosave_loop())


# MCP Tool implementations
async def mcp_list_objects(user_id: str) -> str:
    """List all objects in the current Blender scene."""
    try:
        objects = await _call_blender(user_id, "/api/objects")
        if not objects:
            return "Scene is empty. Create objects with create_object()."

        lines = [f"**Scene Objects** ({len(objects)} total)\n"]
        for obj in objects:
            loc = obj.get('location', [0, 0, 0])
            lines.append(f"- {obj['name']} ({obj['type']}) at ({loc[0]:.1f}, {loc[1]:.1f}, {loc[2]:.1f})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


async def mcp_create_object(user_id: str, obj_type: str, name: str = None,
                            location: list = None, scale: list = None,
                            color: list = None) -> str:
    """Create a 3D object in the scene."""
    try:
        result = await _call_blender(user_id, "/api/object", "POST", {
            "type": obj_type.upper(),
            "name": name,
            "location": location or [0, 0, 0],
            "scale": scale or [1, 1, 1]
        })
        obj_name = result.get("name", name or obj_type)

        if color:
            rgba = color if len(color) == 4 else list(color) + [1.0]
            await _call_blender(user_id, f"/api/object/{obj_name}/material", "POST", {"color": rgba})

        loc = location or [0, 0, 0]
        msg = f"Created {obj_name} at ({loc[0]}, {loc[1]}, {loc[2]})"
        if scale:
            msg += f" scale {scale}"
        if color:
            msg += f" with color ({color[0]:.1f}, {color[1]:.1f}, {color[2]:.1f})"
        return msg
    except Exception as e:
        return f"Error: {e}"


async def mcp_modify_object(user_id: str, name: str, location: list = None,
                            rotation: list = None, scale: list = None) -> str:
    """Modify an object's transform."""
    try:
        data = {}
        if location: data["location"] = location
        if rotation: data["rotation"] = rotation
        if scale: data["scale"] = scale

        await _call_blender(user_id, f"/api/object/{name}", "PUT", data)

        changes = []
        if location: changes.append(f"moved to {location}")
        if rotation: changes.append(f"rotated to {rotation}")
        if scale: changes.append(f"scaled to {scale}")

        return f"Modified {name}: " + ", ".join(changes)
    except Exception as e:
        return f"Error: {e}"


async def mcp_set_color(user_id: str, name: str, color: list) -> str:
    """Set an object's color."""
    try:
        rgba = color if len(color) == 4 else list(color) + [1.0]
        await _call_blender(user_id, f"/api/object/{name}/material", "POST", {"color": rgba})
        return f"Set {name} color to ({rgba[0]:.1f}, {rgba[1]:.1f}, {rgba[2]:.1f})"
    except Exception as e:
        return f"Error: {e}"


async def mcp_delete_object(user_id: str, name: str) -> str:
    """Delete an object from the scene."""
    try:
        await _call_blender(user_id, f"/api/object/{name}", "DELETE")
        return f"Deleted {name}"
    except Exception as e:
        return f"Error: {e}"


async def mcp_clear_scene(user_id: str) -> str:
    """Remove all objects from the scene (keeps camera and lights)."""
    try:
        code = """
import bpy
for obj in list(bpy.data.objects):
    if obj.type not in ('CAMERA', 'LIGHT'):
        bpy.data.objects.remove(obj, do_unlink=True)
result = "cleared"
"""
        await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        return "Scene cleared (camera and lights kept)"
    except Exception as e:
        return f"Error: {e}"


async def mcp_execute_python(user_id: str, code: str) -> str:
    """Execute Python code in Blender."""
    try:
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        if result.get("success"):
            return f"Executed. Result: {result.get('result', 'None')}"
        return f"Error: {result.get('error')}"
    except Exception as e:
        return f"Error: {e}"


async def mcp_gn_list_templates(user_id: str) -> str:
    """List Geometry Nodes templates available in gn_lib (inside Blender)."""
    code = (
        "import sys\n"
        "if '/app' not in sys.path:\n"
        "    sys.path.insert(0, '/app')\n"
        "import gn_lib\n"
        "result = gn_lib.list_templates()\n"
    )
    try:
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        if result.get("success"):
            return json.dumps(result.get("result"), ensure_ascii=False, indent=2)
        return f"Error: {result.get('error')}"
    except Exception as e:
        return f"Error: {e}"


async def mcp_gn_run_template(
    user_id: str,
    template_id: str,
    params: dict | None = None,
    object_name: str | None = None,
) -> str:
    """Build a professional Geometry Nodes setup from a versioned template."""
    payload = {
        "template_id": template_id,
        "params": params or {},
        "object_name": object_name,
    }
    code = (
        "import sys\n"
        "if '/app' not in sys.path:\n"
        "    sys.path.insert(0, '/app')\n"
        "import gn_lib\n"
        f"_p = {repr(payload)}\n"
        "result = gn_lib.run(\n"
        "    _p['template_id'],\n"
        "    params=_p.get('params') or {},\n"
        "    object_name=_p.get('object_name'),\n"
        ")\n"
    )
    try:
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        if not result.get("success"):
            return f"Error: {result.get('error')}"
        data = result.get("result")
        text = json.dumps(data, ensure_ascii=False, indent=2)
        if isinstance(data, dict) and data.get("ok") is False:
            return f"Error: {text}"
        return text
    except Exception as e:
        return f"Error: {e}"


async def mcp_save_project(user_id: str, name: str) -> str:
    """Save current scene as a project."""
    try:
        await _call_blender(user_id, "/api/save", "POST", {
            "filepath": f"/projects/{name}.blend"
        })
        return f"Saved as {name}"
    except Exception as e:
        return f"Error: {e}"


async def mcp_load_project(user_id: str, name: str) -> str:
    """Load a saved project."""
    try:
        await _call_blender(user_id, "/api/load", "POST", {
            "filepath": f"/projects/{name}.blend"
        })
        objects = await _call_blender(user_id, "/api/objects")
        return f"Loaded {name} ({len(objects)} objects)"
    except Exception as e:
        return f"Error: {e}"


async def mcp_save_as(user_id: str, name: str) -> str:
    """Save current scene as a new version/branch without modifying original."""
    try:
        await _call_blender(user_id, "/api/save", "POST", {
            "filepath": f"/projects/{name}.blend"
        })
        return f"Saved as new version: {name}"
    except Exception as e:
        return f"Error: {e}"


async def mcp_list_projects(user_id: str) -> str:
    """List all saved projects for this user."""
    try:
        code = """
import os
projects = []
if os.path.exists('/projects'):
    for f in os.listdir('/projects'):
        if f.endswith('.blend'):
            path = os.path.join('/projects', f)
            size = os.path.getsize(path)
            projects.append({'name': f[:-6], 'size': size})
result = projects
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        projects = result.get("result", [])
        if not projects:
            return "No saved projects yet."
        lines = ["**Saved Projects:**"]
        for p in projects:
            size_kb = p.get('size', 0) / 1024
            lines.append(f"- {p['name']} ({size_kb:.1f} KB)")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


async def mcp_duplicate_object(user_id: str, name: str, new_name: str = None) -> str:
    """Duplicate an object in the scene."""
    try:
        new_name = new_name or f"{name}_copy"
        code = f"""
import bpy
obj = bpy.data.objects.get('{name}')
if obj:
    new_obj = obj.copy()
    new_obj.data = obj.data.copy()
    new_obj.name = '{new_name}'
    bpy.context.collection.objects.link(new_obj)
    result = new_obj.name
else:
    result = None
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        if result.get("result"):
            return f"Duplicated {name} → {result.get('result')}"
        return f"Object '{name}' not found"
    except Exception as e:
        return f"Error: {e}"


async def mcp_undo(user_id: str) -> str:
    """Undo the last action in Blender."""
    try:
        # bpy.ops.ed.undo exige un contexte (fenetre + VIEW_3D). Sans
        # temp_override, l'appel echoue hors session interactive.
        code = """
import bpy
result = None
for window in bpy.context.window_manager.windows:
    screen = window.screen
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        with bpy.context.temp_override(window=window, screen=screen, area=area):
            bpy.ops.ed.undo()
        result = 'Undo performed'
        break
    if result:
        break
if result is None:
    result = 'Error: no VIEW_3D context for undo'
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        return result.get("result", "Undo performed")
    except Exception as e:
        return f"Error: {e}"


async def mcp_redo(user_id: str) -> str:
    """Redo the last undone action in Blender."""
    try:
        code = """
import bpy
result = None
for window in bpy.context.window_manager.windows:
    screen = window.screen
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        with bpy.context.temp_override(window=window, screen=screen, area=area):
            bpy.ops.ed.redo()
        result = 'Redo performed'
        break
    if result:
        break
if result is None:
    result = 'Error: no VIEW_3D context for redo'
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        return result.get("result", "Redo performed")
    except Exception as e:
        return f"Error: {e}"


# Collection management tools
async def mcp_list_collections(user_id: str) -> str:
    """List all collections in the scene."""
    try:
        code = """
import bpy
def get_collections(parent, level=0):
    result = []
    for col in parent.children:
        obj_count = len(col.objects)
        result.append({'name': col.name, 'level': level, 'objects': obj_count})
        result.extend(get_collections(col, level + 1))
    return result
collections = get_collections(bpy.context.scene.collection)
result = collections
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        collections = result.get("result", [])
        if not collections:
            return "No collections (only the default Scene Collection)."
        lines = ["**Collections:**"]
        for c in collections:
            indent = "  " * c['level']
            lines.append(f"{indent}- {c['name']} ({c['objects']} objects)")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


async def mcp_create_collection(user_id: str, name: str, parent: str = None) -> str:
    """Create a new collection."""
    try:
        parent_code = f"bpy.data.collections.get('{parent}')" if parent else "bpy.context.scene.collection"
        code = f"""
import bpy
new_col = bpy.data.collections.new('{name}')
parent = {parent_code}
if parent:
    parent.children.link(new_col)
result = new_col.name
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        return f"Created collection: {result.get('result', name)}"
    except Exception as e:
        return f"Error: {e}"


async def mcp_move_to_collection(user_id: str, object_name: str, collection_name: str) -> str:
    """Move an object to a collection."""
    try:
        code = f"""
import bpy
obj = bpy.data.objects.get('{object_name}')
col = bpy.data.collections.get('{collection_name}')
if obj and col:
    # Remove from current collections
    for c in obj.users_collection:
        c.objects.unlink(obj)
    # Add to new collection
    col.objects.link(obj)
    result = f"Moved {{obj.name}} to {{col.name}}"
else:
    result = None
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        if result.get("result"):
            return result.get("result")
        return f"Object '{object_name}' or collection '{collection_name}' not found"
    except Exception as e:
        return f"Error: {e}"


async def mcp_delete_collection(user_id: str, name: str, delete_objects: bool = False) -> str:
    """Delete a collection (optionally with its objects)."""
    try:
        # repr(bool(...)) -> True/False Python, pas false/true JSON.
        code = f"""
import bpy
col = bpy.data.collections.get('{name}')
if col:
    if {repr(bool(delete_objects))}:
        for obj in list(col.objects):
            bpy.data.objects.remove(obj)
    bpy.data.collections.remove(col)
    result = "deleted"
else:
    result = None
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        if result.get("result"):
            action = "with its objects" if delete_objects else "(objects kept)"
            return f"Deleted collection '{name}' {action}"
        return f"Collection '{name}' not found"
    except Exception as e:
        return f"Error: {e}"


async def mcp_toggle_collection_visibility(user_id: str, name: str) -> str:
    """Toggle visibility of a collection in the viewport."""
    try:
        code = f"""
import bpy
col = bpy.data.collections.get('{name}')
if col:
    col.hide_viewport = not col.hide_viewport
    result = 'hidden' if col.hide_viewport else 'visible'
else:
    result = None
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        if result.get("result"):
            return f"Collection '{name}' is now {result.get('result')}"
        return f"Collection '{name}' not found"
    except Exception as e:
        return f"Error: {e}"


# Asset management tools
async def mcp_list_materials(user_id: str) -> str:
    """List all materials in the project."""
    try:
        # ID.users est deja un int (compteur de references), pas une sequence.
        code = """
import bpy
materials = []
for mat in bpy.data.materials:
    materials.append({'name': mat.name, 'users': int(mat.users)})
result = materials
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        materials = result.get("result", [])
        if not materials:
            return "No materials in the project."
        lines = ["**Materials:**"]
        for m in materials:
            lines.append(f"- {m['name']} (used by {m['users']} objects)")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


async def mcp_create_material(user_id: str, name: str, color: list = None) -> str:
    """Create a new material with optional base color."""
    try:
        color = color or [0.8, 0.8, 0.8, 1.0]
        code = f"""
import bpy
mat = bpy.data.materials.new(name='{name}')
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get('Principled BSDF')
if bsdf:
    bsdf.inputs['Base Color'].default_value = {color}
result = mat.name
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        return f"Created material: {result.get('result', name)}"
    except Exception as e:
        return f"Error: {e}"


async def mcp_apply_material(user_id: str, object_name: str, material_name: str) -> str:
    """Apply a material to an object."""
    try:
        code = f"""
import bpy
obj = bpy.data.objects.get('{object_name}')
mat = bpy.data.materials.get('{material_name}')
if obj and mat and obj.data:
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    result = f"Applied {{mat.name}} to {{obj.name}}"
else:
    result = None
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        if result.get("result"):
            return result.get("result")
        return f"Object '{object_name}' or material '{material_name}' not found"
    except Exception as e:
        return f"Error: {e}"


async def mcp_delete_material(user_id: str, name: str) -> str:
    """Delete a material from the project."""
    try:
        code = f"""
import bpy
mat = bpy.data.materials.get('{name}')
if mat:
    bpy.data.materials.remove(mat)
    result = "deleted"
else:
    result = None
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        if result.get("result"):
            return f"Deleted material: {name}"
        return f"Material '{name}' not found"
    except Exception as e:
        return f"Error: {e}"


async def mcp_list_meshes(user_id: str) -> str:
    """List all mesh data in the project."""
    try:
        # mesh.users est un int ; vertices/polygons restent des collections.
        code = """
import bpy
meshes = []
for mesh in bpy.data.meshes:
    meshes.append({
        'name': mesh.name,
        'users': int(mesh.users),
        'verts': len(mesh.vertices),
        'faces': len(mesh.polygons),
    })
result = meshes
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        meshes = result.get("result", [])
        if not meshes:
            return "No meshes in the project."
        lines = ["**Meshes:**"]
        for m in meshes:
            lines.append(f"- {m['name']}: {m['verts']} verts, {m['faces']} faces (users: {m['users']})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


async def mcp_cleanup_unused(user_id: str) -> str:
    """Remove all unused data blocks (materials, meshes, etc.)."""
    try:
        code = """
import bpy
# Count before
mats_before = len(bpy.data.materials)
meshes_before = len(bpy.data.meshes)
images_before = len(bpy.data.images)

# Purge orphan data
bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

# Count after
mats_after = len(bpy.data.materials)
meshes_after = len(bpy.data.meshes)
images_after = len(bpy.data.images)

result = {
    'materials': mats_before - mats_after,
    'meshes': meshes_before - meshes_after,
    'images': images_before - images_after
}
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        data = result.get("result", {})
        if data:
            return f"Cleaned up: {data.get('materials', 0)} materials, {data.get('meshes', 0)} meshes, {data.get('images', 0)} images"
        return "Cleanup completed"
    except Exception as e:
        return f"Error: {e}"


async def mcp_initialize_scene(user_id: str, clear_default: bool = True,
                               setup_camera: bool = True, setup_lighting: bool = True) -> str:
    """Initialize a clean scene for a new project (Pattern 4.1)."""
    try:
        code = f"""
import bpy
import math

result_parts = []

# 1. Clear default objects if requested
if {clear_default}:
    default_objects = ['Cube', 'Light', 'Camera']
    for name in default_objects:
        obj = bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
    result_parts.append("Cleared defaults")

# 2. Setup camera if requested
if {setup_camera}:
    bpy.ops.object.camera_add(location=(7, -7, 5))
    cam = bpy.context.active_object
    cam.name = "CAM_Main"
    cam.rotation_euler = (1.1, 0, 0.8)
    bpy.context.scene.camera = cam
    result_parts.append("Camera ready")

# 3. Setup basic lighting if requested
if {setup_lighting}:
    bpy.ops.object.light_add(type='SUN', location=(5, 5, 10))
    sun = bpy.context.active_object
    sun.name = "LIGHT_Sun_Main"
    sun.data.energy = 3
    sun.rotation_euler = (math.radians(50), 0, math.radians(45))
    result_parts.append("Lighting ready")

# 4. Configure render defaults
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = 128
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080

result = "Scene initialized: " + ", ".join(result_parts)
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        return result.get("result", "Scene initialized")
    except Exception as e:
        return f"Error: {e}"


async def mcp_setup_studio_lighting(user_id: str) -> str:
    """Setup professional 3-point studio lighting (key, fill, rim lights)."""
    try:
        code = """
import bpy
import math

# Remove existing lights
for obj in list(bpy.data.objects):
    if obj.type == 'LIGHT':
        bpy.data.objects.remove(obj, do_unlink=True)

# Key Light (main light, 45 degrees front-right)
bpy.ops.object.light_add(type='AREA', location=(4, -4, 6))
key = bpy.context.active_object
key.name = "LIGHT_Key"
key.data.energy = 500
key.data.size = 2
key.rotation_euler = (math.radians(60), 0, math.radians(45))
key.data.color = (1, 0.95, 0.9)  # Slightly warm

# Fill Light (softer, opposite side)
bpy.ops.object.light_add(type='AREA', location=(-4, -4, 4))
fill = bpy.context.active_object
fill.name = "LIGHT_Fill"
fill.data.energy = 200
fill.data.size = 3
fill.rotation_euler = (math.radians(60), 0, math.radians(-45))
fill.data.color = (0.9, 0.95, 1)  # Slightly cool

# Rim Light (backlight for edge definition)
bpy.ops.object.light_add(type='AREA', location=(0, 4, 5))
rim = bpy.context.active_object
rim.name = "LIGHT_Rim"
rim.data.energy = 300
rim.data.size = 1
rim.rotation_euler = (math.radians(120), 0, math.radians(180))
rim.data.color = (1, 1, 1)

result = "Studio lighting created: LIGHT_Key, LIGHT_Fill, LIGHT_Rim"
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        return result.get("result", "Studio lighting setup complete")
    except Exception as e:
        return f"Error: {e}"


async def mcp_setup_camera(user_id: str, target: str = None, distance: float = 10.0) -> str:
    """Setup camera aimed at target object or origin."""
    try:
        target_code = f"bpy.data.objects.get('{target}')" if target else "None"
        code = f"""
import bpy
from mathutils import Vector
import math

# Create camera if not exists
cam = bpy.data.objects.get('Camera')
if not cam:
    bpy.ops.object.camera_add()
    cam = bpy.context.active_object
    cam.name = "Camera"

# Position camera
distance = {distance}
cam.location = (distance * 0.7, -distance * 0.7, distance * 0.5)

# Point at target or origin
target_obj = {target_code}
if target_obj:
    target_pos = Vector(target_obj.location)
else:
    target_pos = Vector((0, 0, 0))

direction = target_pos - cam.location
rot_quat = direction.to_track_quat('-Z', 'Y')
cam.rotation_euler = rot_quat.to_euler()

# Set as active camera
bpy.context.scene.camera = cam

result = f"Camera positioned at {{tuple(cam.location)}}, aimed at {{tuple(target_pos)}}"
"""
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        return result.get("result", "Camera setup complete")
    except Exception as e:
        return f"Error: {e}"


async def mcp_get_scene_info(user_id: str) -> str:
    """Get comprehensive scene information (use at start of each session)."""
    try:
        scene = await _call_blender(user_id, "/api/scene")
        objects = await _call_blender(user_id, "/api/objects")

        # Count objects by type
        type_counts = {}
        meshes = []
        lights = []
        cameras = []

        for obj in objects:
            obj_type = obj.get('type', 'UNKNOWN')
            type_counts[obj_type] = type_counts.get(obj_type, 0) + 1

            if obj_type == 'MESH':
                meshes.append(obj['name'])
            elif obj_type == 'LIGHT':
                lights.append(obj['name'])
            elif obj_type == 'CAMERA':
                cameras.append(obj['name'])

        # Build comprehensive info
        info = [
            f"**Scene: {scene.get('name', 'Scene')}**",
            f"",
            f"**Stats:**",
            f"- Total objects: {len(objects)}",
        ]

        for obj_type, count in sorted(type_counts.items()):
            info.append(f"- {obj_type}: {count}")

        info.append(f"")
        info.append(f"**Render Settings:**")
        info.append(f"- Resolution: {scene.get('render_resolution_x', 1920)}x{scene.get('render_resolution_y', 1080)}")
        info.append(f"- Frame: {scene.get('frame_current', 1)}/{scene.get('frame_end', 250)}")

        if cameras:
            info.append(f"")
            info.append(f"**Cameras:** {', '.join(cameras)}")
            info.append(f"- Active: {scene.get('camera', 'None')}")

        if lights:
            info.append(f"")
            info.append(f"**Lights:** {', '.join(lights)}")

        if meshes:
            info.append(f"")
            info.append(f"**Mesh Objects:**")
            for mesh in meshes[:10]:  # Limit to 10
                for obj in objects:
                    if obj['name'] == mesh:
                        loc = obj.get('location', [0, 0, 0])
                        info.append(f"- {mesh} at ({loc[0]:.1f}, {loc[1]:.1f}, {loc[2]:.1f})")
                        break
            if len(meshes) > 10:
                info.append(f"- ... and {len(meshes) - 10} more")

        return "\n".join(info)
    except Exception as e:
        return f"Error: {e}"


# Meta tools for system-level Blender control
async def mcp_send_keypress(user_id: str, key: str) -> str:
    """Send a keypress to Blender (e.g., Escape to dismiss dialogs)."""
    try:
        result = await _call_blender(user_id, "/api/keypress", "POST", {"key": key})
        return f"Sent keypress: {result.get('key', key)}"
    except Exception as e:
        return f"Error: {e}"


async def mcp_get_screenshot(user_id: str, width: int = 1920, height: int = 1080) -> dict:
    """Take a screenshot of the Blender viewport. Returns image data for MCP."""
    try:
        result = await _call_blender(user_id, f"/api/screenshot?width={width}&height={height}")
        # The Blender addon returns "data" as base64
        image_data = result.get("data") or result.get("image_data")
        if result.get("success") and image_data:
            # Return dict with image data for MCP image content block
            return {
                "_type": "image",
                "data": image_data,
                "mimeType": "image/png",
                "width": width,
                "height": height
            }
        error = result.get("error", "Unknown error")
        return {"_type": "error", "message": f"Screenshot failed: {error}"}
    except Exception as e:
        return {"_type": "error", "message": f"Error: {e}"}


async def mcp_restart_blender(user_id: str) -> str:
    """Restart the Blender process in the container."""
    try:
        result = await _call_blender(user_id, "/api/restart", "POST")
        return f"Blender is restarting. Wait a few seconds before next command."
    except Exception as e:
        return f"Error: {e}"


async def mcp_send_click(user_id: str, x: int, y: int, button: int = 1) -> str:
    """Send a mouse click to specific coordinates in Blender."""
    try:
        result = await _call_blender(user_id, "/api/click", "POST", {"x": x, "y": y, "button": button})
        button_name = {1: "left", 2: "middle", 3: "right"}.get(button, str(button))
        return f"Clicked {button_name} button at ({x}, {y})"
    except Exception as e:
        return f"Error: {e}"


async def mcp_detect_gpu(user_id: str) -> str:
    """Detect available GPU devices for rendering."""
    try:
        result = await _call_blender(user_id, "/api/gpu")
        if not result.get("success"):
            return f"GPU detection failed: {result.get('error', 'Unknown error')}"

        gpus = result.get("gpus", {})
        recommended = result.get("recommended", {})

        response = "**GPU Detection Results**\n\n"

        # NVIDIA GPUs
        if gpus.get("cuda"):
            response += "**NVIDIA GPUs (CUDA)**:\n"
            for gpu in gpus["cuda"]:
                response += f"- {gpu['name']} (Index: {gpu['index']}, Memory: {gpu['memory_mb']} MB)\n"

        # NVIDIA OptiX
        if gpus.get("optix"):
            response += "\n**OptiX Support** (RTX GPUs):\n"
            for gpu in gpus["optix"]:
                response += f"- {gpu['name']}\n"

        # AMD GPUs
        if gpus.get("hip"):
            response += "\n**AMD GPUs (HIP)**:\n"
            if gpus["hip"]:
                response += "- AMD GPU detected\n"

        # Blender's view
        if gpus.get("blender_devices"):
            response += "\n**Blender Devices**:\n"
            for dev in gpus["blender_devices"]:
                status = "✓ Enabled" if dev.get("use") else "✗ Disabled"
                response += f"- {dev['name']} ({dev['type']}) [{status}]\n"

        # Recommendation
        response += f"\n**Recommended**: {recommended.get('device')} ({recommended.get('type')})\n"
        response += f"Reason: {recommended.get('reason')}\n"

        return response
    except Exception as e:
        return f"Error: {e}"


async def mcp_configure_render(user_id: str, engine: str = "CYCLES", device: str = "GPU",
                               device_type: str = "CUDA", samples: int = 128,
                               use_denoising: bool = True) -> str:
    """Configure render engine and device (GPU/CPU)."""
    try:
        result = await _call_blender(user_id, "/api/render/configure", "POST", {
            "engine": engine,
            "device": device,
            "device_type": device_type,
            "samples": samples,
            "use_denoising": use_denoising
        })

        if not result.get("success"):
            error = result.get("error", "Unknown error")
            warning = result.get("warning")
            if warning:
                return f"⚠️ {warning}"
            return f"Configuration failed: {error}"

        response = "**Render Configuration Updated**\n\n"
        response += f"- Engine: {result.get('engine')}\n"
        response += f"- Device: {result.get('device')}\n"

        if result.get('device_type'):
            response += f"- Device Type: {result.get('device_type')}\n"

        if result.get('samples'):
            response += f"- Samples: {result.get('samples')}\n"

        if result.get('denoising') is not None:
            response += f"- Denoising: {'Enabled' if result.get('denoising') else 'Disabled'}\n"

        return response
    except Exception as e:
        return f"Error: {e}"


# MCP Protocol Handler
MCP_TOOLS = {
    "list_objects": {
        "description": "List all objects in the current Blender scene. Returns name, type, and position of each object.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "create_object": {
        "description": "Create a 3D object in the scene.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "Object type: CUBE, SPHERE, CYLINDER, CONE, TORUS, PLANE, MONKEY"},
                "name": {"type": "string", "description": "Optional name for the object"},
                "location": {"type": "array", "items": {"type": "number"}, "description": "Position [x, y, z]"},
                "color": {"type": "array", "items": {"type": "number"}, "description": "RGBA color [r, g, b, a] with values 0-1"}
            },
            "required": ["type"]
        }
    },
    "modify_object": {
        "description": "Modify an object's transform (position, rotation, scale).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name"},
                "location": {"type": "array", "items": {"type": "number"}, "description": "New position [x, y, z]"},
                "rotation": {"type": "array", "items": {"type": "number"}, "description": "New rotation in degrees [x, y, z]"},
                "scale": {"type": "array", "items": {"type": "number"}, "description": "New scale [x, y, z]"}
            },
            "required": ["name"]
        }
    },
    "set_color": {
        "description": "Set an object's color.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name"},
                "color": {"type": "array", "items": {"type": "number"}, "description": "RGBA [r, g, b, a] with values 0-1"}
            },
            "required": ["name", "color"]
        }
    },
    "delete_object": {
        "description": "Delete an object from the scene.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name to delete"}
            },
            "required": ["name"]
        }
    },
    "clear_scene": {
        "description": "Remove all objects from the scene (keeps camera and lights).",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "execute_python": {
        "description": "Execute Python code in Blender. Use 'bpy' module. Set 'result' variable to return a value.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"}
            },
            "required": ["code"]
        }
    },
    "save_project": {
        "description": "Save current scene as a project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"}
            },
            "required": ["name"]
        }
    },
    "load_project": {
        "description": "Load a saved project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name to load"}
            },
            "required": ["name"]
        }
    },
    "save_as": {
        "description": "Save current scene as a new version/branch. Useful for creating checkpoints or variations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "New project name (e.g., 'scene_v2', 'experiment_1')"}
            },
            "required": ["name"]
        }
    },
    "list_projects": {
        "description": "List all saved projects for this user.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "duplicate_object": {
        "description": "Duplicate an existing object in the scene.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name to duplicate"},
                "new_name": {"type": "string", "description": "Name for the duplicate (optional)"}
            },
            "required": ["name"]
        }
    },
    "undo": {
        "description": "Undo the last action in Blender.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "redo": {
        "description": "Redo the last undone action in Blender.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "list_collections": {
        "description": "List all collections in the scene with their object counts.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "create_collection": {
        "description": "Create a new collection to organize objects.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Collection name"},
                "parent": {"type": "string", "description": "Parent collection name (optional)"}
            },
            "required": ["name"]
        }
    },
    "move_to_collection": {
        "description": "Move an object to a specific collection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Object to move"},
                "collection_name": {"type": "string", "description": "Target collection"}
            },
            "required": ["object_name", "collection_name"]
        }
    },
    "delete_collection": {
        "description": "Delete a collection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Collection name"},
                "delete_objects": {"type": "boolean", "description": "Also delete objects in collection (default false)"}
            },
            "required": ["name"]
        }
    },
    "toggle_collection_visibility": {
        "description": "Show/hide a collection in the viewport.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Collection name"}
            },
            "required": ["name"]
        }
    },
    "list_materials": {
        "description": "List all materials in the project.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "create_material": {
        "description": "Create a new material with optional base color.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Material name"},
                "color": {"type": "array", "items": {"type": "number"}, "description": "RGBA color [r, g, b, a]"}
            },
            "required": ["name"]
        }
    },
    "apply_material": {
        "description": "Apply a material to an object.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Object to apply material to"},
                "material_name": {"type": "string", "description": "Material to apply"}
            },
            "required": ["object_name", "material_name"]
        }
    },
    "delete_material": {
        "description": "Delete a material from the project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Material name"}
            },
            "required": ["name"]
        }
    },
    "list_meshes": {
        "description": "List all mesh data blocks in the project with vertex/face counts.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "cleanup_unused": {
        "description": "Remove all unused data blocks (orphan materials, meshes, images).",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "initialize_scene": {
        "description": "Initialize a clean scene for a new project. Clears defaults, sets up camera and lighting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "clear_default": {"type": "boolean", "description": "Remove default Cube/Light/Camera (default true)"},
                "setup_camera": {"type": "boolean", "description": "Create and position camera (default true)"},
                "setup_lighting": {"type": "boolean", "description": "Create basic sun lighting (default true)"}
            },
            "required": []
        }
    },
    "get_scene_info": {
        "description": "Get comprehensive scene information. Use at start of each session and before major modifications.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "setup_studio_lighting": {
        "description": "Setup professional 3-point studio lighting (key, fill, rim lights). Removes existing lights.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "setup_camera": {
        "description": "Setup and position camera aimed at target object or origin.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Object name to aim at (optional, defaults to origin)"},
                "distance": {"type": "number", "description": "Distance from target (default 10.0)"}
            },
            "required": []
        }
    },
    "send_keypress": {
        "description": "Send a keypress to Blender (e.g., 'Escape' to dismiss dialogs, 'a' to select all).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key to press (e.g., 'Escape', 'Return', 'a', 'ctrl+z')"}
            },
            "required": ["key"]
        }
    },
    "get_screenshot": {
        "description": (
            "Take a screenshot of the live Blender display (X11). "
            "For interactive GUI access, call get_canvas_url and share the link with the user."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {"type": "integer", "description": "Screenshot width (default 1920)"},
                "height": {"type": "integer", "description": "Screenshot height (default 1080)"}
            },
            "required": []
        }
    },
    "get_canvas_url": {
        "description": (
            "Return the URL of the interactive Blender desktop (full GUI in the browser). "
            "Always share this link with the user so they can open the live Blender UI "
            "in their browser. Prefer this over describing the UI only in text."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "blender_desktop_ui": {
        "description": (
            "Open the interactive Blender Desktop view in the conversation (MCP Apps). "
            "Use when the user wants to see or interact with the scene visually. "
            "Also share get_canvas_url for hosts without MCP Apps support."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "_meta": {"ui": {"resourceUri": "ui://blenderremotemcp/desktop"}},
    },
    "restart_blender": {
        "description": "Restart the Blender process. Use if Blender becomes unresponsive.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "send_click": {
        "description": "Send a mouse click to specific coordinates in Blender window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
                "button": {"type": "integer", "description": "Mouse button (1=left, 2=middle, 3=right)"}
            },
            "required": ["x", "y"]
        }
    },
    "detect_gpu": {
        "description": "Detect available GPU devices for rendering. Shows NVIDIA (CUDA/OptiX), AMD (HIP) GPUs and recommends best device.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "configure_render": {
        "description": "Configure render engine and device. Use CYCLES for photorealistic rendering with GPU acceleration.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "engine": {
                    "type": "string",
                    "description": "Render engine: CYCLES (photorealistic), BLENDER_EEVEE (realtime), BLENDER_WORKBENCH (fast preview)",
                    "default": "CYCLES"
                },
                "device": {
                    "type": "string",
                    "description": "Device type: GPU or CPU",
                    "default": "GPU"
                },
                "device_type": {
                    "type": "string",
                    "description": "GPU type: CUDA (NVIDIA), OPTIX (NVIDIA RTX), HIP (AMD)",
                    "default": "CUDA"
                },
                "samples": {
                    "type": "integer",
                    "description": "Render quality samples (higher = better quality but slower). Recommended: 128-512",
                    "default": 128
                },
                "use_denoising": {
                    "type": "boolean",
                    "description": "Enable AI denoising to reduce render noise",
                    "default": True
                }
            },
            "required": []
        }
    },
    "list_recipes": {
        "description": (
            "List guided workflow recipes (expertise/recipes). "
            "Prefer a recipe over improvising with execute_python when one matches."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "Optional tag filter (studio, archviz, …)"}
            },
            "required": []
        }
    },
    "get_recipe": {
        "description": "Get full recipe definition (steps, parameters) by id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Recipe id (e.g. clear_and_studio)"}
            },
            "required": ["id"]
        }
    },
    "run_recipe": {
        "description": (
            "Execute a recipe step-by-step using primitive MCP tools. "
            "Pass parameter values matching the recipe schema."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Recipe id"},
                "params": {"type": "object", "description": "Recipe parameters"}
            },
            "required": ["id"]
        }
    },
    "get_blender_context": {
        "description": (
            "Guidance context for the agent (phase hint, skills/recipes indexes). "
            "For live scene data, also call get_scene_info."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "phase": {
                    "type": "string",
                    "description": "Optional phase: setup|model|shade|light|render|review"
                }
            },
            "required": []
        }
    },
    "gn_list_templates": {
        "description": (
            "List professional Geometry Nodes templates (gn_lib). "
            "Prefer gn_run_template over hand-built trees for complex results."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    "gn_run_template": {
        "description": (
            "Build a versioned Geometry Nodes setup in the live scene "
            "(scatter_poisson, terrain_displace, facade_extrude, curve_railing). "
            "Read skill://geometry-nodes first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "Template id from gn_list_templates"
                },
                "params": {
                    "type": "object",
                    "description": "Template parameters (see gn_list_templates)"
                },
                "object_name": {
                    "type": "string",
                    "description": "Optional host object name"
                }
            },
            "required": ["template_id"]
        }
    },
}


def _public_base_url(request: Request = None, base_url: str = "") -> str:
    """URL publique du service (canvas, MCP), sans slash final.

    Priorite : argument explicite, PUBLIC_BASE_URL, en-tetes proxy, puis
    request.url. Sans requete : localhost:8100 (compose).
    """
    if base_url:
        return base_url.rstrip("/")
    env = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if env:
        return env
    if request is not None:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
        host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or request.url.netloc
        )
        if host:
            return f"{proto}://{host}".rstrip("/")
    return "http://localhost:8100"


oauth_mcp.mount_oauth(
    app,
    auth_manager=auth_manager,
    public_base_url=_public_base_url,
    templates=templates,
)


def _canvas_url(base_url: str, api_key: str, *, embed: bool = False) -> str:
    """URL canonique du bureau immersif (/desktop). /canvas reste un alias HTTP."""
    base = (base_url or "http://localhost:8100").rstrip("/")
    path = f"{base}/desktop"
    params = []
    if api_key:
        params.append(f"token={api_key}")
    if embed:
        params.append("embed=1")
    if not params:
        return path
    return f"{path}?{'&'.join(params)}"


def _mcp_instructions(base_url: str) -> str:
    """Texte injecte au client LLM a l'initialize (pattern QgisRemoteMCP)."""
    base = (base_url or "http://localhost:8100").rstrip("/")
    return (
        "You control a live Blender 4.0 instance (full GUI in the browser).\n"
        "\n"
        "## Expertise first (do not improvise blindly)\n"
        "1. Read skills via resources (`skill://bpy-pitfalls`, `skill://modelling`, "
        "`skill://materials`, `skill://lighting`, `skill://camera-render`).\n"
        "2. Prefer **list_recipes** / **run_recipe** when a workflow matches "
        "(studio_product, clear_and_studio, archviz_exterior, gn_scatter_instances, gn_curve_to_mesh_pipe).\n"
        "   For complex Geometry Nodes prefer **gn_list_templates** / **gn_run_template** "
        "(terrain, facade, scatter poisson, railing).\n"
        "3. Use **prompts** (demarrer_studio, archviz_exterieur, auditer_scene, geometry_nodes) as starters.\n"
        "   For Geometry Nodes read skill://geometry-nodes before execute_python.\n"
        "4. Only then use primitive tools or short `execute_python` (assign `result`).\n"
        "\n"
        "## Web UI — give this link to the user\n"
        "Call **get_canvas_url** (and **blender_desktop_ui** if MCP Apps) after "
        "meaningful scene changes so the user can validate visually.\n"
        f"Desktop path: `{base}/desktop?token=<API key from the MCP Bearer header>`.\n"
        "\n"
        "## Recommended workflow\n"
        "1. get_blender_context / get_scene_info — know where you are.\n"
        "2. Build via recipe or tools (`create_object`, materials, lighting, …).\n"
        "3. **get_screenshot** — verify in-chat.\n"
        "4. **get_canvas_url** — live GUI for the user.\n"
        "\n"
        "## Notes\n"
        "- Auth: desktop URL embeds the same API key as the MCP Bearer token.\n"
        "- On CPU-only hosts, prefer Cycles CPU + denoising via `configure_render`.\n"
        "- Domain expertise (BIM, roads, mesh) lives outside this workspace — "
        "compose other MCP servers; do not invent norms in execute_python.\n"
    )


async def handle_mcp_request(body: dict, user_id: str, session_id: str = "",
                             portee=None, base_url: str = "",
                             api_key: str = "") -> dict:
    """Traite un message JSON-RPC MCP deja decode.

    Le decodage et le cadrage du transport sont faits par mcp_handler : cette
    fonction ne connait que le protocole, pas le canal.
    base_url / api_key servent aux instructions et a get_canvas_url.
    """
    method = body.get("method", "")
    params = body.get("params", {})
    req_id = body.get("id")
    base = _public_base_url(base_url=base_url)

    # Initialize
    if method == "initialize":
        # Negociation de version : on retient celle du client si on la parle,
        # sinon on annonce la notre et c'est au client de s'aligner.
        demandee = params.get("protocolVersion", "")
        version = demandee if demandee in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        if session_id:
            _touch_session(
                session_id, user_id,
                client=params.get("clientInfo"),
                protocol=version,
            )
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                    "extensions": {
                        "io.modelcontextprotocol/ui": {},
                    },
                },
                "serverInfo": {
                    "name": "BlenderRemoteMCP",
                    "version": "2.0.0"
                },
                "instructions": _mcp_instructions(base),
            }
        }

    # Notifications (no response needed)
    if method == "notifications/initialized":
        # Start Blender container immediately in background
        asyncio.create_task(_ensure_session(user_id))
        logger.info(f"Pre-starting Blender for user {user_id[:8]}...")
        return None

    # List tools
    if method == "tools/list":
        # Filtrer plutot que refuser a l'appel : un agent ne doit pas voir
        # des outils qu'il ne peut pas utiliser, sinon il les tentera.
        tools = []
        for name, info in MCP_TOOLS.items():
            if not _outil_autorise(name, portee):
                continue
            entry = {
                "name": name,
                "description": info["description"],
                "inputSchema": info["inputSchema"],
            }
            if info.get("_meta"):
                entry["_meta"] = info["_meta"]
            tools.append(entry)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": tools}
        }

    # Call tool
    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name not in MCP_TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
            }

        # Le filtrage de tools/list ne suffit pas : rien n'empeche un client
        # d'appeler un nom qu'il n'a pas vu.
        if not _outil_autorise(tool_name, portee):
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32000,
                    "message": f"Outil hors de la portee de cette cle : {tool_name}",
                }
            }

        # Execute tool
        try:
            if tool_name == "list_objects":
                result = await mcp_list_objects(user_id)
            elif tool_name == "create_object":
                result = await mcp_create_object(
                    user_id,
                    arguments.get("type", "CUBE"),
                    arguments.get("name"),
                    arguments.get("location"),
                    arguments.get("scale"),
                    arguments.get("color")
                )
            elif tool_name == "modify_object":
                result = await mcp_modify_object(
                    user_id,
                    arguments.get("name"),
                    arguments.get("location"),
                    arguments.get("rotation"),
                    arguments.get("scale")
                )
            elif tool_name == "set_color":
                result = await mcp_set_color(user_id, arguments.get("name"), arguments.get("color"))
            elif tool_name == "delete_object":
                result = await mcp_delete_object(user_id, arguments.get("name"))
            elif tool_name == "clear_scene":
                result = await mcp_clear_scene(user_id)
            elif tool_name == "execute_python":
                result = await mcp_execute_python(user_id, arguments.get("code", ""))
            elif tool_name == "save_project":
                result = await mcp_save_project(user_id, arguments.get("name"))
            elif tool_name == "load_project":
                result = await mcp_load_project(user_id, arguments.get("name"))
            elif tool_name == "save_as":
                result = await mcp_save_as(user_id, arguments.get("name"))
            elif tool_name == "list_projects":
                result = await mcp_list_projects(user_id)
            elif tool_name == "duplicate_object":
                result = await mcp_duplicate_object(
                    user_id,
                    arguments.get("name"),
                    arguments.get("new_name")
                )
            elif tool_name == "undo":
                result = await mcp_undo(user_id)
            elif tool_name == "redo":
                result = await mcp_redo(user_id)
            elif tool_name == "list_collections":
                result = await mcp_list_collections(user_id)
            elif tool_name == "create_collection":
                result = await mcp_create_collection(
                    user_id,
                    arguments.get("name"),
                    arguments.get("parent")
                )
            elif tool_name == "move_to_collection":
                result = await mcp_move_to_collection(
                    user_id,
                    arguments.get("object_name"),
                    arguments.get("collection_name")
                )
            elif tool_name == "delete_collection":
                result = await mcp_delete_collection(
                    user_id,
                    arguments.get("name"),
                    arguments.get("delete_objects", False)
                )
            elif tool_name == "toggle_collection_visibility":
                result = await mcp_toggle_collection_visibility(user_id, arguments.get("name"))
            elif tool_name == "list_materials":
                result = await mcp_list_materials(user_id)
            elif tool_name == "create_material":
                result = await mcp_create_material(
                    user_id,
                    arguments.get("name"),
                    arguments.get("color")
                )
            elif tool_name == "apply_material":
                result = await mcp_apply_material(
                    user_id,
                    arguments.get("object_name"),
                    arguments.get("material_name")
                )
            elif tool_name == "delete_material":
                result = await mcp_delete_material(user_id, arguments.get("name"))
            elif tool_name == "list_meshes":
                result = await mcp_list_meshes(user_id)
            elif tool_name == "cleanup_unused":
                result = await mcp_cleanup_unused(user_id)
            elif tool_name == "initialize_scene":
                result = await mcp_initialize_scene(
                    user_id,
                    arguments.get("clear_default", True),
                    arguments.get("setup_camera", True),
                    arguments.get("setup_lighting", True)
                )
            elif tool_name == "get_scene_info":
                result = await mcp_get_scene_info(user_id)
            elif tool_name == "setup_studio_lighting":
                result = await mcp_setup_studio_lighting(user_id)
            elif tool_name == "setup_camera":
                result = await mcp_setup_camera(
                    user_id,
                    arguments.get("target"),
                    arguments.get("distance", 10.0)
                )
            elif tool_name == "send_keypress":
                result = await mcp_send_keypress(user_id, arguments.get("key", "Escape"))
            elif tool_name == "get_screenshot":
                screenshot_result = await mcp_get_screenshot(
                    user_id,
                    arguments.get("width", 1920),
                    arguments.get("height", 1080)
                )
                # Handle image response specially
                if isinstance(screenshot_result, dict) and screenshot_result.get("_type") == "image":
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{
                                "type": "image",
                                "data": screenshot_result["data"],
                                "mimeType": screenshot_result["mimeType"]
                            }],
                            "isError": False
                        }
                    }
                elif isinstance(screenshot_result, dict) and screenshot_result.get("_type") == "error":
                    result = screenshot_result.get("message", "Unknown error")
                else:
                    result = str(screenshot_result)
            elif tool_name == "get_canvas_url":
                url = _canvas_url(base, api_key)
                result = (
                    f"Blender desktop (share with the user):\n{url}\n\n"
                    "Open this URL in a browser to see and control the live Blender GUI."
                )
            elif tool_name == "blender_desktop_ui":
                url = _canvas_url(base, api_key)
                result = (
                    "Blender Desktop UI opened for hosts that support MCP Apps "
                    f"(resource ui://blenderremotemcp/desktop).\n"
                    f"Fallback full desktop link for the user: {url}"
                )
            elif tool_name == "restart_blender":
                result = await mcp_restart_blender(user_id)
            elif tool_name == "detect_gpu":
                result = await mcp_detect_gpu(user_id)
            elif tool_name == "configure_render":
                result = await mcp_configure_render(
                    user_id,
                    arguments.get("engine", "CYCLES"),
                    arguments.get("device", "GPU"),
                    arguments.get("device_type", "CUDA"),
                    arguments.get("samples", 128),
                    arguments.get("use_denoising", True)
                )
            elif tool_name == "send_click":
                result = await mcp_send_click(
                    user_id,
                    arguments.get("x", 0),
                    arguments.get("y", 0),
                    arguments.get("button", 1)
                )
            elif tool_name == "list_recipes":
                result = json.dumps(
                    guidance_mod.catalog.list_recipes(arguments.get("tag") or ""),
                    ensure_ascii=False,
                    indent=2,
                )
            elif tool_name == "get_recipe":
                recipe = guidance_mod.catalog.get_recipe(arguments.get("id", ""))
                result = (
                    json.dumps(recipe, ensure_ascii=False, indent=2)
                    if recipe else "Error: recipe inconnue"
                )
            elif tool_name == "run_recipe":
                result = await _executer_recipe(
                    arguments.get("id", ""),
                    arguments.get("params") or {},
                    user_id=user_id,
                    session_id=session_id,
                    portee=portee,
                    base_url=base,
                    api_key=api_key,
                )
            elif tool_name == "get_blender_context":
                phase = arguments.get("phase") or "model"
                result = json.dumps(
                    build_context(
                        phase,
                        extra={
                            "skills": list(guidance_mod.catalog.skills.keys()),
                            "recipes": list(guidance_mod.catalog.recipes.keys()),
                            "note": "Pour l'état live bpy, appelle aussi get_scene_info.",
                        },
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            elif tool_name == "gn_list_templates":
                result = await mcp_gn_list_templates(user_id)
            elif tool_name == "gn_run_template":
                result = await mcp_gn_run_template(
                    user_id,
                    arguments.get("template_id", ""),
                    arguments.get("params") or {},
                    arguments.get("object_name"),
                )
            else:
                result = f"Tool {tool_name} not implemented"

            if isinstance(result, str) and not result.startswith("Error:"):
                ctx = build_context(infer_phase(tool_name))
                result = f"{result}\n\n_context: {json.dumps(ctx, ensure_ascii=False)}"

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result}],
                    "isError": isinstance(result, str) and result.startswith("Error:")
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True
                }
            }

    # List resources
    if method == "resources/list":
        resources = [
            {
                "uri": "ui://blenderremotemcp/desktop",
                "name": "Blender Desktop",
                "description": "Interactive Blender Desktop — live viewport with link to the full desktop.",
                "mimeType": "text/html;profile=mcp-app",
            },
            {"uri": "blender://scene", "name": "Scene", "description": "Current scene state"},
            {"uri": "blender://projects", "name": "Projects", "description": "Saved projects"},
        ]
        resources.extend(guidance_mod.catalog.skill_resources())
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"resources": resources},
        }

    # Read resource
    if method == "resources/read":
        uri = params.get("uri", "")
        try:
            skill = guidance_mod.catalog.read_skill(uri)
            if skill:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "contents": [{
                            "uri": uri,
                            "mimeType": "text/markdown",
                            "text": skill["text"],
                        }]
                    },
                }
            if uri == "ui://blenderremotemcp/desktop":
                canvas = _canvas_url(base, api_key)
                if templates:
                    html = templates.get_template("mcp_app_desktop.html").render(
                        canvas_url=canvas,
                    )
                else:
                    html = (
                        f"<!DOCTYPE html><html><body>"
                        f"<p>Ouvrir le bureau Blender : "
                        f"<a href=\"{canvas}\">{canvas}</a></p></body></html>"
                    )
                # CSP : le host public pour open-link / eventuels assets.
                host_origin = base
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "contents": [{
                            "uri": uri,
                            "mimeType": "text/html;profile=mcp-app",
                            "text": html,
                            "_meta": {
                                "ui": {
                                    "csp": {
                                        "connectDomains": ["self", host_origin],
                                        "resourceDomains": ["self", host_origin],
                                        "frameDomains": [host_origin],
                                    }
                                }
                            },
                        }]
                    },
                }
            if uri == "blender://scene":
                objects = await _call_blender(user_id, "/api/objects")
                content = {"objects": objects, "count": len(objects)}
            elif uri == "blender://projects":
                content = {"projects": []}
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"Unknown resource: {uri}"}
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "contents": [{"uri": uri, "text": str(content)}]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e)}
            }

    if method == "prompts/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"prompts": guidance_mod.catalog.list_prompts()},
        }

    if method == "prompts/get":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        prompt = guidance_mod.catalog.get_prompt(name, arguments)
        if not prompt:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Unknown prompt: {name}"},
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": prompt,
        }

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


async def _executer_recipe(
    recipe_id: str,
    params: dict,
    *,
    user_id: str,
    session_id: str,
    portee,
    base_url: str,
    api_key: str,
) -> str:
    """Enchaine les steps d'une recipe via tools/call internes."""
    recipe = guidance_mod.catalog.get_recipe(recipe_id)
    if not recipe:
        return f"Error: recipe inconnue: {recipe_id}"

    resolved = {}
    for key, spec in (recipe.get("parameters") or {}).items():
        if key in params:
            resolved[key] = params[key]
        elif isinstance(spec, dict) and "default" in spec:
            resolved[key] = spec["default"]

    journal = []
    for step in recipe.get("steps") or []:
        tool = step.get("tool")
        if not tool:
            continue
        if tool == "run_recipe":
            return "Error: recipes imbriquées non supportées — aplatis les steps"
        step_args = substitute_params(step.get("params") or {}, resolved)
        if tool == "execute_python" and step.get("code"):
            step_args = {"code": substitute_params(step["code"], resolved)}
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": step_args},
        }
        resp = await handle_mcp_request(
            body, user_id, session_id, portee, base_url, api_key
        )
        err = False
        text = ""
        if "error" in resp:
            err = True
            text = resp["error"].get("message", str(resp["error"]))
        else:
            result = resp.get("result") or {}
            err = bool(result.get("isError"))
            parts = []
            for block in result.get("content") or []:
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "image":
                    parts.append("[image]")
            text = "\n".join(parts)[:500]
        journal.append({
            "step": step.get("id"),
            "tool": tool,
            "ok": not err,
            "detail": text[:240],
        })
        if err:
            return json.dumps(
                {"recipe": recipe_id, "failed_step": step.get("id"), "log": journal},
                ensure_ascii=False,
                indent=2,
            )

    return json.dumps(
        {"recipe": recipe_id, "status": "ok", "log": journal},
        ensure_ascii=False,
        indent=2,
    )


# =============================================================================
# MCP ENDPOINT
# =============================================================================

def _erreur_auth(message: str, request: Request = None) -> JSONResponse:
    headers = None
    if request is not None:
        base = _public_base_url(request)
        headers = {"WWW-Authenticate": oauth_mcp.www_authenticate_header(base)}
    return JSONResponse(
        status_code=401,
        content={"jsonrpc": "2.0", "error": {"code": -32000, "message": message}, "id": None},
        headers=headers,
    )


async def _resoudre_cle(jeton: str):
    """Resout un jeton, maitre ou scope. Retourne (User, portee).

    La portee vaut None pour une cle maitresse — pouvoir complet — et le
    dictionnaire de la cle scopee sinon. Un seul point de resolution, pour
    qu'aucune route ne puisse oublier de tenir compte de la portee.
    """
    if not jeton:
        return None, None
    if jeton.startswith(SCOPED_PREFIX):
        resultat = await auth_manager.verify_scoped_key(jeton)
        return resultat if resultat else (None, None)
    return await auth_manager.verify_api_key(jeton), None


def _outil_autorise(nom: str, portee) -> bool:
    """Une cle maitresse peut tout ; une cle scopee, sa liste blanche."""
    if portee is None:
        return True
    outils = portee.get("tools", TOUS_LES_OUTILS)
    if outils == TOUS_LES_OUTILS:
        return True
    return nom in (outils or [])


async def _utilisateur_de_la_requete(request: Request):
    """Resout l'utilisateur porteur, ou None. Ignore la portee : les routes
    web n'exposent pas d'outils."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    user, _ = await _resoudre_cle(auth_header[7:].strip())
    return user


@app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"])
@app.api_route("/mcp/", methods=["GET", "POST", "DELETE", "OPTIONS"])
async def mcp_handler(request: Request):
    """Point d'entree MCP, transport Streamable HTTP.

    POST porte les messages JSON-RPC. La reponse part en SSE si le client
    l'accepte, en JSON simple sinon : les proxys du type mcp-remote n'annoncent
    pas text/event-stream et ne savent pas lire un flux.

    GET sert deux usages : sans Accept SSE il renvoie les metadonnees du
    serveur, avec Accept SSE il ouvre le transport historique 2024-11-05 en
    annoncant ou poster.

    DELETE ferme la session.
    """
    if request.method == "OPTIONS":
        return Response(status_code=204)

    accepte_sse = _accepts_sse(request.headers.get("accept", ""))

    # ── GET sans SSE : metadonnees publiques ─────────────────────────────
    if request.method == "GET" and not accepte_sse:
        return {
            "name": "BlenderRemoteMCP",
            "version": "2.0.0",
            "description": "Blender en service, accessible par MCP",
            "protocolVersion": PROTOCOL_VERSION,
            "supportedProtocolVersions": list(SUPPORTED_PROTOCOL_VERSIONS),
            "transport": "streamable-http",
            "authentication": "Bearer API key ou OAuth MCP (découverte /.well-known/)",
            "sessionsActives": len(_sessions),
        }

    entete_auth = request.headers.get("Authorization", "")
    jeton = entete_auth[7:].strip() if entete_auth.startswith("Bearer ") else ""
    user, portee = await _resoudre_cle(jeton)
    if user is None:
        return _erreur_auth(
            "Authentification requise : Bearer blender_… ou flux OAuth MCP.",
            request,
        )

    # ── GET avec SSE : transport historique ──────────────────────────────
    if request.method == "GET":
        session_id = request.headers.get("mcp-session-id") or uuid.uuid4().hex
        _touch_session(session_id, user.id)

        async def flux_historique():
            # Annonce ou poster les requetes, puis maintient le lien ouvert.
            yield "event: endpoint\ndata: /mcp\n\n"
            while True:
                await asyncio.sleep(30)
                yield ": keepalive\n\n"

        return StreamingResponse(
            flux_historique(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "mcp-session-id": session_id,
            },
        )

    # ── DELETE : fermeture de session ────────────────────────────────────
    if request.method == "DELETE":
        session_id = request.headers.get("mcp-session-id", "")
        session = _sessions.get(session_id)
        if session and session["user_id"] == user.id:
            _sessions.pop(session_id, None)
            logger.info(f"Session MCP fermee : {session_id[:8]}")
        # Fermer une session ne touche pas au container : d'autres sessions
        # du meme utilisateur peuvent encore travailler sur l'instance.
        return Response(status_code=204)

    # ── POST : messages JSON-RPC ─────────────────────────────────────────
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
        )

    if isinstance(body, list):
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "Les lots de requetes ne sont pas supportes"},
            },
        )

    entete_session = request.headers.get("mcp-session-id", "")
    session_id = entete_session or uuid.uuid4().hex
    method = body.get("method", "")
    req_id = body.get("id")

    # Validation indulgente : on ne refuse que si le client a explicitement
    # presente une session que l'on ne connait pas. Un client sans session
    # reste accepte, sinon les proxys sans gestion de session sont exclus.
    if (_sessions and entete_session and entete_session not in _sessions
            and method in _STATEFUL_METHODS and req_id is not None):
        return JSONResponse(
            status_code=400,
            headers={"mcp-session-id": entete_session},
            content={
                "jsonrpc": "2.0", "id": req_id,
                "error": {
                    "code": -32600,
                    "message": "Session inconnue ou expiree. Envoyer 'initialize' d'abord.",
                },
            },
        )

    _touch_session(session_id, user.id)

    # Notifications : pas d'identifiant, donc pas de reponse. 202 et non 204,
    # pour que le client sache que le message a bien ete accepte.
    if req_id is None:
        if method == "notifications/initialized":
            asyncio.create_task(_ensure_session(user.id))
            logger.info(f"Pre-demarrage de Blender pour {user.id[:8]}")
        return Response(status_code=202, headers={"mcp-session-id": session_id})

    reponse = await handle_mcp_request(
        body, user.id, session_id, portee,
        base_url=_public_base_url(request),
        api_key=jeton,
    )
    if reponse is None:
        return Response(status_code=202, headers={"mcp-session-id": session_id})

    if accepte_sse:
        return _sse_response(reponse, session_id)
    return JSONResponse(content=reponse, headers={"mcp-session-id": session_id})


# =============================================================================
# AUTH ENDPOINTS
# =============================================================================

@app.post("/api/auth/register", response_model=TokenResponse)
async def register(data: UserCreate):
    """Register a new user and get API key"""
    try:
        return await auth_manager.register(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# CLES SCOPEES
# =============================================================================
#
# Une cle maitresse identifie une personne, une cle scopee identifie un agent.
# Seule la maitresse peut en emettre : autrement une cle restreinte se
# delivrerait elle-meme une cle complete, et la restriction ne vaudrait rien.


async def _porteur_maitre(request: Request):
    """Exige une cle MAITRESSE. Retourne l'utilisateur, ou leve 401/403."""
    entete = request.headers.get("Authorization", "")
    jeton = entete[7:].strip() if entete.startswith("Bearer ") else ""
    user, portee = await _resoudre_cle(jeton)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentification requise")
    if portee is not None:
        raise HTTPException(
            status_code=403,
            detail="Une cle scopee ne peut pas gerer les cles. Utiliser la cle maitresse.",
        )
    return user


@app.post("/api/keys")
async def creer_cle_scopee(request: Request):
    """Emet une cle scopee.

    Corps : {"label": "...", "tools": ["nom", ...] | "all", "ttl_seconds": 3600}

    La cle en clair n'est renvoyee QU'ICI : elle n'est plus jamais reaffichee
    par la suite, seulement identifiee par ses douze derniers caracteres.
    """
    user = await _porteur_maitre(request)
    try:
        corps = await request.json()
    except Exception:
        corps = {}

    outils = corps.get("tools", TOUS_LES_OUTILS)
    if isinstance(outils, list):
        inconnus = [o for o in outils if o not in MCP_TOOLS]
        if inconnus:
            raise HTTPException(
                status_code=400,
                detail=f"Outils inconnus : {', '.join(inconnus)}",
            )

    resultat = await auth_manager.create_scoped_key(
        user.id,
        label=corps.get("label", ""),
        tools=outils,
        ttl_seconds=corps.get("ttl_seconds"),
    )
    return resultat


@app.get("/api/keys")
async def lister_cles_scopees(request: Request):
    """Liste les cles scopees. Les cles en clair ne sont jamais renvoyees."""
    user = await _porteur_maitre(request)
    return {"keys": await auth_manager.list_scoped_keys(user.id)}


@app.delete("/api/keys/{key_id}")
async def revoquer_cle_scopee(key_id: str, request: Request):
    """Revoque une cle par ses douze derniers caracteres."""
    user = await _porteur_maitre(request)
    if not await auth_manager.revoke_scoped_key(user.id, key_id):
        raise HTTPException(status_code=404, detail="Cle introuvable ou deja revoquee")
    return Response(status_code=204)


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(data: UserLogin):
    """Login and get API key"""
    try:
        return await auth_manager.login(data)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


# =============================================================================
# STREAM ENDPOINT
# =============================================================================

async def _utilisateur_du_websocket(websocket: WebSocket):
    """Resout l'utilisateur d'une connexion WebSocket.

    Un navigateur ne peut pas poser d'en-tete Authorization sur un
    WebSocket : le jeton arrive donc par le cookie pose par /canvas, ou a
    defaut en parametre de requete.
    """
    jeton = (websocket.cookies.get("blender_token")
             or websocket.query_params.get("token"))
    if not jeton:
        entete = websocket.headers.get("authorization", "")
        if entete.startswith("Bearer "):
            jeton = entete[7:].strip()
    if not jeton:
        return None
    return await auth_manager.verify_api_key(jeton)


@app.get("/stream/{user_id}")
async def stream(user_id: str, request: Request):
    """Flux MJPEG de l'instance Blender de cet utilisateur.

    L'identifiant dans le chemin ne vaut PAS authentification : en mode
    mono il est meme ignore par la resolution, donc n'importe quelle
    chaine y ouvrait le flux. Le porteur doit prouver son identite, et
    etre celui qu'il demande.
    """
    user = await _get_user_from_request(request)
    if user is None or user.id != user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    try:
        hote, _, port_flux, _ = _points_d_acces(user_id)
    except Exception:
        raise HTTPException(status_code=404, detail="No active session")

    async def generate():
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "GET",
                    f"http://{hote}:{port_flux}/stream",
                    timeout=None
                ) as response:
                    async for chunk in response.aiter_bytes():
                        yield chunk
            except Exception as e:
                logger.error(f"Stream error: {e}")

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# =============================================================================
# WEBSOCKET VNC PROXY
# =============================================================================

@app.websocket("/ws/{user_id}")
async def vnc_websocket_proxy(websocket: WebSocket, user_id: str):
    """
    WebSocket proxy to user's VNC server (via websockify).
    Enables direct browser connection to Blender viewport.
    """
    # Authentifier AVANT d'accepter : ce canal donne le clavier et la
    # souris de Blender, donc l'execution de code dans le container. Sans
    # ce controle, /ws/<n-importe-quoi> ouvrait le bureau a tout venant.
    user = await _utilisateur_du_websocket(websocket)
    if user is None or user.id != user_id:
        await websocket.close(code=4401)   # 4401 : non authentifie
        return

    # L'instance doit etre joignable avant d'accepter la connexion
    try:
        hote, _, _, port_novnc = _points_d_acces(user_id)
    except Exception:
        await websocket.close(code=4004)
        return

    await websocket.accept()

    # Connect to container's websockify (noVNC WebSocket bridge)
    # websockify runs on port 6080 inside container, mapped to novnc_port
    # Use host_address (host.docker.internal) when running in Docker
    vnc_ws_url = f"ws://{hote}:{port_novnc}/websockify"

    try:
        async with websockets.connect(
            vnc_ws_url,
            subprotocols=["binary"],
            max_size=None,
            ping_interval=None
        ) as vnc_ws:

            async def client_to_vnc():
                """Forward messages from browser to VNC"""
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await vnc_ws.send(data)
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    logger.debug(f"Client->VNC ended: {e}")

            async def vnc_to_client():
                """Forward messages from VNC to browser"""
                try:
                    async for data in vnc_ws:
                        if isinstance(data, bytes):
                            await websocket.send_bytes(data)
                        else:
                            await websocket.send_text(data)
                except Exception as e:
                    logger.debug(f"VNC->Client ended: {e}")

            # Run both directions concurrently
            await asyncio.gather(
                client_to_vnc(),
                vnc_to_client(),
                return_exceptions=True
            )

    except websockets.exceptions.InvalidStatusCode as e:
        logger.error(f"VNC WebSocket connection failed: {e}")
    except Exception as e:
        logger.error(f"VNC proxy error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# =============================================================================
# BLENDER CANVAS (Pure VNC Interface)
# =============================================================================

async def _get_user_from_token(token: str):
    """Verify token and return user"""
    if not token:
        return None
    # Handle both cookie and query param formats
    if token.startswith("blender_"):
        return await auth_manager.verify_api_key(token)
    return None


async def _get_user_from_request(request: Request):
    """Extract and verify user from request (Authorization header or cookie)"""
    # Try Authorization header first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return await _get_user_from_token(token)

    # Try cookie
    token = request.cookies.get("blender_token")
    if token:
        return await _get_user_from_token(token)

    # Try query param
    token = request.query_params.get("token")
    if token:
        return await _get_user_from_token(token)

    return None


@app.get("/desktop", response_class=HTMLResponse)
@app.get("/canvas", response_class=HTMLResponse)
async def desktop_page(request: Request, token: str = None, embed: str = None):
    """Bureau Blender immersif (plein viewport). /canvas est un alias de /desktop.

    ``embed=1`` est réservé à un futur hub (même page, contrat d'iframe).
    Auth via ``?token=`` ou cookie ``blender_token``.
    """
    auth_token = token or request.cookies.get("blender_token")
    embed_mode = str(embed or "").strip().lower() in ("1", "true", "yes")

    if not auth_token:
        return HTMLResponse("""
        <html lang="fr">
        <head><title>Bureau Blender — authentification</title></head>
        <body style="background:#0d0d0d;color:#c8c8c8;font-family:system-ui,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;">
            <div style="text-align:center;">
                <p>Authentification requise</p>
                <p style="color:#888;font-size:14px;margin-top:12px;">
                  Ouvre <code style="color:#e8e8e8;">/desktop?token=…</code>
                  ou <a href="/" style="color:#ff6b35;">l’accueil</a> pour t’enregistrer.
                </p>
            </div>
        </body>
        </html>
        """, status_code=401)

    user = await _get_user_from_token(auth_token)
    if not user:
        return HTMLResponse("""
        <html lang="fr">
        <head><title>Bureau Blender — jeton invalide</title></head>
        <body style="background:#0d0d0d;color:#c8c8c8;font-family:system-ui,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;">
            <div style="text-align:center;">
                <p>Jeton invalide ou expiré</p>
                <p style="margin-top:12px;"><a href="/" style="color:#ff6b35;">Retour à l’accueil</a></p>
            </div>
        </body>
        </html>
        """, status_code=401)

    try:
        session = await _ensure_session(user.id)
    except Exception as e:
        return HTMLResponse(f"""
        <html lang="fr">
        <head><title>Bureau Blender — erreur</title></head>
        <body style="background:#0d0d0d;color:#c8c8c8;font-family:system-ui,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;">
            <div style="text-align:center;">
                <p>Impossible de démarrer la session</p>
                <p style="color:#888;font-size:14px;margin-top:12px;">{e}</p>
                <p style="margin-top:12px;"><a href="/" style="color:#ff6b35;">Réessayer</a></p>
            </div>
        </body>
        </html>
        """, status_code=500)

    # Signature moderne de Starlette : la requete passe en premier argument.
    # L'ancienne forme TemplateResponse(nom, contexte) a ete retiree dans
    # Starlette 1.x, ou elle echoue sur « unhashable type: dict » — le
    # dictionnaire de contexte etant pris pour une cle de cache.
    reponse = templates.TemplateResponse(request, "blender_canvas.html", {
        "user_id": user.id,
        "session": session.to_dict() if hasattr(session, 'to_dict') else {},
        "token": auth_token,
        "embed": embed_mode,
    })
    # Le WebSocket du bureau s'authentifie par ce cookie : un navigateur ne
    # peut pas poser d'en-tete Authorization sur une connexion WebSocket.
    # httponly : le jeton reste hors de portee du JavaScript de la page.
    reponse.set_cookie(
        "blender_token", auth_token,
        httponly=True, samesite="strict",
        secure=request.url.scheme == "https",
        max_age=7 * 24 * 3600,
    )
    return reponse


@app.get("/api/session/info")
async def session_info(request: Request, token: str = None):
    """Get current session info (ports, URLs)"""
    auth_token = token or request.headers.get("Authorization", "").replace("Bearer ", "")

    user = await _get_user_from_token(auth_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not MULTI_USER_MODE:
        hote, port_api, port_flux, port_novnc = _points_d_acces(user.id)
        return {
            "mode": "mono",
            "user_id": user.id,
            "api_url": f"http://{hote}:{port_api}",
            "stream_url": f"http://{hote}:{port_flux}/stream",
            "novnc_url": f"http://{hote}:{port_novnc}/vnc.html",
            "desktop_url": "/desktop",
            "status": "ready",
        }

    session = container_manager.get_session(user.id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    return session.to_dict()


# =============================================================================
# FILE MANAGEMENT API
# =============================================================================

@app.get("/api/files/list")
async def list_user_files(request: Request):
    """List files in user's project folder"""
    user = await _get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = container_manager.get_session(user.id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    # Execute Python in Blender to list files
    result = await _call_blender(user.id, "/api/execute", "POST", {
        "code": """
import os
files = []
projects_dir = '/projects'
if os.path.exists(projects_dir):
    for f in os.listdir(projects_dir):
        path = os.path.join(projects_dir, f)
        if os.path.isfile(path):
            files.append({
                'name': f,
                'size': os.path.getsize(path),
                'is_blend': f.endswith('.blend'),
                'is_image': f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.hdr'))
            })
result = sorted(files, key=lambda x: x['name'])
"""
    })

    return result.get("result", [])


@app.post("/api/files/upload")
async def upload_user_file(request: Request):
    """Upload a file to user's project folder"""
    from fastapi import UploadFile, File, Form
    import base64

    user = await _get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = container_manager.get_session(user.id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    # Parse multipart form data
    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")

    filename = file.filename
    content = await file.read()

    # Validate filename (security)
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Encode content as base64 and send to Blender
    content_b64 = base64.b64encode(content).decode('utf-8')

    result = await _call_blender(user.id, "/api/execute", "POST", {
        "code": f"""
import os
import base64

filename = {repr(filename)}
content_b64 = {repr(content_b64)}
content = base64.b64decode(content_b64)

filepath = os.path.join('/projects', filename)
with open(filepath, 'wb') as f:
    f.write(content)

result = {{'success': True, 'filename': filename, 'size': len(content)}}
"""
    })

    return result.get("result", {"success": False})


@app.get("/api/files/download/{filename}")
async def download_user_file(request: Request, filename: str):
    """Download a file from user's project folder"""
    import base64

    user = await _get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = container_manager.get_session(user.id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    # Validate filename (security)
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Get file content from Blender
    result = await _call_blender(user.id, "/api/execute", "POST", {
        "code": f"""
import os
import base64

filename = {repr(filename)}
filepath = os.path.join('/projects', filename)

if os.path.exists(filepath):
    with open(filepath, 'rb') as f:
        content = f.read()
    result = {{'success': True, 'content': base64.b64encode(content).decode('utf-8'), 'filename': filename}}
else:
    result = {{'success': False, 'error': 'File not found'}}
"""
    })

    file_result = result.get("result", {})
    if not file_result.get("success"):
        raise HTTPException(status_code=404, detail=file_result.get("error", "File not found"))

    content = base64.b64decode(file_result["content"])

    # Determine content type
    content_type = "application/octet-stream"
    if filename.endswith(".blend"):
        content_type = "application/x-blender"
    elif filename.endswith(".png"):
        content_type = "image/png"
    elif filename.endswith((".jpg", ".jpeg")):
        content_type = "image/jpeg"

    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.delete("/api/files/{filename}")
async def delete_user_file(request: Request, filename: str):
    """Delete a file from user's project folder"""
    user = await _get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = container_manager.get_session(user.id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    # Validate filename (security)
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    result = await _call_blender(user.id, "/api/execute", "POST", {
        "code": f"""
import os

filename = {repr(filename)}
filepath = os.path.join('/projects', filename)

if os.path.exists(filepath):
    os.remove(filepath)
    result = {{'success': True, 'deleted': filename}}
else:
    result = {{'success': False, 'error': 'File not found'}}
"""
    })

    file_result = result.get("result", {})
    if not file_result.get("success"):
        raise HTTPException(status_code=404, detail=file_result.get("error", "File not found"))

    return file_result


# =============================================================================
# WEB UI
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Vitrine du service : identité, lien bureau, snippet MCP."""
    base = _public_base_url(request)
    if templates:
        return templates.TemplateResponse(
            request,
            "landing.html",
            {"public_base": base},
        )
    return HTMLResponse(
        f"<html><body><h1>BlenderRemoteMCP</h1>"
        f"<p>MCP: <code>{base}/mcp</code></p>"
        f"<p>Bureau: <a href=\"{base}/desktop\">{base}/desktop</a></p>"
        f"</body></html>"
    )


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "blender-mcp",
        "multi_user": MULTI_USER_MODE,
        "protocolVersion": PROTOCOL_VERSION,
        "sessions": len(_sessions),
    }


@app.get("/health/ready")
async def health_ready():
    """Sonde de disponibilite : verifie la chaine jusqu'a Blender.

    /health atteste que CE serveur repond ; celle-ci que Blender repond. Les
    deux ne se valent pas, et les confondre a un cout concret : en pod,
    Kubernetes marque le service disponible des que uvicorn ecoute et lui
    envoie du trafic pendant que Blender demarre encore.

    Separation deliberee des roles : /health sert la sonde de vie — redemarrer
    le pod parce que Blender est tombe serait excessif, supervisord le releve
    — et /health/ready sert la disponibilite, qui elle doit retenir le trafic.
    """
    detail = {
        "service": "blender-mcp",
        "multi_user": MULTI_USER_MODE,
        "sessions": len(_sessions),
    }

    if not MULTI_USER_MODE:
        try:
            async with httpx.AsyncClient() as client:
                reponse = await client.get(
                    f"http://{MONO_HOST}:{MONO_API_PORT}/health", timeout=5.0
                )
            amont = reponse.json()
            pret = reponse.status_code == 200 and amont.get("blender") == "running"
            detail["blender"] = amont.get("blender", "inconnu")
        except Exception as e:
            pret = False
            detail["blender"] = f"injoignable: {type(e).__name__}"
    else:
        # En mode passerelle il n'y a pas d'instance unique : ce qui doit
        # repondre, c'est le pilotage des containers.
        pret = container_manager.docker_client is not None
        detail["docker"] = "connecte" if pret else "indisponible"
        detail["containers"] = len(container_manager.sessions)

    detail["status"] = "ready" if pret else "not-ready"
    return JSONResponse(content=detail, status_code=200 if pret else 503)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main_mcp:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info"
    )
