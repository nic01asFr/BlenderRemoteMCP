#!/usr/bin/env python3
"""
HTTP API Server for Blender Container
Provides REST endpoints to control Blender instance
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uvicorn
import subprocess
import json
import os
import base64
import socket
import struct

app = FastAPI(title="Blender Container API")

# Socket path for communication with Blender addon
BLENDER_SOCKET = "/tmp/blender_api.sock"

# Cadrage du protocole du pont : 4 octets big-endian de longueur, puis JSON.
# Doit rester aligne avec blender_addon.py.
HEADER_FORMAT = ">I"
HEADER_SIZE = 4
MAX_MESSAGE_BYTES = 64 * 1024 * 1024
SOCKET_TIMEOUT = 180.0


class ExecuteRequest(BaseModel):
    code: str


class ObjectRequest(BaseModel):
    type: str = "CUBE"
    name: Optional[str] = None
    location: List[float] = [0, 0, 0]
    rotation: List[float] = [0, 0, 0]
    scale: List[float] = [1, 1, 1]


class ModifyRequest(BaseModel):
    location: Optional[List[float]] = None
    rotation: Optional[List[float]] = None
    scale: Optional[List[float]] = None
    visible: Optional[bool] = None


class MaterialRequest(BaseModel):
    color: List[float]  # RGBA


class SaveRequest(BaseModel):
    filepath: Optional[str] = None


class LoadRequest(BaseModel):
    filepath: Optional[str] = None
    blend_data: Optional[str] = None  # Base64 encoded


def _recv_exactly(sock, n: int):
    """Lit exactement n octets, ou None si la connexion se ferme avant."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def send_to_blender(command: dict) -> dict:
    """Envoie une commande a l'addon Blender via le socket Unix.

    Cadrage en longueur prefixee : l'ancien delimiteur newline dependait de
    l'echappement JSON pour ne pas couper une charge utile au mauvais endroit,
    et ne survivait pas a une reponse volumineuse (capture d'ecran base64).
    """
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        sock.connect(BLENDER_SOCKET)

        payload = json.dumps(command).encode("utf-8")
        sock.sendall(struct.pack(HEADER_FORMAT, len(payload)) + payload)

        header = _recv_exactly(sock, HEADER_SIZE)
        if header is None:
            return {"success": False, "error": "Connexion fermee par Blender avant reponse"}
        (length,) = struct.unpack(HEADER_FORMAT, header)
        if length <= 0 or length > MAX_MESSAGE_BYTES:
            return {"success": False, "error": f"Taille de reponse invalide : {length}"}

        body = _recv_exactly(sock, length)
        if body is None:
            return {"success": False, "error": "Reponse tronquee"}
        return json.loads(body.decode("utf-8"))
    except socket.timeout:
        return {"success": False, "error": f"Timeout apres {SOCKET_TIMEOUT}s"}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


@app.get("/health")
async def health():
    """Health check endpoint"""
    # Check if Blender socket exists
    if os.path.exists(BLENDER_SOCKET):
        result = send_to_blender({"action": "ping"})
        if result.get("success"):
            return {"status": "healthy", "blender": "running"}
    return JSONResponse(
        status_code=503,
        content={"status": "unhealthy", "blender": "not responding"}
    )


@app.get("/api/scene")
async def get_scene():
    """Get current scene information"""
    result = send_to_blender({"action": "get_scene"})
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@app.get("/api/objects")
async def list_objects():
    """List all objects in the scene"""
    result = send_to_blender({"action": "list_objects"})
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result.get("objects", [])


@app.get("/api/object/{name}")
async def get_object(name: str):
    """Get details of a specific object"""
    result = send_to_blender({"action": "get_object", "name": name})
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@app.post("/api/object")
async def create_object(request: ObjectRequest):
    """Create a new object"""
    result = send_to_blender({
        "action": "create_object",
        "type": request.type,
        "name": request.name,
        "location": request.location,
        "rotation": request.rotation,
        "scale": request.scale
    })
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@app.delete("/api/object/{name}")
async def delete_object(name: str):
    """Delete an object"""
    result = send_to_blender({"action": "delete_object", "name": name})
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@app.put("/api/object/{name}")
async def modify_object(name: str, request: ModifyRequest):
    """Modify an object's properties"""
    result = send_to_blender({
        "action": "modify_object",
        "name": name,
        "location": request.location,
        "rotation": request.rotation,
        "scale": request.scale,
        "visible": request.visible
    })
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@app.post("/api/object/{name}/material")
async def set_material(name: str, request: MaterialRequest):
    """Set object material/color"""
    result = send_to_blender({
        "action": "set_material",
        "name": name,
        "color": request.color
    })
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@app.post("/api/execute")
async def execute_code(request: ExecuteRequest):
    """Execute arbitrary Python code in Blender"""
    result = send_to_blender({
        "action": "execute",
        "code": request.code
    })
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@app.post("/api/save")
async def save_project(request: SaveRequest):
    """Save current project"""
    filepath = request.filepath or "/projects/current.blend"
    result = send_to_blender({
        "action": "save",
        "filepath": filepath
    })
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))

    # Return file as base64 if needed
    if os.path.exists(filepath):
        with open(filepath, 'rb') as f:
            blend_data = base64.b64encode(f.read()).decode()
        return {"success": True, "filepath": filepath, "blend_data": blend_data}
    return result


@app.post("/api/load")
async def load_project(request: LoadRequest):
    """Load a project"""
    filepath = request.filepath

    # If blend_data provided, write to temp file first
    if request.blend_data:
        filepath = "/tmp/loaded_project.blend"
        with open(filepath, 'wb') as f:
            f.write(base64.b64decode(request.blend_data))

    if not filepath:
        raise HTTPException(status_code=400, detail="No filepath or blend_data provided")

    result = send_to_blender({
        "action": "load",
        "filepath": filepath
    })
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@app.get("/api/screenshot")
async def screenshot(width: int = 1920, height: int = 1080):
    """Take viewport screenshot (max 1MB output)"""
    # Limit resolution to keep output under 1MB
    max_pixels = 1920 * 1080  # ~1MB PNG limit
    if width * height > max_pixels:
        scale = (max_pixels / (width * height)) ** 0.5
        width = int(width * scale)
        height = int(height * scale)

    result = send_to_blender({
        "action": "screenshot",
        "width": width,
        "height": height
    })
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@app.get("/api/gpu")
async def detect_gpu():
    """Detect available GPU devices for rendering"""
    result = send_to_blender({"action": "detect_gpu"})
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "GPU detection failed"))
    return result


class RenderConfigRequest(BaseModel):
    engine: str = "CYCLES"  # CYCLES, BLENDER_EEVEE, BLENDER_WORKBENCH
    device: str = "GPU"  # GPU or CPU
    device_type: str = "CUDA"  # CUDA, OPTIX, HIP
    samples: int = 128
    use_denoising: bool = True


@app.post("/api/render/configure")
async def configure_render(request: RenderConfigRequest):
    """Configure render engine and device (GPU/CPU)"""
    result = send_to_blender({
        "action": "configure_render",
        "engine": request.engine,
        "device": request.device,
        "device_type": request.device_type,
        "samples": request.samples,
        "use_denoising": request.use_denoising
    })
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Render configuration failed"))
    return result


class KeypressRequest(BaseModel):
    key: str  # Key name (e.g., "Escape", "Return", "a", "ctrl+z")


@app.post("/api/keypress")
async def send_keypress(request: KeypressRequest):
    """Send keypress to Blender window using xdotool"""
    try:
        # Map common key names to xdotool format
        key_map = {
            "escape": "Escape",
            "enter": "Return",
            "return": "Return",
            "space": "space",
            "tab": "Tab",
            "delete": "Delete",
            "backspace": "BackSpace",
        }
        key = key_map.get(request.key.lower(), request.key)

        # Use xdotool to send keypress
        result = subprocess.run(
            ["xdotool", "key", "--window", "$(xdotool search --name 'Blender' | head -1)", key],
            shell=True,
            capture_output=True,
            text=True,
            env={**os.environ, "DISPLAY": ":99"}
        )

        if result.returncode != 0:
            # Try alternative approach
            result = subprocess.run(
                f"DISPLAY=:99 xdotool search --name 'Blender' | head -1 | xargs -I{{}} xdotool key --window {{}} {key}",
                shell=True,
                capture_output=True,
                text=True
            )

        return {"success": True, "key": key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/restart")
async def restart_blender():
    """Restart the Blender process via supervisorctl"""
    try:
        result = subprocess.run(
            ["supervisorctl", "restart", "blender"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return {"success": True, "message": "Blender restarting"}
        else:
            raise HTTPException(status_code=500, detail=result.stderr)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class MouseClickRequest(BaseModel):
    x: int
    y: int
    button: int = 1  # 1=left, 2=middle, 3=right


@app.post("/api/click")
async def send_click(request: MouseClickRequest):
    """Send mouse click to specific coordinates"""
    try:
        result = subprocess.run(
            f"DISPLAY=:99 xdotool mousemove {request.x} {request.y} click {request.button}",
            shell=True,
            capture_output=True,
            text=True
        )
        return {"success": True, "x": request.x, "y": request.y, "button": request.button}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
