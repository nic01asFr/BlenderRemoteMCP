# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Blender MCP Server** - A cloud Blender service accessible via Model Context Protocol (MCP). Users connect their AI assistant (Claude Desktop, etc.) to get their own isolated Blender instance. No local Blender installation required.

## Quick Start

```bash
# Option 1: Docker (recommended)
docker build -t blender-canvas:latest docker/blender-canvas/
docker-compose up -d

# Option 2: Local development
pip install -r requirements.txt
python main_mcp.py
```

Server runs at http://localhost:8000

## Architecture

```
┌─────────────────┐          ┌─────────────────────────────────┐
│ Claude Desktop  │──────────│     Blender MCP Server          │
│   (MCP Client)  │  Bearer  │     (port 8000)                 │
└─────────────────┘  Token   │                                 │
        │                    │  /mcp ─── MCP JSON-RPC Handler  │
        └────────────────────│  /api ─── Auth endpoints        │
                             │  /stream ─ MJPEG video          │
                             └───────────────┬─────────────────┘
                                             │
                             ┌───────────────┼───────────────┐
                             ▼               ▼               ▼
                       ┌──────────┐   ┌──────────┐   ┌──────────┐
                       │ Blender  │   │ Blender  │   │ Blender  │
                       │ User A   │   │ User B   │   │ User C   │
                       └──────────┘   └──────────┘   └──────────┘
```

### Core Components

**main_mcp.py** - Main entry point. Implements:
- MCP JSON-RPC protocol handler at `/mcp`
- Authentication via Bearer token in Authorization header
- User registration/login at `/api/auth/*`
- MJPEG stream proxy at `/stream/{user_id}`
- Blender tool implementations (create_object, modify_object, etc.)

**src/container_manager.py** - Docker container orchestration:
- One container per user (isolated Blender instances)
- Auto-start on first MCP tool call
- Auto-cleanup after 30 minutes of inactivity
- Health checking and port allocation

**src/auth.py** - Authentication:
- User registration with email/password
- API key generation (format: `blender_xxx...`)
- JWT tokens for web UI
- In-memory storage (use PostgreSQL for production)

**docker/blender-canvas/** - Blender container:
- `Dockerfile` - Ubuntu + Blender 4.0 + Xvfb + FFmpeg
- `api_server.py` - REST API for Blender control (port 8080)
- `stream_server.py` - MJPEG streaming (port 8081)
- `blender_addon.py` - Python addon running inside Blender

## MCP Integration

### Claude Desktop Configuration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "blender": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

Get your API key by registering:
```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "yourpassword"}'
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `list_objects` | List all objects in the scene |
| `create_object` | Create 3D object (CUBE, SPHERE, CYLINDER, CONE, TORUS, PLANE, MONKEY) |
| `modify_object` | Change position, rotation, scale |
| `set_color` | Set object color (RGBA) |
| `delete_object` | Remove an object |
| `clear_scene` | Clear all objects (keep camera/lights) |
| `execute_python` | Run custom Blender Python code |
| `save_project` | Save scene to file |
| `load_project` | Load saved project |
| `get_scene_info` | Get scene information |

### MCP Resources

| URI | Description |
|-----|-------------|
| `blender://scene` | Current scene state (objects list) |
| `blender://projects` | Saved projects list |

## Key Features

- **Auto-start**: Blender container starts on first MCP command
- **Auto-save**: Projects saved every 5 minutes
- **Auto-cleanup**: Containers stop after 30 min inactivity
- **Isolation**: Each user gets their own Docker container
- **Live stream**: View Blender viewport via MJPEG stream

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register, returns API key
- `POST /api/auth/login` - Login, returns API key

### MCP
- `GET /mcp` - Server info
- `POST /mcp` - MCP JSON-RPC requests (requires Bearer token)

### Streaming
- `GET /stream/{user_id}` - MJPEG video stream

### Health
- `GET /health` - Service health check

## Development

### Run locally
```bash
# Build Blender image first
docker build -t blender-canvas:latest docker/blender-canvas/

# Run server
python main_mcp.py
```

### Run with Docker Compose
```bash
docker-compose up -d
docker-compose logs -f mcp
```

### Hot-Reload (Apply Changes on Restart)

**MCP Server changes** (`main_mcp.py`, `src/*`):
```bash
# Files are mounted as volumes - just restart
docker-compose restart mcp
```

**Blender container changes** (`docker/blender-canvas/*`):
```bash
# Rebuild the image
docker-compose build blender-base

# Stop existing user containers (new ones will use updated image)
docker stop $(docker ps -q --filter "name=blender-user")
```

### Screenshot Feature

The `get_screenshot` tool captures the Blender viewport and returns it as an MCP image content block that Claude can see directly.

- **Render Engine**: Workbench (no GPU required, works in headless/Xvfb)
- **Format**: PNG encoded as base64 in MCP `image` content type
- **Auto-camera**: Creates temporary camera if scene has none

### Test MCP endpoint
```bash
# Initialize
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{},"id":1}'

# List tools
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":2}'

# Create object
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"create_object","arguments":{"type":"CUBE","color":[1,0,0,1]}},"id":3}'
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 8000 | Server port |
| `JWT_SECRET` | (random) | JWT signing key |
| `LOG_LEVEL` | info | Logging level |

## File Structure

```
├── main_mcp.py              # Main entry point (MCP server)
├── docker-compose.yml       # Docker Compose config
├── requirements.txt         # Python dependencies
├── QUICKSTART.md            # User quick start guide
├── src/
│   ├── auth.py              # Authentication
│   ├── container_manager.py # Docker management
│   └── ...
├── docker/
│   ├── api/Dockerfile       # API server image
│   └── blender-canvas/      # Blender container
│       ├── Dockerfile
│       ├── api_server.py
│       ├── stream_server.py
│       └── blender_addon.py
└── templates/
    └── canvas.html          # Web UI
```
