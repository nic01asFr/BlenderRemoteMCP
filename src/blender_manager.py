"""
Gestionnaire d'instances Blender
Responsable de créer, gérer et arrêter les instances Blender
"""

import asyncio
import subprocess
import psutil
import uuid
import logging
import os
import json
import tempfile
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from .models import BlenderInstance, InstanceStatus, CommandResponse
from .port_manager import PortManager

logger = logging.getLogger(__name__)

class BlenderInstanceManager:
    """Gestionnaire des instances Blender"""
    
    def __init__(self, base_port: int = 8080, max_instances: int = 10):
        self.instances: Dict[str, BlenderInstance] = {}
        self.processes: Dict[str, subprocess.Popen] = {}
        self.port_manager = PortManager(base_port, max_instances)
        self.blender_executable = self._find_blender_executable()
        self.temp_dir = Path(tempfile.gettempdir()) / "blender_web_service"
        self.temp_dir.mkdir(exist_ok=True)
    
    def _find_blender_executable(self) -> str:
        """Recherche l'exécutable Blender dans le système"""
        possible_paths = [
            "C:/Program Files/Blender Foundation/Blender 3.6/blender.exe",
            "C:/Program Files/Blender Foundation/Blender 4.0/blender.exe",
            "/usr/bin/blender",
            "/Applications/Blender.app/Contents/MacOS/Blender",
            "blender"  # Si dans le PATH
        ]
        
        for path in possible_paths:
            if os.path.exists(path) or path == "blender":
                try:
                    # Test si l'exécutable fonctionne
                    result = subprocess.run(
                        [path, "--version"], 
                        capture_output=True, 
                        text=True, 
                        timeout=10
                    )
                    if result.returncode == 0:
                        logger.info(f"Blender trouvé : {path}")
                        return path
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    continue
        
        raise FileNotFoundError("Blender non trouvé dans le système")
    
    async def initialize(self):
        """Initialisation du gestionnaire"""
        logger.info("Initialisation du gestionnaire Blender")
        await self.port_manager.initialize()
        
        # Vérification des ressources système
        memory = psutil.virtual_memory()
        if memory.available < 2 * 1024 * 1024 * 1024:  # 2GB
            logger.warning("Mémoire disponible faible, performances dégradées possibles")
    
    async def create_instance(
        self, 
        name: str, 
        blender_version: str = "3.6",
        additional_addons: List[str] = None
    ) -> BlenderInstance:
        """Créer une nouvelle instance Blender"""
        if additional_addons is None:
            additional_addons = []
        
        # Génération d'un ID unique
        instance_id = str(uuid.uuid4())
        
        # Attribution d'un port
        port = await self.port_manager.allocate_port()
        if port is None:
            raise RuntimeError("Aucun port disponible pour la nouvelle instance")
        
        # Création de l'instance
        instance = BlenderInstance(
            instance_id=instance_id,
            name=name,
            port=port,
            status=InstanceStatus.STARTING,
            blender_version=blender_version,
            additional_addons=additional_addons
        )
        
        try:
            # Création du script de démarrage pour Blender avec serveur web
            startup_script = self._create_startup_script(instance)
            
            # Commande pour lancer Blender avec le script
            cmd = [
                self.blender_executable,
                "--background",
                "--python", startup_script
            ]
            
            logger.info(f"Démarrage de l'instance {name} sur le port {port}")
            
            # Lancement du processus Blender
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Attendre que le serveur soit prêt
            await self._wait_for_server_ready(port, timeout=30)
            
            # Mise à jour du statut et sauvegarde
            instance.status = InstanceStatus.RUNNING
            instance.process_id = process.pid
            
            self.instances[instance_id] = instance
            self.processes[instance_id] = process
            
            # Démarrage du monitoring
            asyncio.create_task(self._monitor_instance(instance_id))
            
            return instance
            
        except Exception as e:
            # Nettoyage en cas d'erreur
            await self.port_manager.release_port(port)
            if instance_id in self.instances:
                del self.instances[instance_id]
            if instance_id in self.processes:
                self.processes[instance_id].terminate()
                del self.processes[instance_id]
            
            logger.error(f"Erreur lors de la création de l'instance {name}: {e}")
            raise RuntimeError(f"Impossible de créer l'instance: {e}")
    
    def _create_startup_script(self, instance: BlenderInstance) -> str:
        """Créer le script Python de démarrage pour Blender"""
        script_content = f"""
import bpy
import bmesh
import json
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import urllib.parse

# Configuration du serveur HTTP pour cette instance
PORT = {instance.port}
INSTANCE_ID = "{instance.instance_id}"

class BlenderHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            html = f'''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Instance Blender - {instance.name}</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; }}
                    .header {{ background: #007acc; color: white; padding: 20px; border-radius: 5px; }}
                    .info {{ margin: 20px 0; padding: 20px; background: #f5f5f5; border-radius: 5px; }}
                    .api-section {{ margin: 20px 0; }}
                    .endpoint {{ background: white; padding: 10px; margin: 5px 0; border-left: 4px solid #007acc; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>Instance Blender: {instance.name}</h1>
                    <p>ID: {instance.instance_id}</p>
                    <p>Port: {instance.port}</p>
                </div>
                
                <div class="info">
                    <h2>Informations</h2>
                    <p><strong>Version Blender:</strong> {{bpy.app.version_string}}</p>
                    <p><strong>Statut:</strong> En fonctionnement</p>
                    <p><strong>Nombre d'objets:</strong> {{len(bpy.data.objects)}}</p>
                </div>
                
                <div class="api-section">
                    <h2>API Disponible</h2>
                    <div class="endpoint">
                        <strong>GET /api/status</strong> - Statut de l'instance
                    </div>
                    <div class="endpoint">
                        <strong>POST /api/execute</strong> - Exécuter du code Python dans Blender
                    </div>
                    <div class="endpoint">
                        <strong>GET /api/scene</strong> - Informations sur la scène
                    </div>
                    <div class="endpoint">
                        <strong>GET /api/objects</strong> - Liste des objets
                    </div>
                </div>
            </body>
            </html>
            '''
            self.wfile.write(html.encode())
            
        elif self.path == "/api/status":
            self.send_json_response({{
                "instance_id": INSTANCE_ID,
                "name": "{instance.name}",
                "port": PORT,
                "status": "running",
                "blender_version": bpy.app.version_string,
                "objects_count": len(bpy.data.objects),
                "memory_usage": bpy.app.driver_namespace.get("memory_usage", 0)
            }})
            
        elif self.path == "/api/scene":
            self.send_json_response({{
                "name": bpy.context.scene.name,
                "objects": [obj.name for obj in bpy.context.scene.objects],
                "current_frame": bpy.context.scene.frame_current,
                "frame_start": bpy.context.scene.frame_start,
                "frame_end": bpy.context.scene.frame_end
            }})
            
        elif self.path == "/api/objects":
            objects_info = []
            for obj in bpy.data.objects:
                obj_data = {{
                    "name": obj.name,
                    "type": obj.type,
                    "location": list(obj.location),
                    "rotation": list(obj.rotation_euler),
                    "scale": list(obj.scale),
                    "dimensions": list(obj.dimensions),
                    "visible": obj.visible_get()
                }}
                if hasattr(obj.data, 'materials') and obj.data.materials:
                    obj_data["materials"] = [m.name for m in obj.data.materials if m]
                objects_info.append(obj_data)
            self.send_json_response(objects_info)

        elif self.path.startswith("/api/object/"):
            obj_name = urllib.parse.unquote(self.path[12:])
            obj = bpy.data.objects.get(obj_name)
            if obj:
                obj_data = {{
                    "name": obj.name,
                    "type": obj.type,
                    "location": list(obj.location),
                    "rotation_euler": list(obj.rotation_euler),
                    "scale": list(obj.scale),
                    "dimensions": list(obj.dimensions),
                    "visible": obj.visible_get(),
                    "parent": obj.parent.name if obj.parent else None,
                    "children": [c.name for c in obj.children]
                }}
                if hasattr(obj.data, 'materials') and obj.data.materials:
                    obj_data["materials"] = [m.name for m in obj.data.materials if m]
                self.send_json_response(obj_data)
            else:
                self.send_json_response({{"error": f"Object not found: {{obj_name}}"}}, 404)

        else:
            self.send_error(404, "Endpoint non trouvé")
    
    def do_POST(self):
        if self.path == "/api/execute":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                code = data.get('code', '')
                
                if not code:
                    self.send_json_response({{"error": "Aucun code fourni"}}, 400)
                    return
                
                # Exécution du code dans le contexte Blender
                result = {{"success": False, "result": None, "error": None}}
                
                try:
                    # Capture des prints et résultats
                    old_stdout = sys.stdout
                    from io import StringIO
                    sys.stdout = captured_output = StringIO()
                    
                    # Exécution sécurisée
                    exec_globals = {{
                        'bpy': bpy,
                        'bmesh': bmesh,
                        'mathutils': __import__('mathutils'),
                        '__builtins__': __builtins__
                    }}
                    
                    exec_result = exec(code, exec_globals)
                    
                    # Récupération des outputs
                    sys.stdout = old_stdout
                    output = captured_output.getvalue()
                    
                    result["success"] = True
                    result["result"] = output if output else "Code exécuté avec succès"
                    
                except Exception as e:
                    sys.stdout = old_stdout
                    result["error"] = str(e)
                
                self.send_json_response(result)
                
            except json.JSONDecodeError:
                self.send_json_response({{"error": "JSON invalide"}}, 400)
            except Exception as e:
                self.send_json_response({{"error": str(e)}}, 500)
        else:
            self.send_error(404, "Endpoint non trouvé")
    
    def send_json_response(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, format, *args):
        # Supprimer les logs HTTP pour éviter le spam
        pass

def start_server():
    server = HTTPServer(("0.0.0.0", PORT), BlenderHTTPRequestHandler)
    print(f"Serveur Blender démarré sur le port {{PORT}}")
    server.serve_forever()

# Démarrage du serveur dans un thread séparé
server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

print(f"Instance Blender {{INSTANCE_ID}} prête sur le port {{PORT}}")

# Maintenir Blender actif
import time
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Arrêt de l'instance Blender")
"""
        
        script_path = self.temp_dir / f"blender_startup_{instance.instance_id}.py"
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        return str(script_path)
    
    async def _wait_for_server_ready(self, port: int, timeout: int = 30):
        """Attendre que le serveur Blender soit prêt"""
        import httpx
        
        for _ in range(timeout):
            try:
                async with httpx.AsyncClient(timeout=1.0) as client:
                    response = await client.get(f"http://localhost:{port}/api/status")
                    if response.status_code == 200:
                        logger.info(f"Serveur Blender prêt sur le port {port}")
                        return
            except:
                pass
            await asyncio.sleep(1)
        
        raise TimeoutError(f"Le serveur Blender n'a pas démarré sur le port {port}")
    
    async def _monitor_instance(self, instance_id: str):
        """Surveiller une instance Blender"""
        while instance_id in self.instances:
            try:
                instance = self.instances[instance_id]
                process = self.processes.get(instance_id)
                
                if process and process.pid:
                    try:
                        psutil_process = psutil.Process(process.pid)
                        instance.memory_usage = psutil_process.memory_info().rss / 1024 / 1024  # MB
                        instance.cpu_usage = psutil_process.cpu_percent()
                        
                        if not psutil_process.is_running():
                            instance.status = InstanceStatus.STOPPED
                            logger.warning(f"Instance {instance_id} s'est arrêtée de manière inattendue")
                            
                    except psutil.NoSuchProcess:
                        instance.status = InstanceStatus.STOPPED
                        logger.warning(f"Processus de l'instance {instance_id} non trouvé")
                
                await asyncio.sleep(30)  # Monitoring toutes les 30 secondes
                
            except Exception as e:
                logger.error(f"Erreur lors du monitoring de l'instance {instance_id}: {e}")
                await asyncio.sleep(60)
    
    async def stop_instance(self, instance_id: str):
        """Arrêter une instance Blender"""
        if instance_id not in self.instances:
            raise ValueError(f"Instance {instance_id} non trouvée")
        
        instance = self.instances[instance_id]
        instance.status = InstanceStatus.STOPPING
        
        # Arrêt du processus
        if instance_id in self.processes:
            process = self.processes[instance_id]
            try:
                process.terminate()
                await asyncio.sleep(5)  # Attendre l'arrêt gracieux
                if process.poll() is None:
                    process.kill()  # Forcer l'arrêt si nécessaire
            except Exception as e:
                logger.error(f"Erreur lors de l'arrêt du processus: {e}")
            finally:
                del self.processes[instance_id]
        
        # Libération du port
        await self.port_manager.release_port(instance.port)
        
        # Nettoyage du script temporaire
        script_path = self.temp_dir / f"blender_startup_{instance_id}.py"
        if script_path.exists():
            script_path.unlink()
        
        # Suppression de l'instance
        del self.instances[instance_id]
        logger.info(f"Instance {instance_id} arrêtée")
    
    async def list_instances(self) -> List[BlenderInstance]:
        """Lister toutes les instances actives"""
        return list(self.instances.values())
    
    async def get_instance(self, instance_id: str) -> Optional[BlenderInstance]:
        """Obtenir une instance spécifique"""
        return self.instances.get(instance_id)
    
    async def get_instance_status(self, instance_id: str) -> Optional[InstanceStatus]:
        """Obtenir le statut d'une instance"""
        instance = self.instances.get(instance_id)
        return instance.status if instance else None
    
    async def restart_instance(self, instance_id: str):
        """Redémarrer une instance"""
        if instance_id not in self.instances:
            raise ValueError(f"Instance {instance_id} non trouvée")
        
        instance = self.instances[instance_id]
        name = instance.name
        version = instance.blender_version
        addons = instance.additional_addons
        
        # Arrêter l'instance
        await self.stop_instance(instance_id)
        
        # Recréer l'instance
        return await self.create_instance(name, version, addons)
    
    async def execute_command(self, instance_id: str, command: dict) -> CommandResponse:
        """Exécuter une commande sur une instance via API"""
        if instance_id not in self.instances:
            return CommandResponse(
                success=False,
                error="Instance non trouvée",
                execution_time=0
            )
        
        instance = self.instances[instance_id]
        start_time = asyncio.get_event_loop().time()
        
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"http://localhost:{instance.port}/api/execute",
                    json=command
                )
                
                result = response.json()
                execution_time = asyncio.get_event_loop().time() - start_time
                
                return CommandResponse(
                    success=result.get("success", False),
                    result=result.get("result"),
                    error=result.get("error"),
                    execution_time=execution_time
                )
        
        except Exception as e:
            execution_time = asyncio.get_event_loop().time() - start_time
            return CommandResponse(
                success=False,
                error=str(e),
                execution_time=execution_time
            )
    
    async def cleanup_all_instances(self):
        """Nettoyer toutes les instances au shutdown"""
        instance_ids = list(self.instances.keys())
        for instance_id in instance_ids:
            try:
                await self.stop_instance(instance_id)
            except Exception as e:
                logger.error(f"Erreur lors du nettoyage de l'instance {instance_id}: {e}")
        
        # Nettoyage du répertoire temporaire
        try:
            if self.temp_dir.exists():
                import shutil
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage du répertoire temporaire: {e}")
