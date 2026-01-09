# BigBlender

**Cloud Blender for AI Assistants** - Give your AI the power to create 3D content.

BigBlender is a Model Context Protocol (MCP) server that provides AI assistants with their own isolated Blender instance in the cloud. No local installation required. Just connect and create.

## Why BigBlender?

- **Zero Setup**: No Blender installation needed. Your AI gets instant access to a full Blender environment.
- **Isolated Sessions**: Each user gets their own dedicated Blender container. Your projects stay private.
- **Live Canvas**: Watch your AI work in real-time through an interactive browser canvas.
- **Full Control**: Create, modify, animate - all through natural language with your AI assistant.

## Quick Start

### 1. Start the Server

```bash
# Clone the repository
git clone https://github.com/nic01asFr/BigBlenderMCP.git
cd BigBlenderMCP

# Build and start
docker-compose up -d --build
```

### 2. Get Your API Key

```bash
curl -X POST http://localhost:8100/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "yourpassword"}'
```

### 3. Connect Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "blender": {
      "url": "http://localhost:8100/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

### 4. Start Creating

Ask Claude to create 3D scenes:

> "Create a red cube and place a blue sphere next to it"

> "Build a simple house with a pyramid roof"

> "Make a solar system with the sun and planets"

## Features

### MCP Tools

| Tool | Description |
|------|-------------|
| `create_object` | Create 3D primitives (cube, sphere, cylinder, cone, torus, plane, monkey) |
| `modify_object` | Change position, rotation, scale of any object |
| `set_color` | Apply colors to objects |
| `delete_object` | Remove objects from scene |
| `clear_scene` | Start fresh (keeps camera and lights) |
| `execute_python` | Run custom Blender Python scripts |
| `get_screenshot` | Capture viewport for AI to see the scene |
| `save_project` | Save your work |
| `load_project` | Resume previous projects |
| `list_objects` | See what's in the scene |

### Live Canvas

View and interact with Blender directly in your browser:

```
http://localhost:8100/canvas?token=YOUR_API_KEY
```

**Controls:**
- **Orbit**: Middle mouse button (or Alt + Left click)
- **Pan**: Shift + Middle mouse button
- **Zoom**: Scroll wheel
- **Select**: Left click
- **All Blender shortcuts**: Work natively in fullscreen mode

### Auto-Management

- **Auto-start**: Your Blender container spins up on first command
- **Auto-save**: Projects saved every 5 minutes
- **Auto-cleanup**: Inactive containers stop after 30 minutes (saves resources)

## Architecture

```
┌─────────────────┐         ┌──────────────────────────────────┐
│  Claude Desktop │─────────│       BigBlender Server          │
│  or any MCP     │ Bearer  │       (port 8100)                │
│  compatible AI  │ Token   │                                  │
└─────────────────┘         │  /mcp ──── MCP Protocol Handler  │
        │                   │  /canvas ─ Interactive Viewport  │
        └───────────────────│  /api ──── Authentication        │
                            └──────────────┬───────────────────┘
                                           │ Docker API
                            ┌──────────────┼──────────────┐
                            ▼              ▼              ▼
                      ┌──────────┐  ┌──────────┐  ┌──────────┐
                      │ Blender  │  │ Blender  │  │ Blender  │
                      │ User A   │  │ User B   │  │ User C   │
                      │ Container│  │ Container│  │ Container│
                      └──────────┘  └──────────┘  └──────────┘
```

Each user container includes:
- **Blender 4.0** with full Python API
- **Virtual display** (Xvfb) for headless rendering
- **VNC server** for live viewport streaming
- **REST API** for Blender control

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mcp` | POST | MCP JSON-RPC requests |
| `/canvas` | GET | Interactive Blender canvas (browser) |
| `/api/auth/register` | POST | Create account, get API key |
| `/api/auth/login` | POST | Login, get API key |
| `/health` | GET | Server health check |
| `/docs` | GET | OpenAPI documentation |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 8000 | Internal server port |
| `JWT_SECRET` | auto-generated | Token signing secret |
| `LOG_LEVEL` | info | Logging verbosity |

## Development

### Project Structure

```
BigBlenderMCP/
├── main_mcp.py              # MCP server & API endpoints
├── docker-compose.yml       # Container orchestration
├── src/
│   ├── auth.py              # Authentication system
│   └── container_manager.py # Docker container lifecycle
├── docker/
│   └── blender-canvas/      # Blender container image
│       ├── Dockerfile
│       ├── api_server.py    # Blender REST API
│       ├── stream_server.py # MJPEG streaming
│       └── blender_addon.py # Blender Python addon
├── templates/
│   └── blender_canvas.html  # Interactive canvas page
└── static/
    └── novnc/               # VNC client library
```

### Hot Reload

**Server changes** (`main_mcp.py`, `src/*`):
```bash
docker-compose restart mcp
```

**Blender container changes** (`docker/blender-canvas/*`):
```bash
docker-compose build blender-base
# New user containers will use the updated image
```

## Requirements

- Docker & Docker Compose
- 4GB+ RAM recommended
- Port 8100 available

## License

MIT License - See [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome! Please open an issue or pull request on [GitHub](https://github.com/nic01asFr/BigBlenderMCP).

---

**BigBlender** - Bringing 3D creation to AI, one prompt at a time.
