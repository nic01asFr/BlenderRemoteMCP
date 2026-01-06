"""
Gestionnaire de ports pour les instances Blender
S'assure qu'aucun conflit de port n'arrive
"""

import asyncio
import socket
import logging
from typing import Optional, Set, List
import psutil

logger = logging.getLogger(__name__)

class PortManager:
    """Gestionnaire des ports pour les instances"""
    
    def __init__(self, base_port: int = 8080, max_instances: int = 10):
        self.base_port = base_port
        self.max_instances = max_instances
        self.allocated_ports: Set[int] = set()
        self.available_ports: List[int] = []
    
    async def initialize(self):
        """Initialisation du gestionnaire de ports"""
        logger.info("Initialisation du gestionnaire de ports")
        
        # Génération de la liste des ports disponibles
        for i in range(self.max_instances):
            port = self.base_port + i
            if await self._is_port_available(port):
                self.available_ports.append(port)
        
        logger.info(f"Ports disponibles: {self.available_ports}")
    
    async def _is_port_available(self, port: int) -> bool:
        """Vérifier si un port est disponible"""
        try:
            # Vérification avec socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            
            if result == 0:  # Port occupé
                return False
            
            # Vérification avec psutil pour plus de sécurité
            connections = psutil.net_connections()
            for conn in connections:
                if conn.laddr and conn.laddr.port == port:
                    return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Erreur lors de la vérification du port {port}: {e}")
            return False
    
    async def allocate_port(self) -> Optional[int]:
        """Allouer un port disponible"""
        # Recherche dans les ports disponibles
        for port in self.available_ports:
            if port not in self.allocated_ports:
                # Double vérification de disponibilité
                if await self._is_port_available(port):
                    self.allocated_ports.add(port)
                    logger.info(f"Port {port} alloué")
                    return port
                else:
                    # Port plus disponible, le retirer de la liste
                    self.available_ports.remove(port)
        
        # Aucun port disponible
        logger.warning("Aucun port disponible pour une nouvelle instance")
        return None
    
    async def release_port(self, port: int):
        """Libérer un port"""
        if port in self.allocated_ports:
            self.allocated_ports.remove(port)
            
            # Remettre le port dans les disponibles s'il n'y est pas déjà
            if port not in self.available_ports:
                self.available_ports.append(port)
                self.available_ports.sort()  # Maintenir l'ordre
            
            logger.info(f"Port {port} libéré")
    
    def get_allocated_ports(self) -> List[int]:
        """Obtenir la liste des ports alloués"""
        return sorted(list(self.allocated_ports))
    
    def get_available_ports(self) -> List[int]:
        """Obtenir la liste des ports disponibles"""
        return [port for port in self.available_ports if port not in self.allocated_ports]
    
    async def refresh_available_ports(self):
        """Rafraîchir la liste des ports disponibles"""
        logger.info("Rafraîchissement des ports disponibles")
        
        # Réévaluer tous les ports possibles
        new_available = []
        for i in range(self.max_instances):
            port = self.base_port + i
            if await self._is_port_available(port):
                new_available.append(port)
        
        self.available_ports = new_available
        
        # Nettoyer les allocations de ports qui ne sont plus valides
        invalid_allocations = []
        for port in self.allocated_ports:
            if not await self._is_port_available(port):
                # Port plus utilisé par nos instances
                continue
            if port not in self.available_ports:
                invalid_allocations.append(port)
        
        for port in invalid_allocations:
            self.allocated_ports.remove(port)
        
        logger.info(f"Ports disponibles après rafraîchissement: {self.available_ports}")
