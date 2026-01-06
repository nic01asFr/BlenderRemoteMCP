#!/usr/bin/env python3
"""
Blender Canvas - Multi-User Platform
Main API Gateway with MCP support, authentication, and container management
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn
import httpx
from typing import Optional
import logging

from src.container_manager import ContainerManager
from src.auth import AuthManager, UserCreate, UserLogin, TokenResponse
from src.mcp_server import mcp, initialize as init_mcp, cleanup as cleanup_mcp

# Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Managers
container_manager = ContainerManager()
auth_manager = AuthManager()
security = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager"""
    logger.info("Starting Blender Canvas Platform")
    await container_manager.initialize()
    await init_mcp(container_manager)
    logger.info("Platform ready")

    yield

    logger.info("Shutting down Blender Canvas Platform")
    await cleanup_mcp()
    await container_manager.cleanup()


app = FastAPI(
    title="Blender Canvas",
    description="Multi-user Blender platform with AI assistant integration via MCP",
    version="2.0.0",
    lifespan=lifespan
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Mount MCP server
mcp_app = mcp.http_app(path="/mcp")
app.mount("/mcp", mcp_app)


# ============================================================================
# Authentication Dependencies
# ============================================================================

async def get_current_user_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Get current user from JWT token"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = await auth_manager.verify_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user


async def get_current_user_from_api_key(
    x_api_key: Optional[str] = Header(None)
):
    """Get current user from API key (for MCP)"""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    user = await auth_manager.verify_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    x_api_key: Optional[str] = Header(None)
):
    """Get current user from either JWT token or API key"""
    # Try API key first (for MCP clients)
    if x_api_key:
        user = await auth_manager.verify_api_key(x_api_key)
        if user:
            return user

    # Try JWT token
    if credentials:
        user = await auth_manager.verify_token(credentials.credentials)
        if user:
            return user

    raise HTTPException(status_code=401, detail="Not authenticated")


# ============================================================================
# Auth Routes
# ============================================================================

@app.post("/api/auth/register", response_model=TokenResponse)
async def register(data: UserCreate):
    """Register a new user"""
    try:
        return await auth_manager.register(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(data: UserLogin):
    """Login and get access token"""
    try:
        return await auth_manager.login(data)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/api/auth/me")
async def get_me(user=Depends(get_current_user)):
    """Get current user info"""
    return {
        "user_id": user.id,
        "email": user.email,
        "created_at": user.created_at.isoformat()
    }


@app.post("/api/auth/regenerate-api-key")
async def regenerate_api_key(user=Depends(get_current_user_from_token)):
    """Regenerate API key"""
    new_key = await auth_manager.regenerate_api_key(user.id)
    return {"api_key": new_key}


# ============================================================================
# Session Routes
# ============================================================================

@app.post("/api/session/start")
async def start_session(user=Depends(get_current_user)):
    """Start a Blender session for the current user"""
    try:
        session = await container_manager.start_session(user.id)
        return session.to_dict()
    except Exception as e:
        logger.error(f"Failed to start session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/session")
async def get_session(user=Depends(get_current_user)):
    """Get current user's session"""
    session = container_manager.get_session(user.id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session")
    return session.to_dict()


@app.delete("/api/session")
async def stop_session(user=Depends(get_current_user)):
    """Stop current user's session"""
    await container_manager.stop_session(user.id)
    return {"success": True, "message": "Session stopped"}


@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions (admin only in production)"""
    return container_manager.list_sessions()


# ============================================================================
# Blender API Routes (proxy to user's container)
# ============================================================================

@app.get("/api/blender/scene")
async def get_scene(user=Depends(get_current_user)):
    """Get scene info from user's Blender instance"""
    try:
        return await container_manager.execute_on_container(
            user.id, "/api/scene"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/blender/objects")
async def list_objects(user=Depends(get_current_user)):
    """List objects in user's Blender scene"""
    try:
        return await container_manager.execute_on_container(
            user.id, "/api/objects"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/blender/object")
async def create_object(data: dict, user=Depends(get_current_user)):
    """Create object in user's Blender scene"""
    try:
        return await container_manager.execute_on_container(
            user.id, "/api/object", method="POST", data=data
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/blender/object/{name}")
async def delete_object(name: str, user=Depends(get_current_user)):
    """Delete object from user's Blender scene"""
    try:
        return await container_manager.execute_on_container(
            user.id, f"/api/object/{name}", method="DELETE"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/blender/object/{name}")
async def modify_object(name: str, data: dict, user=Depends(get_current_user)):
    """Modify object in user's Blender scene"""
    try:
        return await container_manager.execute_on_container(
            user.id, f"/api/object/{name}", method="PUT", data=data
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/blender/object/{name}/material")
async def set_material(name: str, data: dict, user=Depends(get_current_user)):
    """Set object material"""
    try:
        return await container_manager.execute_on_container(
            user.id, f"/api/object/{name}/material", method="POST", data=data
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/blender/execute")
async def execute_code(data: dict, user=Depends(get_current_user)):
    """Execute Python code in user's Blender instance"""
    try:
        return await container_manager.execute_on_container(
            user.id, "/api/execute", method="POST", data=data
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Stream Routes
# ============================================================================

@app.get("/stream/{user_id}")
async def stream_proxy(user_id: str, request: Request):
    """Proxy MJPEG stream from user's container"""
    session = container_manager.get_session(user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async def generate():
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "GET",
                f"http://localhost:{session.stream_port}/stream",
                timeout=None
            ) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/stream")
async def my_stream(user=Depends(get_current_user)):
    """Get stream for current user"""
    session = container_manager.get_session(user.id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    async def generate():
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "GET",
                f"http://localhost:{session.stream_port}/stream",
                timeout=None
            ) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# ============================================================================
# Frontend Routes
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page"""
    return templates.TemplateResponse("canvas.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("login.html", {"request": request})


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main_multiuser:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
