"""
Modèles de données pour le service Blender Web
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class InstanceStatus(str, Enum):
    """États possibles d'une instance Blender"""
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"

class BlenderInstance(BaseModel):
    """Modèle d'une instance Blender"""
    instance_id: str = Field(..., description="Identifiant unique de l'instance")
    name: str = Field(..., description="Nom de l'instance")
    port: int = Field(..., description="Port d'écoute de l'instance")
    status: InstanceStatus = Field(..., description="Statut de l'instance")
    blender_version: str = Field(default="3.6", description="Version de Blender")
    created_at: datetime = Field(default_factory=datetime.now, description="Date de création")
    last_accessed: Optional[datetime] = Field(None, description="Dernier accès")
    process_id: Optional[int] = Field(None, description="PID du processus Blender")
    memory_usage: Optional[float] = Field(None, description="Utilisation mémoire en MB")
    cpu_usage: Optional[float] = Field(None, description="Utilisation CPU en %")
    additional_addons: List[str] = Field(default_factory=list, description="Addons supplémentaires")
    config: Dict[str, Any] = Field(default_factory=dict, description="Configuration spécifique")

class InstanceRequest(BaseModel):
    """Requête pour créer une nouvelle instance"""
    name: str = Field(..., description="Nom de l'instance", min_length=1, max_length=50)
    blender_version: str = Field(default="3.6", description="Version de Blender")
    additional_addons: List[str] = Field(default_factory=list, description="Addons à installer")
    config: Dict[str, Any] = Field(default_factory=dict, description="Configuration personnalisée")

class InstanceResponse(BaseModel):
    """Réponse après création d'instance"""
    success: bool = Field(..., description="Succès de l'opération")
    message: str = Field(..., description="Message de retour")
    instance: Optional[BlenderInstance] = Field(None, description="Instance créée")
    error: Optional[str] = Field(None, description="Détails de l'erreur")

class CommandRequest(BaseModel):
    """Requête pour exécuter une commande via MCP"""
    command: str = Field(..., description="Commande à exécuter")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Paramètres de la commande")
    timeout: int = Field(default=30, description="Timeout en secondes")

class CommandResponse(BaseModel):
    """Réponse d'exécution de commande"""
    success: bool = Field(..., description="Succès de l'exécution")
    result: Any = Field(None, description="Résultat de la commande")
    error: Optional[str] = Field(None, description="Erreur rencontrée")
    execution_time: float = Field(..., description="Temps d'exécution en secondes")

class SystemStatus(BaseModel):
    """Statut général du système"""
    total_instances: int = Field(..., description="Nombre total d'instances")
    running_instances: int = Field(..., description="Instances en cours d'exécution")
    available_ports: List[int] = Field(..., description="Ports disponibles")
    system_memory_usage: float = Field(..., description="Utilisation mémoire système")
    system_cpu_usage: float = Field(..., description="Utilisation CPU système")
    uptime: float = Field(..., description="Temps de fonctionnement en secondes")
