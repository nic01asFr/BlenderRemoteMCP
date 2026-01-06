"""
Container Manager
Manages Docker containers for user Blender sessions
"""

import docker
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta
import uuid

logger = logging.getLogger(__name__)


class UserSession:
    """Represents a user's Blender session"""

    def __init__(
        self,
        user_id: str,
        container_id: str,
        api_port: int,
        stream_port: int,
        novnc_port: int
    ):
        self.user_id = user_id
        self.session_id = str(uuid.uuid4())
        self.container_id = container_id
        self.api_port = api_port
        self.stream_port = stream_port
        self.novnc_port = novnc_port
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.status = "starting"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "container_id": self.container_id,
            "api_port": self.api_port,
            "stream_port": self.stream_port,
            "novnc_port": self.novnc_port,
            "api_url": f"http://localhost:{self.api_port}",
            "stream_url": f"http://localhost:{self.stream_port}/stream",
            "novnc_url": f"http://localhost:{self.novnc_port}/vnc.html",
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "status": self.status
        }


class ContainerManager:
    """Manages Docker containers for Blender sessions"""

    def __init__(
        self,
        image_name: str = "blender-canvas:latest",
        network_name: str = "blender-net",
        base_api_port: int = 9000,
        base_stream_port: int = 9100,
        base_novnc_port: int = 9200,
        max_containers: int = 50,
        idle_timeout_minutes: int = 30
    ):
        self.image_name = image_name
        self.network_name = network_name
        self.base_api_port = base_api_port
        self.base_stream_port = base_stream_port
        self.base_novnc_port = base_novnc_port
        self.max_containers = max_containers
        self.idle_timeout = timedelta(minutes=idle_timeout_minutes)

        # Use host.docker.internal when running in Docker, localhost otherwise
        self.host_address = self._detect_host_address()

        self.docker_client: Optional[docker.DockerClient] = None
        self.sessions: Dict[str, UserSession] = {}  # user_id -> session
        self.port_allocator = set()
        self._cleanup_task = None

    def _detect_host_address(self) -> str:
        """Detect if running in Docker and return appropriate host address"""
        import os
        # Check if running in Docker (/.dockerenv exists)
        if os.path.exists("/.dockerenv"):
            logger.info("Running in Docker, using host.docker.internal")
            return "host.docker.internal"
        return "localhost"

    async def initialize(self):
        """Initialize Docker client and network"""
        try:
            self.docker_client = docker.from_env()
            logger.info("Docker client initialized")

            # Ensure network exists
            try:
                self.docker_client.networks.get(self.network_name)
            except docker.errors.NotFound:
                self.docker_client.networks.create(
                    self.network_name,
                    driver="bridge"
                )
                logger.info(f"Created network: {self.network_name}")

            # Clean up any stale user containers from previous runs
            # This ensures new containers use the latest image
            await self._cleanup_stale_containers()

            # Start cleanup task
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        except Exception as e:
            logger.error(f"Failed to initialize Docker: {e}")
            raise

    async def cleanup(self):
        """Cleanup all containers and resources"""
        if self._cleanup_task:
            self._cleanup_task.cancel()

        # Stop all user containers
        for user_id in list(self.sessions.keys()):
            await self.stop_session(user_id)

        logger.info("All containers cleaned up")

    async def _cleanup_stale_containers(self):
        """Stop and remove any blender-user containers from previous runs.
        This ensures new containers use the latest blender-canvas image."""
        try:
            containers = self.docker_client.containers.list(
                all=True,
                filters={"name": "blender-user"}
            )
            for container in containers:
                logger.info(f"Cleaning up stale container: {container.name}")
                try:
                    container.stop(timeout=5)
                except Exception:
                    pass
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            if containers:
                logger.info(f"Cleaned up {len(containers)} stale container(s)")
        except Exception as e:
            logger.warning(f"Error cleaning up stale containers: {e}")

    def _allocate_ports(self) -> tuple:
        """Allocate API, stream, and noVNC ports for a new container"""
        for i in range(self.max_containers):
            api_port = self.base_api_port + i
            stream_port = self.base_stream_port + i
            novnc_port = self.base_novnc_port + i

            if api_port not in self.port_allocator:
                self.port_allocator.add(api_port)
                self.port_allocator.add(stream_port)
                self.port_allocator.add(novnc_port)
                return api_port, stream_port, novnc_port

        raise Exception("No available ports")

    def _release_ports(self, api_port: int, stream_port: int, novnc_port: int):
        """Release allocated ports"""
        self.port_allocator.discard(api_port)
        self.port_allocator.discard(stream_port)
        self.port_allocator.discard(novnc_port)

    async def start_session(self, user_id: str) -> UserSession:
        """Start a new Blender session for a user"""

        # Check if user already has a session
        if user_id in self.sessions:
            session = self.sessions[user_id]
            session.last_activity = datetime.now()
            return session

        # Check container limit
        if len(self.sessions) >= self.max_containers:
            raise Exception("Maximum container limit reached")

        # Allocate ports
        api_port, stream_port, novnc_port = self._allocate_ports()

        try:
            # Create container
            container = self.docker_client.containers.run(
                self.image_name,
                detach=True,
                name=f"blender-user-{user_id[:8]}",
                ports={
                    "8080/tcp": api_port,
                    "8081/tcp": stream_port,
                    "6080/tcp": novnc_port
                },
                network=self.network_name,
                environment={
                    "USER_ID": user_id
                },
                volumes={
                    f"blender-projects-{user_id[:8]}": {
                        "bind": "/projects",
                        "mode": "rw"
                    }
                },
                mem_limit="4g",
                cpu_period=100000,
                cpu_quota=200000,  # 2 CPUs max
                remove=True
            )

            session = UserSession(
                user_id=user_id,
                container_id=container.id,
                api_port=api_port,
                stream_port=stream_port,
                novnc_port=novnc_port
            )

            self.sessions[user_id] = session
            logger.info(f"Started session for user {user_id}: {session.session_id}")

            # Wait for container to be healthy
            asyncio.create_task(self._wait_for_healthy(session))

            return session

        except Exception as e:
            self._release_ports(api_port, stream_port, novnc_port)
            logger.error(f"Failed to start container: {e}")
            raise

    async def _wait_for_healthy(self, session: UserSession):
        """Wait for container to become healthy"""
        import httpx

        for i in range(120):  # 120 second timeout (Blender takes time to start)
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"http://{self.host_address}:{session.api_port}/health",
                        timeout=2.0
                    )
                    if response.status_code == 200:
                        session.status = "ready"
                        logger.info(f"Session {session.session_id} is ready")
                        return
            except Exception:
                pass

            await asyncio.sleep(1)

        session.status = "unhealthy"
        logger.warning(f"Session {session.session_id} failed health check")

    async def _check_and_update_health(self, session: UserSession) -> bool:
        """Check container health and update session status"""
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"http://{self.host_address}:{session.api_port}/health",
                    timeout=2.0
                )
                if response.status_code == 200:
                    if session.status != "ready":
                        session.status = "ready"
                        logger.info(f"Session {session.session_id} is now ready")
                    return True
        except Exception:
            pass
        return False

    async def stop_session(self, user_id: str):
        """Stop a user's Blender session"""
        if user_id not in self.sessions:
            return

        session = self.sessions[user_id]

        try:
            container = self.docker_client.containers.get(session.container_id)
            container.stop(timeout=10)
            logger.info(f"Stopped session {session.session_id}")
        except docker.errors.NotFound:
            pass
        except Exception as e:
            logger.error(f"Error stopping container: {e}")

        self._release_ports(session.api_port, session.stream_port, session.novnc_port)
        del self.sessions[user_id]

    def get_session(self, user_id: str) -> Optional[UserSession]:
        """Get a user's current session, validating container exists"""
        session = self.sessions.get(user_id)
        if session:
            # Verify container actually exists
            try:
                container = self.docker_client.containers.get(session.container_id)
                if container.status not in ("running", "created"):
                    # Container exists but not running
                    logger.warning(f"Container for user {user_id[:8]} not running, cleaning up")
                    self._release_ports(session.api_port, session.stream_port, session.novnc_port)
                    del self.sessions[user_id]
                    return None
            except docker.errors.NotFound:
                # Container was deleted externally
                logger.warning(f"Container for user {user_id[:8]} not found, cleaning up stale session")
                self._release_ports(session.api_port, session.stream_port, session.novnc_port)
                del self.sessions[user_id]
                return None
            except Exception as e:
                logger.error(f"Error checking container: {e}")
                # Keep session, may be transient error

            session.last_activity = datetime.now()
        return session

    def list_sessions(self) -> list:
        """List all active sessions"""
        return [s.to_dict() for s in self.sessions.values()]

    async def _cleanup_loop(self):
        """Background task to cleanup idle containers"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute

                now = datetime.now()
                idle_users = []

                for user_id, session in self.sessions.items():
                    if now - session.last_activity > self.idle_timeout:
                        idle_users.append(user_id)

                for user_id in idle_users:
                    logger.info(f"Stopping idle session for user {user_id}")
                    await self.stop_session(user_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    async def execute_on_container(
        self,
        user_id: str,
        endpoint: str,
        method: str = "GET",
        data: dict = None
    ) -> dict:
        """Execute an API call on a user's container"""
        import httpx

        session = self.get_session(user_id)
        if not session:
            raise Exception("No active session")

        # If session not ready, check again - container may have become healthy
        if session.status != "ready":
            if not await self._check_and_update_health(session):
                raise Exception("Session not ready")

        url = f"http://{self.host_address}:{session.api_port}{endpoint}"

        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(url, timeout=30.0)
            elif method == "POST":
                response = await client.post(url, json=data, timeout=30.0)
            elif method == "PUT":
                response = await client.put(url, json=data, timeout=30.0)
            elif method == "DELETE":
                response = await client.delete(url, timeout=30.0)
            else:
                raise Exception(f"Unknown method: {method}")

            # Handle HTTP errors
            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("detail", error_data.get("error", str(response.status_code)))
                except Exception:
                    error_msg = f"HTTP {response.status_code}"
                raise Exception(f"Blender API error: {error_msg}")

            return response.json()
