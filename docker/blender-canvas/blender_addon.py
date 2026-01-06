#!/usr/bin/env python3
"""
Blender Addon - Socket API Server
Runs inside Blender to handle commands via Unix socket
"""

import bpy
import socket
import os
import json
import threading
import base64
import tempfile
import math
import subprocess

SOCKET_PATH = "/tmp/blender_api.sock"


class BlenderAPIHandler:
    """Handles API commands for Blender"""

    def handle_command(self, command: dict) -> dict:
        """Route command to appropriate handler"""
        action = command.get("action")

        handlers = {
            "ping": self.ping,
            "get_scene": self.get_scene,
            "list_objects": self.list_objects,
            "get_object": self.get_object,
            "create_object": self.create_object,
            "delete_object": self.delete_object,
            "modify_object": self.modify_object,
            "set_material": self.set_material,
            "execute": self.execute_code,
            "save": self.save_project,
            "load": self.load_project,
            "screenshot": self.take_screenshot,
            "detect_gpu": self.detect_gpu,
            "configure_render": self.configure_render_engine,
        }

        handler = handlers.get(action)
        if handler:
            try:
                return handler(command)
            except Exception as e:
                return {"success": False, "error": str(e)}
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    def ping(self, cmd):
        return {"success": True, "message": "pong"}

    def get_scene(self, cmd):
        scene = bpy.context.scene
        return {
            "success": True,
            "name": scene.name,
            "frame_current": scene.frame_current,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "render_resolution_x": scene.render.resolution_x,
            "render_resolution_y": scene.render.resolution_y,
            "object_count": len(bpy.data.objects),
            "camera": scene.camera.name if scene.camera else None
        }

    def list_objects(self, cmd):
        objects = []
        for obj in bpy.data.objects:
            obj_data = {
                "name": obj.name,
                "type": obj.type,
                "location": list(obj.location),
                "rotation": [math.degrees(r) for r in obj.rotation_euler],
                "scale": list(obj.scale),
                "visible": obj.visible_get()
            }

            # Add material info if available
            if hasattr(obj.data, 'materials') and obj.data.materials:
                materials = []
                for mat in obj.data.materials:
                    if mat:
                        mat_info = {"name": mat.name}
                        if mat.use_nodes:
                            # Try to get base color
                            principled = mat.node_tree.nodes.get("Principled BSDF")
                            if principled:
                                color = principled.inputs["Base Color"].default_value
                                mat_info["color"] = list(color)
                        materials.append(mat_info)
                obj_data["materials"] = materials

            objects.append(obj_data)

        return {"success": True, "objects": objects}

    def get_object(self, cmd):
        name = cmd.get("name")
        obj = bpy.data.objects.get(name)

        if not obj:
            return {"success": False, "error": f"Object '{name}' not found"}

        data = {
            "success": True,
            "name": obj.name,
            "type": obj.type,
            "location": list(obj.location),
            "rotation": [math.degrees(r) for r in obj.rotation_euler],
            "scale": list(obj.scale),
            "dimensions": list(obj.dimensions),
            "visible": obj.visible_get(),
            "parent": obj.parent.name if obj.parent else None,
            "children": [c.name for c in obj.children]
        }

        # Mesh-specific data
        if obj.type == 'MESH' and obj.data:
            data["mesh"] = {
                "vertices": len(obj.data.vertices),
                "edges": len(obj.data.edges),
                "polygons": len(obj.data.polygons)
            }

        return data

    def create_object(self, cmd):
        obj_type = cmd.get("type", "CUBE").upper()
        name = cmd.get("name")
        location = cmd.get("location", [0, 0, 0])
        rotation = cmd.get("rotation", [0, 0, 0])
        scale = cmd.get("scale", [1, 1, 1])

        # Track objects before creation to find the new one
        existing_objects = set(bpy.data.objects.keys())

        # Create mesh based on type
        if obj_type == "CUBE":
            bpy.ops.mesh.primitive_cube_add(location=location)
        elif obj_type == "SPHERE":
            bpy.ops.mesh.primitive_uv_sphere_add(location=location)
        elif obj_type == "CYLINDER":
            bpy.ops.mesh.primitive_cylinder_add(location=location)
        elif obj_type == "CONE":
            bpy.ops.mesh.primitive_cone_add(location=location)
        elif obj_type == "TORUS":
            bpy.ops.mesh.primitive_torus_add(location=location)
        elif obj_type == "PLANE":
            bpy.ops.mesh.primitive_plane_add(location=location)
        elif obj_type == "MONKEY":
            bpy.ops.mesh.primitive_monkey_add(location=location)
        elif obj_type == "EMPTY":
            bpy.ops.object.empty_add(location=location)
        elif obj_type == "CAMERA":
            bpy.ops.object.camera_add(location=location)
        elif obj_type == "LIGHT":
            bpy.ops.object.light_add(type='POINT', location=location)
        else:
            return {"success": False, "error": f"Unknown object type: {obj_type}"}

        # Find the newly created object
        new_objects = set(bpy.data.objects.keys()) - existing_objects
        if not new_objects:
            return {"success": False, "error": "Failed to create object"}

        obj = bpy.data.objects[list(new_objects)[0]]

        # Rename if name provided
        if name:
            obj.name = name

        # Apply rotation (convert degrees to radians)
        obj.rotation_euler = [math.radians(r) for r in rotation]

        # Apply scale
        obj.scale = scale

        return {
            "success": True,
            "name": obj.name,
            "type": obj.type,
            "location": list(obj.location)
        }

    def delete_object(self, cmd):
        name = cmd.get("name")
        obj = bpy.data.objects.get(name)

        if not obj:
            return {"success": False, "error": f"Object '{name}' not found"}

        # Select and delete
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.delete()

        return {"success": True, "message": f"Object '{name}' deleted"}

    def modify_object(self, cmd):
        name = cmd.get("name")
        obj = bpy.data.objects.get(name)

        if not obj:
            return {"success": False, "error": f"Object '{name}' not found"}

        if cmd.get("location") is not None:
            obj.location = cmd["location"]

        if cmd.get("rotation") is not None:
            obj.rotation_euler = [math.radians(r) for r in cmd["rotation"]]

        if cmd.get("scale") is not None:
            obj.scale = cmd["scale"]

        if cmd.get("visible") is not None:
            obj.hide_viewport = not cmd["visible"]
            obj.hide_render = not cmd["visible"]

        return {
            "success": True,
            "name": obj.name,
            "location": list(obj.location),
            "rotation": [math.degrees(r) for r in obj.rotation_euler],
            "scale": list(obj.scale),
            "visible": obj.visible_get()
        }

    def set_material(self, cmd):
        name = cmd.get("name")
        color = cmd.get("color", [1, 0, 0, 1])  # Default red

        obj = bpy.data.objects.get(name)
        if not obj:
            return {"success": False, "error": f"Object '{name}' not found"}

        if not hasattr(obj.data, 'materials'):
            return {"success": False, "error": f"Object '{name}' cannot have materials"}

        # Create new material
        mat_name = f"{name}_material"
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            mat = bpy.data.materials.new(name=mat_name)

        mat.use_nodes = True
        principled = mat.node_tree.nodes.get("Principled BSDF")
        if principled:
            principled.inputs["Base Color"].default_value = color

        # Assign to object
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

        return {"success": True, "material": mat_name, "color": color}

    def execute_code(self, cmd):
        code = cmd.get("code", "")

        # Create namespace for execution
        namespace = {"bpy": bpy, "result": None}

        try:
            exec(code, namespace)
            result = namespace.get("result")

            # Convert result to JSON-serializable format
            if result is not None:
                if hasattr(result, '__dict__'):
                    result = str(result)

            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_project(self, cmd):
        filepath = cmd.get("filepath", "/projects/current.blend")

        try:
            bpy.ops.wm.save_as_mainfile(filepath=filepath)
            return {"success": True, "filepath": filepath}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def load_project(self, cmd):
        filepath = cmd.get("filepath")

        if not filepath or not os.path.exists(filepath):
            return {"success": False, "error": "File not found"}

        try:
            bpy.ops.wm.open_mainfile(filepath=filepath)
            return {"success": True, "filepath": filepath}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def take_screenshot(self, cmd):
        """Render the scene and return the image"""
        width = cmd.get("width", 1920)
        height = cmd.get("height", 1080)

        scene = bpy.context.scene
        scene.render.resolution_x = width
        scene.render.resolution_y = height

        temp_path = tempfile.mktemp(suffix=".png")
        scene.render.filepath = temp_path

        try:
            # Render with current engine (Eevee by default)
            bpy.ops.render.render(write_still=True)

            with open(temp_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode()

            os.remove(temp_path)

            return {
                "success": True,
                "format": "png",
                "width": width,
                "height": height,
                "data": image_data
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def detect_gpu(self, cmd):
        """Detect available GPU devices for rendering"""
        try:
            gpu_info = {
                "cuda": [],
                "optix": [],
                "hip": [],
                "cpu": True,
                "blender_devices": []
            }

            # Check NVIDIA GPU via nvidia-smi
            try:
                result = subprocess.run(
                    ['nvidia-smi', '--query-gpu=index,name,memory.total', '--format=csv,noheader,nounits'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if line:
                            parts = line.split(', ')
                            if len(parts) >= 3:
                                idx, name, memory = parts[0], parts[1], parts[2]
                                gpu_info['cuda'].append({
                                    'index': int(idx),
                                    'name': name,
                                    'memory_mb': int(float(memory))
                                })
                                # OptiX available on RTX cards
                                if 'RTX' in name or 'A100' in name or 'A6000' in name:
                                    gpu_info['optix'].append({'index': int(idx), 'name': name})
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

            # Check AMD GPU via rocm-smi
            try:
                result = subprocess.run(
                    ['rocm-smi', '--showid'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    gpu_info['hip'].append({'available': True})
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

            # Get Blender's view of available devices
            try:
                cycles_prefs = bpy.context.preferences.addons['cycles'].preferences
                for device in cycles_prefs.devices:
                    gpu_info['blender_devices'].append({
                        'name': device.name,
                        'type': device.type,
                        'use': device.use
                    })
            except Exception as e:
                gpu_info['blender_devices_error'] = str(e)

            return {
                "success": True,
                "gpus": gpu_info,
                "recommended": self._recommend_render_device(gpu_info)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _recommend_render_device(self, gpu_info):
        """Recommend best render device based on available hardware"""
        if gpu_info['optix']:
            return {'device': 'GPU', 'type': 'OPTIX', 'reason': 'NVIDIA RTX GPU with OptiX support'}
        elif gpu_info['cuda']:
            return {'device': 'GPU', 'type': 'CUDA', 'reason': 'NVIDIA GPU with CUDA support'}
        elif gpu_info['hip']:
            return {'device': 'GPU', 'type': 'HIP', 'reason': 'AMD GPU with HIP support'}
        else:
            return {'device': 'CPU', 'type': 'CPU', 'reason': 'No GPU detected, using CPU'}

    def configure_render_engine(self, cmd):
        """Configure render engine (CYCLES, EEVEE, WORKBENCH) with GPU/CPU selection"""
        try:
            engine = cmd.get("engine", "CYCLES").upper()
            device = cmd.get("device", "GPU").upper()  # GPU or CPU
            device_type = cmd.get("device_type", "CUDA").upper()  # CUDA, OPTIX, HIP
            samples = cmd.get("samples", 128)
            use_denoising = cmd.get("use_denoising", True)

            scene = bpy.context.scene

            # Set render engine
            if engine not in ['CYCLES', 'BLENDER_EEVEE', 'BLENDER_WORKBENCH']:
                return {"success": False, "error": f"Invalid engine: {engine}"}

            scene.render.engine = engine

            # Configure Cycles-specific settings
            if engine == 'CYCLES':
                # Enable Cycles addon if not already
                try:
                    bpy.ops.preferences.addon_enable(module='cycles')
                except:
                    pass

                cycles_prefs = bpy.context.preferences.addons['cycles'].preferences

                # Set device type (GPU or CPU)
                if device == 'GPU':
                    # Configure GPU type
                    if device_type in ['CUDA', 'OPTIX', 'HIP', 'ONEAPI']:
                        try:
                            cycles_prefs.compute_device_type = device_type
                            scene.cycles.device = 'GPU'

                            # Enable all devices of the selected type
                            for dev in cycles_prefs.devices:
                                if dev.type == device_type:
                                    dev.use = True
                                else:
                                    dev.use = False
                        except Exception as e:
                            # Fallback to CPU if GPU config fails
                            scene.cycles.device = 'CPU'
                            return {
                                "success": True,
                                "warning": f"GPU config failed, using CPU: {e}",
                                "device": "CPU"
                            }
                    else:
                        return {"success": False, "error": f"Invalid device_type: {device_type}"}
                else:
                    scene.cycles.device = 'CPU'

                # Set quality/performance settings
                scene.cycles.samples = samples
                scene.cycles.use_adaptive_sampling = True
                scene.cycles.adaptive_threshold = 0.01

                # Denoising
                scene.cycles.use_denoising = use_denoising
                if use_denoising:
                    scene.cycles.denoiser = 'OPENIMAGEDENOISE'

                return {
                    "success": True,
                    "engine": engine,
                    "device": scene.cycles.device,
                    "device_type": cycles_prefs.compute_device_type if device == 'GPU' else 'CPU',
                    "samples": samples,
                    "denoising": use_denoising
                }
            else:
                # EEVEE or WORKBENCH
                return {
                    "success": True,
                    "engine": engine,
                    "device": "N/A (non-Cycles engine)"
                }

        except Exception as e:
            return {"success": False, "error": str(e)}


class SocketServer:
    """Unix socket server for receiving commands"""

    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.handler = BlenderAPIHandler()
        self.running = False
        self.server_socket = None

    def start(self):
        """Start the socket server"""
        # Remove existing socket
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.bind(self.socket_path)
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)
        self.running = True

        print(f"Blender API listening on {self.socket_path}")

        while self.running:
            try:
                client, _ = self.server_socket.accept()
                self.handle_client(client)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Socket error: {e}")

    def handle_client(self, client):
        """Handle a single client connection"""
        try:
            data = b''
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b'\n' in chunk:
                    break

            if data:
                command = json.loads(data.decode().strip())
                response = self.handler.handle_command(command)
                client.sendall(json.dumps(response).encode() + b'\n')
        except Exception as e:
            error_response = {"success": False, "error": str(e)}
            client.sendall(json.dumps(error_response).encode() + b'\n')
        finally:
            client.close()

    def stop(self):
        """Stop the socket server"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)


# Global server instance
server = None


def start_server():
    """Start the socket server in a background thread"""
    global server
    server = SocketServer(SOCKET_PATH)
    server_thread = threading.Thread(target=server.start, daemon=True)
    server_thread.start()


def register():
    """Register the addon"""
    start_server()
    print("Blender API Server started")


def unregister():
    """Unregister the addon"""
    global server
    if server:
        server.stop()
    print("Blender API Server stopped")


if __name__ == "__main__":
    register()

    # Keep Blender running
    print("Blender is ready. API server running.")
