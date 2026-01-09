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
import logging
import os
import asyncio
import websockets

from src.container_manager import ContainerManager
from src.auth import AuthManager, UserCreate, UserLogin, TokenResponse

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    logger.info("Starting Blender MCP Server...")
    await container_manager.initialize()
    logger.info("=" * 50)
    logger.info("Server ready at http://localhost:8000")
    logger.info("MCP endpoint: http://localhost:8000/mcp")
    logger.info("=" * 50)

    yield

    logger.info("Shutting down...")
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

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

async def _ensure_session(user_id: str):
    """Ensure user has an active Blender container"""
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
    """Call Blender API on user's container"""
    session = await _ensure_session(user_id)
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
        code = "import bpy; bpy.ops.ed.undo(); result = 'Undo performed'"
        result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
        return result.get("result", "Undo performed")
    except Exception as e:
        return f"Error: {e}"


async def mcp_redo(user_id: str) -> str:
    """Redo the last undone action in Blender."""
    try:
        code = "import bpy; bpy.ops.ed.redo(); result = 'Redo performed'"
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
        code = f"""
import bpy
col = bpy.data.collections.get('{name}')
if col:
    if {str(delete_objects).lower()}:
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
        code = """
import bpy
materials = []
for mat in bpy.data.materials:
    users = len(mat.users) if hasattr(mat, 'users') else 0
    materials.append({'name': mat.name, 'users': users})
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
        code = """
import bpy
meshes = []
for mesh in bpy.data.meshes:
    users = len(mesh.users) if hasattr(mesh, 'users') else 0
    verts = len(mesh.vertices)
    faces = len(mesh.polygons)
    meshes.append({'name': mesh.name, 'users': users, 'verts': verts, 'faces': faces})
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
        "description": "Take a screenshot of the Blender viewport.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {"type": "integer", "description": "Screenshot width (default 1920)"},
                "height": {"type": "integer", "description": "Screenshot height (default 1080)"}
            },
            "required": []
        }
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
    }
}


async def handle_mcp_request(request: Request, user_id: str) -> dict:
    """Handle MCP JSON-RPC request"""
    try:
        body = await request.json()
    except Exception:
        return {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None}

    method = body.get("method", "")
    params = body.get("params", {})
    req_id = body.get("id")

    # Initialize
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {}
                },
                "serverInfo": {
                    "name": "Blender",
                    "version": "1.0.0"
                }
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
        tools = [
            {"name": name, "description": info["description"], "inputSchema": info["inputSchema"]}
            for name, info in MCP_TOOLS.items()
        ]
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
            else:
                result = f"Tool {tool_name} not implemented"

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result}],
                    "isError": result.startswith("Error:")
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
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "resources": [
                    {"uri": "blender://scene", "name": "Scene", "description": "Current scene state"},
                    {"uri": "blender://projects", "name": "Projects", "description": "Saved projects"}
                ]
            }
        }

    # Read resource
    if method == "resources/read":
        uri = params.get("uri", "")
        try:
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

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


# =============================================================================
# MCP ENDPOINT
# =============================================================================

@app.api_route("/mcp", methods=["GET", "POST", "OPTIONS"])
@app.api_route("/mcp/", methods=["GET", "POST", "OPTIONS"])
async def mcp_handler(request: Request):
    """
    Main MCP endpoint. Handles JSON-RPC requests.
    Requires Authorization: Bearer <api_key> header.
    """
    # Handle OPTIONS for CORS
    if request.method == "OPTIONS":
        return Response(status_code=204)

    # GET returns server info
    if request.method == "GET":
        return {
            "name": "Blender",
            "version": "1.0.0",
            "description": "Cloud Blender access via MCP",
            "protocol": "MCP 2024-11-05",
            "authentication": "Bearer token in Authorization header"
        }

    # POST handles MCP requests
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={
                "jsonrpc": "2.0",
                "error": {
                    "code": -32000,
                    "message": "Authorization required. Use 'Authorization: Bearer YOUR_API_KEY' header."
                },
                "id": None
            }
        )

    api_key = auth_header[7:]  # Remove "Bearer "
    user = await auth_manager.verify_api_key(api_key)

    if not user:
        return JSONResponse(
            status_code=401,
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": "Invalid API key"},
                "id": None
            }
        )

    # Handle MCP request
    response = await handle_mcp_request(request, user.id)

    if response is None:
        return Response(status_code=204)

    return JSONResponse(content=response)


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

@app.get("/stream/{user_id}")
async def stream(user_id: str):
    """MJPEG stream from user's Blender container"""
    session = container_manager.get_session(user_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    async def generate():
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "GET",
                    f"http://localhost:{session.stream_port}/stream",
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
    # Verify user has active session
    session = container_manager.get_session(user_id)
    if not session:
        await websocket.close(code=4004)
        return

    await websocket.accept()

    # Connect to container's websockify (noVNC WebSocket bridge)
    # websockify runs on port 6080 inside container, mapped to novnc_port
    # Use host_address (host.docker.internal) when running in Docker
    vnc_ws_url = f"ws://{container_manager.host_address}:{session.novnc_port}/websockify"

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


@app.get("/canvas", response_class=HTMLResponse)
async def canvas_page(request: Request, token: str = None):
    """
    Pure Blender canvas page - full viewport, no chrome.
    Auth via ?token= query param or blender_token cookie.
    """
    # Check token from query or cookie
    auth_token = token or request.cookies.get("blender_token")

    if not auth_token:
        # Redirect to login or show error
        return HTMLResponse("""
        <html>
        <head><title>Blender Canvas - Auth Required</title></head>
        <body style="background:#1a1a1a;color:#fff;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;">
            <div style="text-align:center;">
                <h1>Authentication Required</h1>
                <p>Add your API key: <code>/canvas?token=blender_xxx</code></p>
                <p>Or <a href="/" style="color:#4af;">go to home</a> to register.</p>
            </div>
        </body>
        </html>
        """, status_code=401)

    user = await _get_user_from_token(auth_token)
    if not user:
        return HTMLResponse("""
        <html>
        <head><title>Blender Canvas - Invalid Token</title></head>
        <body style="background:#1a1a1a;color:#fff;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;">
            <div style="text-align:center;">
                <h1>Invalid Token</h1>
                <p>Your API key is invalid or expired.</p>
                <p><a href="/" style="color:#4af;">Go to home</a> to get a new one.</p>
            </div>
        </body>
        </html>
        """, status_code=401)

    # Ensure user has a session
    try:
        session = await _ensure_session(user.id)
    except Exception as e:
        return HTMLResponse(f"""
        <html>
        <head><title>Blender Canvas - Error</title></head>
        <body style="background:#1a1a1a;color:#fff;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;">
            <div style="text-align:center;">
                <h1>Session Error</h1>
                <p>Failed to start Blender: {e}</p>
                <p><a href="/" style="color:#4af;">Try again</a></p>
            </div>
        </body>
        </html>
        """, status_code=500)

    # Return pure canvas page
    return templates.TemplateResponse("blender_canvas.html", {
        "request": request,
        "user_id": user.id,
        "session": session.to_dict() if hasattr(session, 'to_dict') else {},
        "token": auth_token
    })


@app.get("/api/session/info")
async def session_info(request: Request, token: str = None):
    """Get current session info (ports, URLs)"""
    auth_token = token or request.headers.get("Authorization", "").replace("Bearer ", "")

    user = await _get_user_from_token(auth_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")

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
    """Web UI for registration and stream viewing"""
    if templates:
        return templates.TemplateResponse("canvas.html", {"request": request})
    return HTMLResponse("""
    <html>
    <head><title>Blender MCP Server</title></head>
    <body>
        <h1>Blender MCP Server</h1>
        <p>MCP endpoint: <code>/mcp</code></p>
        <p>Register: <code>POST /api/auth/register</code></p>
        <p>Login: <code>POST /api/auth/login</code></p>
    </body>
    </html>
    """)


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "blender-mcp"}


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
