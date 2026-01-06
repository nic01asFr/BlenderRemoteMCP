#!/usr/bin/env python3
"""
Blender MCP Server
==================
Standard MCP server for cloud Blender access.

User configuration (claude_desktop_config.json):
{
  "mcpServers": {
    "blender": {
      "url": "https://blender.example.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}

- Standard MCP HTTP transport
- API key in Authorization header
- Blender instance auto-starts on first use
- Auto-save every 5 minutes
"""

from fastmcp import FastMCP
from typing import Optional, List, Dict
import asyncio
import logging

logger = logging.getLogger(__name__)

# Container manager reference (injected at startup)
_container_manager = None
_autosave_tasks: Dict[str, asyncio.Task] = {}


def create_mcp_app(user_id: str, container_manager, stream_url: str = None):
    """
    Create an MCP server instance for a specific user.

    Args:
        user_id: The authenticated user's ID
        container_manager: Docker container manager
        stream_url: Optional URL where user can view the stream

    Returns:
        FastMCP app ready to be mounted
    """
    global _container_manager
    _container_manager = container_manager

    # Create MCP server
    mcp = FastMCP(
        name="Blender",
        version="1.0.0",
        description="Create and manipulate 3D scenes in Blender."
    )

    # =========================================================================
    # TOOLS
    # =========================================================================

    @mcp.tool()
    async def list_objects() -> str:
        """
        List all objects in the current Blender scene.
        Returns name, type, and position of each object.
        """
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

    @mcp.tool()
    async def create_object(
        type: str,
        name: str = None,
        location: List[float] = None,
        color: List[float] = None
    ) -> str:
        """
        Create a 3D object in the scene.

        Args:
            type: Object type - CUBE, SPHERE, CYLINDER, CONE, TORUS, PLANE, MONKEY
            name: Optional name for the object
            location: Position [x, y, z], default [0, 0, 0]
            color: RGBA color [r, g, b, a] with values 0-1, e.g. [1, 0, 0, 1] for red
        """
        try:
            result = await _call_blender(user_id, "/api/object", "POST", {
                "type": type.upper(),
                "name": name,
                "location": location or [0, 0, 0]
            })
            obj_name = result.get("name", name or type)

            if color:
                await _call_blender(user_id, f"/api/object/{obj_name}/material", "POST", {
                    "color": color if len(color) == 4 else list(color) + [1.0]
                })

            loc = location or [0, 0, 0]
            msg = f"Created {obj_name} at ({loc[0]}, {loc[1]}, {loc[2]})"
            if color:
                msg += f" with color ({color[0]:.1f}, {color[1]:.1f}, {color[2]:.1f})"
            return msg
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    async def modify_object(
        name: str,
        location: List[float] = None,
        rotation: List[float] = None,
        scale: List[float] = None
    ) -> str:
        """
        Modify an object's transform.

        Args:
            name: Object name
            location: New position [x, y, z]
            rotation: New rotation in degrees [x, y, z]
            scale: New scale [x, y, z]
        """
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

    @mcp.tool()
    async def set_color(name: str, color: List[float]) -> str:
        """
        Set an object's color.

        Args:
            name: Object name
            color: RGBA [r, g, b, a] with values 0-1
        """
        try:
            rgba = color if len(color) == 4 else list(color) + [1.0]
            await _call_blender(user_id, f"/api/object/{name}/material", "POST", {"color": rgba})
            return f"Set {name} color to ({rgba[0]:.1f}, {rgba[1]:.1f}, {rgba[2]:.1f})"
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    async def delete_object(name: str) -> str:
        """Delete an object from the scene."""
        try:
            await _call_blender(user_id, f"/api/object/{name}", "DELETE")
            return f"Deleted {name}"
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    async def clear_scene() -> str:
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

    @mcp.tool()
    async def execute_python(code: str) -> str:
        """
        Execute Python code in Blender.

        Args:
            code: Python code with access to 'bpy'. Set 'result' to return a value.
        """
        try:
            result = await _call_blender(user_id, "/api/execute", "POST", {"code": code})
            if result.get("success"):
                return f"Executed. Result: {result.get('result', 'None')}"
            return f"Error: {result.get('error')}"
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    async def save_project(name: str) -> str:
        """Save current scene as a project."""
        try:
            await _call_blender(user_id, "/api/save", "POST", {
                "filepath": f"/projects/{name}.blend"
            })
            return f"Saved as {name}"
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    async def load_project(name: str) -> str:
        """Load a saved project."""
        try:
            await _call_blender(user_id, "/api/load", "POST", {
                "filepath": f"/projects/{name}.blend"
            })
            objects = await _call_blender(user_id, "/api/objects")
            return f"Loaded {name} ({len(objects)} objects)"
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    async def get_scene_info() -> str:
        """Get information about the current scene."""
        try:
            scene = await _call_blender(user_id, "/api/scene")
            objects = await _call_blender(user_id, "/api/objects")

            info = [
                f"Scene: {scene.get('name', 'Scene')}",
                f"Objects: {len(objects)}",
                f"Resolution: {scene.get('render_resolution_x', 1920)}x{scene.get('render_resolution_y', 1080)}",
            ]
            if stream_url:
                info.append(f"Live view: {stream_url}")

            return "\n".join(info)
        except Exception as e:
            return f"Error: {e}"

    # =========================================================================
    # RESOURCES
    # =========================================================================

    @mcp.resource("blender://scene")
    async def resource_scene():
        """Current scene state"""
        try:
            objects = await _call_blender(user_id, "/api/objects")
            return {
                "objects": objects,
                "count": len(objects)
            }
        except:
            return {"objects": [], "count": 0}

    @mcp.resource("blender://projects")
    async def resource_projects():
        """List of saved projects"""
        # TODO: Implement project listing from storage
        return {"projects": []}

    # =========================================================================
    # PROMPTS
    # =========================================================================

    @mcp.prompt()
    async def new_scene():
        """Start with a fresh scene"""
        return {
            "messages": [{
                "role": "user",
                "content": "Clear the scene and set up basic lighting for a new project."
            }]
        }

    @mcp.prompt()
    async def create_from_description(description: str):
        """Create a scene from a text description"""
        return {
            "messages": [{
                "role": "user",
                "content": f"Create a 3D scene based on this description: {description}"
            }]
        }

    # Start autosave for this user
    _start_autosave(user_id)

    return mcp


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

async def _ensure_session(user_id: str):
    """Ensure user has an active Blender container"""
    if not _container_manager:
        raise Exception("Container manager not initialized")

    session = _container_manager.get_session(user_id)

    if not session:
        logger.info(f"Starting Blender for user {user_id[:8]}...")
        session = await _container_manager.start_session(user_id)

        # Wait for ready
        for _ in range(60):
            session = _container_manager.get_session(user_id)
            if session and session.status == "ready":
                logger.info(f"Blender ready for {user_id[:8]}")
                return session
            await asyncio.sleep(1)

        raise Exception("Blender failed to start")

    return session


async def _call_blender(user_id: str, endpoint: str, method: str = "GET", data: dict = None):
    """Call Blender API on user's container"""
    session = await _ensure_session(user_id)
    return await _container_manager.execute_on_container(user_id, endpoint, method, data)


def _start_autosave(user_id: str):
    """Start background autosave"""
    if user_id in _autosave_tasks:
        return

    async def autosave_loop():
        while True:
            await asyncio.sleep(300)  # 5 minutes
            try:
                await _call_blender(user_id, "/api/save", "POST", {
                    "filepath": "/projects/autosave.blend"
                })
            except:
                pass

    _autosave_tasks[user_id] = asyncio.create_task(autosave_loop())


async def cleanup():
    """Cancel all autosave tasks"""
    for task in _autosave_tasks.values():
        task.cancel()
