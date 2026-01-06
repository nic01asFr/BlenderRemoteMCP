"""
Gestionnaire de proxy pour router les requêtes vers les instances Blender
"""

import asyncio
import httpx
import logging
from fastapi import Request, Response, HTTPException
from fastapi.responses import StreamingResponse
import websockets
from typing import Optional

logger = logging.getLogger(__name__)

class ProxyManager:
    """Gestionnaire de proxy pour les instances Blender"""
    
    def __init__(self):
        self.instances_cache = {}
        self.http_client = None
    
    async def initialize(self):
        """Initialisation du gestionnaire de proxy"""
        logger.info("Initialisation du gestionnaire de proxy")
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
    
    async def cleanup(self):
        """Nettoyage lors de l'arrêt"""
        if self.http_client:
            await self.http_client.aclose()
    
    async def proxy_request(self, instance_id: str, path: str, request: Request):
        """Proxy une requête HTTP vers une instance Blender"""
        from main import blender_manager  # Import local pour éviter les dépendances circulaires
        
        # Récupérer l'instance
        instance = await blender_manager.get_instance(instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance non trouvée")
        
        if instance.status.value != "running":
            raise HTTPException(status_code=503, detail="Instance non disponible")
        
        # Construire l'URL de destination
        target_url = f"http://localhost:{instance.port}/{path.lstrip('/')}"
        
        try:
            # Récupérer les headers de la requête originale
            headers = dict(request.headers)
            # Supprimer les headers problématiques
            headers.pop('host', None)
            headers.pop('content-length', None)
            
            # Proxy selon la méthode HTTP
            if request.method == "GET":
                response = await self.http_client.get(
                    target_url,
                    headers=headers,
                    params=request.query_params
                )
            elif request.method == "POST":
                body = await request.body()
                response = await self.http_client.post(
                    target_url,
                    headers=headers,
                    content=body,
                    params=request.query_params
                )
            elif request.method == "PUT":
                body = await request.body()
                response = await self.http_client.put(
                    target_url,
                    headers=headers,
                    content=body,
                    params=request.query_params
                )
            elif request.method == "DELETE":
                response = await self.http_client.delete(
                    target_url,
                    headers=headers,
                    params=request.query_params
                )
            else:
                raise HTTPException(status_code=405, detail="Méthode non supportée")
            
            # Mettre à jour l'heure du dernier accès
            from datetime import datetime
            instance.last_accessed = datetime.now()
            
            # Préparer les headers de réponse
            response_headers = dict(response.headers)
            response_headers.pop('content-length', None)
            response_headers.pop('transfer-encoding', None)
            
            # Retourner la réponse
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers,
                media_type=response.headers.get('content-type')
            )
            
        except httpx.RequestError as e:
            logger.error(f"Erreur lors du proxy vers {target_url}: {e}")
            raise HTTPException(status_code=502, detail="Erreur de proxy")
        except httpx.TimeoutException:
            logger.error(f"Timeout lors du proxy vers {target_url}")
            raise HTTPException(status_code=504, detail="Timeout de proxy")
    
    async def proxy_websocket(self, instance_id: str, websocket):
        """Proxy une connexion WebSocket vers une instance Blender"""
        from main import blender_manager
        
        # Récupérer l'instance
        instance = await blender_manager.get_instance(instance_id)
        if not instance:
            await websocket.close(code=1000, reason="Instance non trouvée")
            return
        
        if instance.status.value != "running":
            await websocket.close(code=1000, reason="Instance non disponible")
            return
        
        # URL WebSocket de destination
        target_ws_url = f"ws://localhost:{instance.port}/ws"
        
        try:
            # Accepter la connexion WebSocket côté client
            await websocket.accept()
            
            # Établir la connexion vers l'instance Blender
            async with websockets.connect(target_ws_url) as blender_ws:
                # Créer des tâches pour transférer les messages dans les deux sens
                async def forward_to_blender():
                    try:
                        while True:
                            message = await websocket.receive()
                            if message["type"] == "websocket.receive":
                                if "text" in message:
                                    await blender_ws.send(message["text"])
                                elif "bytes" in message:
                                    await blender_ws.send(message["bytes"])
                    except Exception as e:
                        logger.error(f"Erreur transfer client->blender: {e}")
                
                async def forward_to_client():
                    try:
                        async for message in blender_ws:
                            await websocket.send_text(message)
                    except Exception as e:
                        logger.error(f"Erreur transfer blender->client: {e}")
                
                # Lancer les tâches de transfert
                await asyncio.gather(
                    forward_to_blender(),
                    forward_to_client(),
                    return_exceptions=True
                )
                
        except websockets.exceptions.WebSocketException as e:
            logger.error(f"Erreur WebSocket vers l'instance {instance_id}: {e}")
        except Exception as e:
            logger.error(f"Erreur générale lors du proxy WebSocket: {e}")
        finally:
            try:
                await websocket.close()
            except:
                pass
    
    async def health_check_instance(self, instance_id: str) -> bool:
        """Vérifier la santé d'une instance via une requête HTTP"""
        from main import blender_manager
        
        instance = await blender_manager.get_instance(instance_id)
        if not instance:
            return False
        
        try:
            response = await self.http_client.get(
                f"http://localhost:{instance.port}/api/status",
                timeout=5.0
            )
            return response.status_code == 200
        except:
            return False
    
    async def get_instance_info(self, instance_id: str) -> Optional[dict]:
        """Récupérer les informations d'une instance via l'API"""
        from main import blender_manager
        
        instance = await blender_manager.get_instance(instance_id)
        if not instance:
            return None
        
        try:
            response = await self.http_client.get(
                f"http://localhost:{instance.port}/api/status",
                timeout=5.0
            )
            if response.status_code == 200:
                return response.json()
        except:
            pass
        
        return None
