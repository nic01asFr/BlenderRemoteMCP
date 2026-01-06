"""
MCP Server for multi-instance Blender management
Implements proper Model Context Protocol with FastMCP
"""

from fastmcp import FastMCP
from typing import Optional, List, Dict, Any
import logging
import httpx
import json

logger = logging.getLogger(__name__)

# Create the MCP server instance
mcp = FastMCP(
    name="BlenderWebService",
    version="1.0.0",
    description="Multi-user Blender instance management via MCP"
)

# Reference to blender_manager will be set during initialization
_blender_manager = None
_http_client: Optional[httpx.AsyncClient] = None


async def initialize(blender_manager):
    """Initialize MCP server with reference to BlenderInstanceManager"""
    global _blender_manager, _http_client
    _blender_manager = blender_manager
    _http_client = httpx.AsyncClient(timeout=60.0)
    logger.info("MCP Server initialized")


async def cleanup():
    """Cleanup resources"""
    global _http_client
    if _http_client:
        await _http_client.aclose()
    logger.info("MCP Server cleanup complete")


# =============================================================================
# INSTANCE MANAGEMENT TOOLS
# =============================================================================

@mcp.tool
async def list_instances() -> Dict[str, Any]:
    """
    List all active Blender instances.

    Returns information about each running instance including:
    - instance_id: Unique identifier to use with other tools
    - name: Human-readable name
    - status: Current status (running, stopped, etc.)
    - port: Network port
    """
    if not _blender_manager:
        return {"error": "MCP server not initialized"}

    instances = await _blender_manager.list_instances()
    return {
        "instances": [
            {
                "instance_id": inst.instance_id,
                "name": inst.name,
                "status": inst.status.value,
                "port": inst.port,
                "blender_version": inst.blender_version,
                "created_at": inst.created_at.isoformat(),
                "memory_usage_mb": inst.memory_usage,
                "cpu_usage_percent": inst.cpu_usage
            }
            for inst in instances
        ],
        "total_count": len(instances)
    }


@mcp.tool
async def get_instance_status(instance_id: str) -> Dict[str, Any]:
    """
    Get detailed status of a specific Blender instance.

    Args:
        instance_id: The unique identifier of the Blender instance

    Returns:
        Detailed status including health, memory, CPU usage
    """
    if not _blender_manager:
        return {"error": "MCP server not initialized"}

    instance = await _blender_manager.get_instance(instance_id)
    if not instance:
        return {"error": f"Instance {instance_id} not found"}

    live_status = None
    try:
        response = await _http_client.get(
            f"http://localhost:{instance.port}/api/status"
        )
        if response.status_code == 200:
            live_status = response.json()
    except Exception:
        pass

    return {
        "instance_id": instance.instance_id,
        "name": instance.name,
        "status": instance.status.value,
        "port": instance.port,
        "blender_version": instance.blender_version,
        "created_at": instance.created_at.isoformat(),
        "memory_usage_mb": instance.memory_usage,
        "cpu_usage_percent": instance.cpu_usage,
        "live_status": live_status
    }


# =============================================================================
# SCENE INFORMATION TOOLS
# =============================================================================

@mcp.tool
async def get_scene_info(instance_id: str) -> Dict[str, Any]:
    """
    Get information about the current Blender scene.

    Args:
        instance_id: The Blender instance to query

    Returns:
        Scene name, object list, frame range, and other scene properties
    """
    if not _blender_manager:
        return {"error": "MCP server not initialized"}

    instance = await _blender_manager.get_instance(instance_id)
    if not instance:
        return {"error": f"Instance {instance_id} not found"}

    try:
        response = await _http_client.get(
            f"http://localhost:{instance.port}/api/scene"
        )
        if response.status_code == 200:
            return response.json()
        return {"error": f"Failed to get scene info: {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool
async def list_objects(instance_id: str) -> Dict[str, Any]:
    """
    List all objects in the current Blender scene.

    Args:
        instance_id: The Blender instance to query

    Returns:
        List of all objects with basic info (name, type, location)
    """
    if not _blender_manager:
        return {"error": "MCP server not initialized"}

    instance = await _blender_manager.get_instance(instance_id)
    if not instance:
        return {"error": f"Instance {instance_id} not found"}

    try:
        response = await _http_client.get(
            f"http://localhost:{instance.port}/api/objects"
        )
        if response.status_code == 200:
            return {"objects": response.json()}
        return {"error": f"Failed to list objects: {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool
async def get_object_info(instance_id: str, object_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific object in the scene.

    Args:
        instance_id: The Blender instance to query
        object_name: Name of the object to inspect

    Returns:
        Object type, location, rotation, scale, materials, and other properties
    """
    code = f'''
import bpy
import json

obj = bpy.data.objects.get("{object_name}")
if obj is None:
    result = {{"error": "Object '{object_name}' not found"}}
else:
    result = {{
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
        "rotation_euler": list(obj.rotation_euler),
        "scale": list(obj.scale),
        "dimensions": list(obj.dimensions),
        "visible": obj.visible_get(),
        "materials": [mat.name for mat in obj.data.materials] if hasattr(obj.data, 'materials') and obj.data.materials else [],
        "parent": obj.parent.name if obj.parent else None,
        "children": [child.name for child in obj.children]
    }}
print(json.dumps(result))
'''
    return await execute_blender_code(instance_id, code)


# =============================================================================
# OBJECT MANIPULATION TOOLS
# =============================================================================

@mcp.tool
async def create_object(
    instance_id: str,
    object_type: str,
    name: Optional[str] = None,
    location: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    Create a new 3D object in the Blender scene.

    Args:
        instance_id: The Blender instance to modify
        object_type: Type of object: 'CUBE', 'SPHERE', 'CYLINDER', 'CONE',
                     'PLANE', 'TORUS', 'MONKEY', 'EMPTY', 'CAMERA', 'LIGHT'
        name: Optional custom name for the object
        location: [x, y, z] position in 3D space (default: [0, 0, 0])
        rotation: [x, y, z] rotation in radians (default: [0, 0, 0])
        scale: [x, y, z] scale factors (default: [1, 1, 1])

    Returns:
        Information about the created object
    """
    loc = location or [0, 0, 0]
    rot = rotation or [0, 0, 0]
    scl = scale or [1, 1, 1]

    type_to_op = {
        'CUBE': 'bpy.ops.mesh.primitive_cube_add',
        'SPHERE': 'bpy.ops.mesh.primitive_uv_sphere_add',
        'CYLINDER': 'bpy.ops.mesh.primitive_cylinder_add',
        'CONE': 'bpy.ops.mesh.primitive_cone_add',
        'PLANE': 'bpy.ops.mesh.primitive_plane_add',
        'TORUS': 'bpy.ops.mesh.primitive_torus_add',
        'MONKEY': 'bpy.ops.mesh.primitive_monkey_add',
        'EMPTY': 'bpy.ops.object.empty_add',
        'CAMERA': 'bpy.ops.object.camera_add',
        'LIGHT': 'bpy.ops.object.light_add',
    }

    op = type_to_op.get(object_type.upper())
    if not op:
        return {"error": f"Unknown object type: {object_type}. Valid types: {list(type_to_op.keys())}"}

    name_line = f'obj.name = "{name}"' if name else ''

    code = f'''
import bpy
import json

{op}(location=({loc[0]}, {loc[1]}, {loc[2]}))
obj = bpy.context.active_object
obj.rotation_euler = ({rot[0]}, {rot[1]}, {rot[2]})
obj.scale = ({scl[0]}, {scl[1]}, {scl[2]})
{name_line}

result = {{
    "success": True,
    "name": obj.name,
    "type": obj.type,
    "location": list(obj.location)
}}
print(json.dumps(result))
'''
    return await execute_blender_code(instance_id, code)


@mcp.tool
async def delete_object(instance_id: str, object_name: str) -> Dict[str, Any]:
    """
    Delete an object from the Blender scene.

    Args:
        instance_id: The Blender instance to modify
        object_name: Name of the object to delete

    Returns:
        Confirmation of deletion
    """
    code = f'''
import bpy
import json

obj = bpy.data.objects.get("{object_name}")
if obj is None:
    result = {{"error": "Object '{object_name}' not found"}}
else:
    bpy.data.objects.remove(obj, do_unlink=True)
    result = {{"success": True, "deleted": "{object_name}"}}
print(json.dumps(result))
'''
    return await execute_blender_code(instance_id, code)


@mcp.tool
async def modify_object(
    instance_id: str,
    object_name: str,
    location: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    visible: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Modify properties of an existing object.

    Args:
        instance_id: The Blender instance to modify
        object_name: Name of the object to modify
        location: New [x, y, z] position (optional)
        rotation: New [x, y, z] rotation in radians (optional)
        scale: New [x, y, z] scale (optional)
        visible: Set visibility (optional)

    Returns:
        Updated object properties
    """
    modifications = []
    if location:
        modifications.append(f'    obj.location = ({location[0]}, {location[1]}, {location[2]})')
    if rotation:
        modifications.append(f'    obj.rotation_euler = ({rotation[0]}, {rotation[1]}, {rotation[2]})')
    if scale:
        modifications.append(f'    obj.scale = ({scale[0]}, {scale[1]}, {scale[2]})')
    if visible is not None:
        modifications.append(f'    obj.hide_set({not visible})')

    mods_code = '\n'.join(modifications) if modifications else '    pass'

    code = f'''
import bpy
import json

obj = bpy.data.objects.get("{object_name}")
if obj is None:
    result = {{"error": "Object '{object_name}' not found"}}
else:
{mods_code}
    result = {{
        "success": True,
        "name": obj.name,
        "location": list(obj.location),
        "rotation_euler": list(obj.rotation_euler),
        "scale": list(obj.scale)
    }}
print(json.dumps(result))
'''
    return await execute_blender_code(instance_id, code)


# =============================================================================
# MATERIAL TOOLS
# =============================================================================

@mcp.tool
async def set_object_material(
    instance_id: str,
    object_name: str,
    color: List[float],
    material_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Set or create a material for an object with a specified color.

    Args:
        instance_id: The Blender instance to modify
        object_name: Name of the object to apply material to
        color: RGBA color as [r, g, b, a] with values 0.0-1.0
        material_name: Optional name for the material

    Returns:
        Information about the applied material
    """
    mat_name = material_name or f"{object_name}_material"
    r, g, b = color[0], color[1], color[2]
    a = color[3] if len(color) > 3 else 1.0

    code = f'''
import bpy
import json

obj = bpy.data.objects.get("{object_name}")
if obj is None:
    result = {{"error": "Object '{object_name}' not found"}}
elif not hasattr(obj.data, 'materials'):
    result = {{"error": "Object '{object_name}' does not support materials"}}
else:
    mat = bpy.data.materials.new(name="{mat_name}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = ({r}, {g}, {b}, {a})

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    result = {{
        "success": True,
        "object": "{object_name}",
        "material": mat.name,
        "color": [{r}, {g}, {b}, {a}]
    }}
print(json.dumps(result))
'''
    return await execute_blender_code(instance_id, code)


# =============================================================================
# CODE EXECUTION
# =============================================================================

@mcp.tool
async def execute_blender_code(instance_id: str, code: str) -> Dict[str, Any]:
    """
    Execute arbitrary Python code in a Blender instance.

    This is a powerful tool that allows running any valid Blender Python code.
    The code has access to bpy, bmesh, and mathutils modules.

    Args:
        instance_id: The Blender instance to execute code in
        code: Python code to execute

    Returns:
        Execution result including any printed output
    """
    if not _blender_manager:
        return {"error": "MCP server not initialized"}

    instance = await _blender_manager.get_instance(instance_id)
    if not instance:
        return {"error": f"Instance {instance_id} not found"}

    if instance.status.value != "running":
        return {"error": f"Instance {instance_id} is not running (status: {instance.status.value})"}

    try:
        response = await _http_client.post(
            f"http://localhost:{instance.port}/api/execute",
            json={"code": code}
        )
        if response.status_code == 200:
            result = response.json()
            # Try to parse JSON from output if the code printed JSON
            if result.get("success") and result.get("result"):
                try:
                    parsed = json.loads(result["result"].strip())
                    return parsed
                except (json.JSONDecodeError, AttributeError):
                    pass
            return result
        return {"error": f"Execution failed with status {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# VIEWPORT/RENDERING TOOLS
# =============================================================================

@mcp.tool
async def get_viewport_screenshot(
    instance_id: str,
    width: int = 800,
    height: int = 600
) -> Dict[str, Any]:
    """
    Capture a screenshot of the current viewport.

    Args:
        instance_id: The Blender instance to capture from
        width: Image width in pixels (default: 800)
        height: Image height in pixels (default: 600)

    Returns:
        Base64-encoded PNG image data
    """
    code = f'''
import bpy
import json
import base64
import tempfile
import os

bpy.context.scene.render.resolution_x = {width}
bpy.context.scene.render.resolution_y = {height}
bpy.context.scene.render.resolution_percentage = 100

temp_path = os.path.join(tempfile.gettempdir(), "viewport_capture.png")
bpy.context.scene.render.filepath = temp_path
bpy.ops.render.opengl(write_still=True)

with open(temp_path, 'rb') as f:
    img_data = base64.b64encode(f.read()).decode('utf-8')

os.remove(temp_path)

result = {{
    "success": True,
    "width": {width},
    "height": {height},
    "format": "png",
    "data": img_data
}}
print(json.dumps(result))
'''
    return await execute_blender_code(instance_id, code)


# =============================================================================
# POLYHAVEN INTEGRATION
# =============================================================================

POLYHAVEN_API = "https://api.polyhaven.com"


@mcp.tool
async def search_polyhaven_assets(
    asset_type: str,
    categories: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Search for free assets on Poly Haven (HDRIs, textures, models).

    Args:
        asset_type: Type of asset: 'hdris', 'textures', or 'models'
        categories: Optional list of categories to filter by

    Returns:
        List of matching assets with id, name, and preview info
    """
    if asset_type not in ['hdris', 'textures', 'models']:
        return {"error": "asset_type must be 'hdris', 'textures', or 'models'"}

    try:
        url = f"{POLYHAVEN_API}/assets?t={asset_type}"
        if categories:
            url += f"&c={','.join(categories)}"

        response = await _http_client.get(
            url,
            headers={"User-Agent": "BlenderWebService/1.0"}
        )

        if response.status_code == 200:
            data = response.json()
            assets = []
            for asset_id, info in list(data.items())[:50]:  # Limit to 50 results
                assets.append({
                    "id": asset_id,
                    "name": info.get("name", asset_id),
                    "categories": info.get("categories", []),
                    "tags": info.get("tags", [])[:5],
                    "download_count": info.get("download_count", 0)
                })
            return {
                "asset_type": asset_type,
                "count": len(assets),
                "assets": sorted(assets, key=lambda x: x["download_count"], reverse=True)
            }
        return {"error": f"PolyHaven API error: {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool
async def get_polyhaven_asset_info(asset_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific Poly Haven asset.

    Args:
        asset_id: The asset identifier from search results

    Returns:
        Available resolutions, file formats, and download URLs
    """
    try:
        response = await _http_client.get(
            f"{POLYHAVEN_API}/files/{asset_id}",
            headers={"User-Agent": "BlenderWebService/1.0"}
        )

        if response.status_code == 200:
            data = response.json()
            return {
                "asset_id": asset_id,
                "files": data
            }
        return {"error": f"Asset not found: {asset_id}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool
async def download_polyhaven_hdri(
    instance_id: str,
    asset_id: str,
    resolution: str = "1k"
) -> Dict[str, Any]:
    """
    Download and apply an HDRI from Poly Haven as world environment.

    Args:
        instance_id: The Blender instance to modify
        asset_id: The HDRI asset ID from search
        resolution: Resolution to download (1k, 2k, 4k, 8k)

    Returns:
        Confirmation of HDRI application
    """
    # Get file info
    try:
        response = await _http_client.get(
            f"{POLYHAVEN_API}/files/{asset_id}",
            headers={"User-Agent": "BlenderWebService/1.0"}
        )
        if response.status_code != 200:
            return {"error": f"Asset not found: {asset_id}"}

        files = response.json()
        hdri_url = None

        # Find the HDR file at requested resolution
        if "hdri" in files and resolution in files["hdri"]:
            if "hdr" in files["hdri"][resolution]:
                hdri_url = files["hdri"][resolution]["hdr"]["url"]

        if not hdri_url:
            return {"error": f"HDRI not available at resolution {resolution}"}

    except Exception as e:
        return {"error": f"Failed to get asset info: {e}"}

    code = f'''
import bpy
import json
import urllib.request
import tempfile
import os

hdri_url = "{hdri_url}"
temp_path = os.path.join(tempfile.gettempdir(), "{asset_id}_{resolution}.hdr")

try:
    urllib.request.urlretrieve(hdri_url, temp_path)

    # Setup world nodes
    world = bpy.context.scene.world
    if not world:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world

    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()

    # Create nodes
    tex_coord = tree.nodes.new('ShaderNodeTexCoord')
    mapping = tree.nodes.new('ShaderNodeMapping')
    env_tex = tree.nodes.new('ShaderNodeTexEnvironment')
    background = tree.nodes.new('ShaderNodeBackground')
    output = tree.nodes.new('ShaderNodeOutputWorld')

    # Load HDRI
    env_tex.image = bpy.data.images.load(temp_path)

    # Connect nodes
    tree.links.new(tex_coord.outputs['Generated'], mapping.inputs['Vector'])
    tree.links.new(mapping.outputs['Vector'], env_tex.inputs['Vector'])
    tree.links.new(env_tex.outputs['Color'], background.inputs['Color'])
    tree.links.new(background.outputs['Background'], output.inputs['Surface'])

    result = {{"success": True, "hdri": "{asset_id}", "resolution": "{resolution}"}}
except Exception as e:
    result = {{"error": str(e)}}

print(json.dumps(result))
'''
    return await execute_blender_code(instance_id, code)


@mcp.tool
async def download_polyhaven_model(
    instance_id: str,
    asset_id: str,
    file_format: str = "gltf"
) -> Dict[str, Any]:
    """
    Download and import a 3D model from Poly Haven.

    Args:
        instance_id: The Blender instance to modify
        asset_id: The model asset ID from search
        file_format: Format to download (gltf, fbx, blend)

    Returns:
        Information about imported objects
    """
    try:
        response = await _http_client.get(
            f"{POLYHAVEN_API}/files/{asset_id}",
            headers={"User-Agent": "BlenderWebService/1.0"}
        )
        if response.status_code != 200:
            return {"error": f"Asset not found: {asset_id}"}

        files = response.json()
        model_url = None

        # Find the model file
        if file_format in files:
            for res_key, res_data in files[file_format].items():
                if file_format in res_data:
                    model_url = res_data[file_format]["url"]
                    break

        if not model_url:
            return {"error": f"Model not available in format {file_format}"}

    except Exception as e:
        return {"error": f"Failed to get asset info: {e}"}

    import_cmd = {
        "gltf": "bpy.ops.import_scene.gltf(filepath=temp_path)",
        "fbx": "bpy.ops.import_scene.fbx(filepath=temp_path)",
        "blend": "bpy.ops.wm.append(filepath=temp_path)"
    }.get(file_format, "bpy.ops.import_scene.gltf(filepath=temp_path)")

    ext = {"gltf": ".glb", "fbx": ".fbx", "blend": ".blend"}.get(file_format, ".glb")

    code = f'''
import bpy
import json
import urllib.request
import tempfile
import os

model_url = "{model_url}"
temp_path = os.path.join(tempfile.gettempdir(), "{asset_id}{ext}")

try:
    urllib.request.urlretrieve(model_url, temp_path)

    objects_before = set(obj.name for obj in bpy.data.objects)
    {import_cmd}
    objects_after = set(obj.name for obj in bpy.data.objects)

    new_objects = list(objects_after - objects_before)

    result = {{
        "success": True,
        "model": "{asset_id}",
        "format": "{file_format}",
        "imported_objects": new_objects
    }}
except Exception as e:
    result = {{"error": str(e)}}

print(json.dumps(result))
'''
    return await execute_blender_code(instance_id, code)


# =============================================================================
# RESOURCES
# =============================================================================

@mcp.resource("blender://instances")
async def instances_resource() -> str:
    """List of all active Blender instances"""
    result = await list_instances()
    return json.dumps(result, indent=2, default=str)


@mcp.resource("blender://instance/{instance_id}/scene")
async def scene_resource(instance_id: str) -> str:
    """Current scene information for a specific instance"""
    result = await get_scene_info(instance_id)
    return json.dumps(result, indent=2, default=str)


@mcp.resource("blender://instance/{instance_id}/objects")
async def objects_resource(instance_id: str) -> str:
    """List of objects in a specific instance"""
    result = await list_objects(instance_id)
    return json.dumps(result, indent=2, default=str)
