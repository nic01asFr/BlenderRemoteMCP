# Blender MCP Server - Quick Start Guide

Cloud Blender access via MCP protocol. Users connect their AI assistant (Claude Desktop, etc.) and get their own isolated Blender instance.

## Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)
- An MCP-compatible client (Claude Desktop, etc.)

## Quick Start

### Option 1: Docker (Recommended)

```bash
# 1. Build the Blender container image
docker build -t blender-canvas:latest docker/blender-canvas/

# 2. Start the MCP server
docker-compose up -d

# 3. Check logs
docker-compose logs -f api
```

The server will be available at:
- **API**: http://localhost:8000
- **MCP endpoint**: http://localhost:8000/mcp
- **Web UI**: http://localhost:8000

### Option 2: Local Development

```bash
# 1. Build the Blender container image first
docker build -t blender-canvas:latest docker/blender-canvas/

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Run the server
python main_mcp.py
```

## User Registration

Before using the MCP endpoint, register a user account:

```bash
# Register
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "your-password"}'

# Response:
# {
#   "access_token": "eyJ...",
#   "api_key": "blender_abc123...",
#   "user_id": "..."
# }
```

Save the `api_key` - you'll need it for Claude Desktop configuration.

## Configure Claude Desktop

Add to your Claude Desktop configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "blender": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY_HERE"
      }
    }
  }
}
```

Replace `YOUR_API_KEY_HERE` with your actual API key.

### Config file locations:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

## Test It

Restart Claude Desktop, then try asking:

> "Create a red cube in Blender"

Claude will:
1. Auto-start your Blender container (first use takes ~30 seconds)
2. Create the cube
3. Apply the red color

## View Your Canvas

Open http://localhost:8000 and login with your credentials to see the live MJPEG stream of your Blender viewport.

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `list_objects` | List all objects in the scene |
| `create_object` | Create a 3D object (CUBE, SPHERE, CYLINDER, etc.) |
| `modify_object` | Change position, rotation, or scale |
| `set_color` | Set an object's color |
| `delete_object` | Remove an object |
| `clear_scene` | Clear all objects (keep camera/lights) |
| `execute_python` | Run custom Blender Python code |
| `save_project` | Save current scene |
| `load_project` | Load a saved project |
| `get_scene_info` | Get scene information |

## Example Prompts

Try these with Claude:

- "Create a scene with a table and two chairs"
- "Make a pyramid of cubes"
- "Create a sphere and make it blue"
- "List all objects in my scene"
- "Delete everything except the camera"
- "Save this as 'my-project'"

## Architecture

```
┌─────────────────┐          ┌─────────────────────────────────┐
│ Claude Desktop  │          │     Blender MCP Server          │
│   (MCP Client)  │──────────│     (port 8000)                 │
└─────────────────┘          │                                 │
        │                    │  /mcp ─── MCP Protocol Handler  │
        │ Authorization:     │  /api ─── Auth & REST endpoints │
        │ Bearer API_KEY     │  /stream ─ MJPEG video stream   │
        │                    └───────────────┬─────────────────┘
        │                                    │
        │                    ┌───────────────┼───────────────┐
        │                    │               │               │
        │                    ▼               ▼               ▼
        │              ┌──────────┐   ┌──────────┐   ┌──────────┐
        └──────────────│ Blender  │   │ Blender  │   │ Blender  │
                       │ User A   │   │ User B   │   │ User C   │
                       └──────────┘   └──────────┘   └──────────┘
```

- Each user gets an isolated Docker container
- Containers auto-start on first MCP command
- Auto-save every 5 minutes
- Auto-cleanup after 30 minutes of inactivity

## Network Access

To allow access from other machines on your network:

1. Find your machine's IP: `ipconfig` (Windows) or `ifconfig` (Mac/Linux)
2. Configure Claude Desktop on other machines with:

```json
{
  "mcpServers": {
    "blender": {
      "url": "http://YOUR_IP:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

## Troubleshooting

### Container won't start
```bash
# Check Docker is running
docker ps

# Check blender-canvas image exists
docker images | grep blender-canvas

# Rebuild if needed
docker build -t blender-canvas:latest docker/blender-canvas/
```

### API not responding
```bash
# Check logs
docker-compose logs api

# Or for local dev
python main_mcp.py
```

### MCP connection fails
1. Verify API key is correct
2. Check Authorization header format: `Bearer YOUR_API_KEY` (with space)
3. Restart Claude Desktop after config changes

## Development

### Project Structure

```
├── main_mcp.py              # Main entry point
├── docker-compose.yml       # Docker Compose config
├── requirements.txt         # Python dependencies
├── src/
│   ├── auth.py              # User authentication
│   ├── container_manager.py # Docker container management
│   └── ...
├── docker/
│   ├── api/                 # API server Dockerfile
│   └── blender-canvas/      # Blender container
│       ├── Dockerfile
│       ├── api_server.py    # REST API inside container
│       ├── stream_server.py # MJPEG streaming
│       └── blender_addon.py # Blender Python addon
└── templates/
    └── canvas.html          # Web UI
```

### Local Development

```bash
# Run with auto-reload
python main_mcp.py

# Or with uvicorn directly
uvicorn main_mcp:app --reload --host 0.0.0.0 --port 8000
```
