# BlenderRemoteMCP

**Blender 4.0 cloud pour agents MCP** — instance isolée, canvas noVNC live, outils scène / matériaux / rendu.

[Vitrine](https://nic01asfr.github.io/BlenderRemoteMCP/) · [Dépôt](https://github.com/nic01asFr/BlenderRemoteMCP)

## Démarrage rapide

```bash
git clone https://github.com/nic01asFr/BlenderRemoteMCP.git
cd BlenderRemoteMCP
docker-compose up -d --build
```

Service sur **http://localhost:8100** (compose).

### Clé API

```bash
curl -X POST http://localhost:8100/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"yourpassword"}'
```

### Client MCP (Cursor / Claude Desktop)

```json
{
  "mcpServers": {
    "blender": {
      "url": "http://localhost:8100/mcp",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

### Canvas

```
http://localhost:8100/canvas?token=YOUR_API_KEY
```

L’agent doit appeler `get_canvas_url` (ou `blender_desktop_ui` si MCP Apps) et **partager le lien** avec l’utilisateur.

## Fonctions clés

| Capacité | Détail |
|---|---|
| 37 outils MCP | objets, collections, matériaux, éclairage, caméra, rendu, Python `bpy` |
| Canvas noVNC | GUI Blender live dans le navigateur |
| MCP Apps | resource `ui://blenderremotemcp/desktop` + outil `blender_desktop_ui` |
| Auth | Bearer API key (`blender_…`), cookie, `?token=` |
| Modes | multi-user (Docker) ou mono (pod Onyxia / all-in-one) |

## Déploiement SSPCloud / Onyxia

```bash
# Image
docker build -t blender-canvas:latest docker/blender-canvas/
docker build -t ghcr.io/nic01asfr/blender-remote-mcp:latest -f docker/all-in-one/Dockerfile .
docker push ghcr.io/nic01asfr/blender-remote-mcp:latest

# Chart (Mes services)
helm upgrade --install blender-remote-mcp deploy/onyxia/chart/blender-remote-mcp \
  -n user-$USER \
  --set onyxia_user=$USER \
  --set mcpApiKey=blender_…
```

Manifeste brut (sans Mes services) : `deploy/onyxia/blender-remote-mcp.yaml`.

## Architecture

```
MCP client  →  /mcp (Streamable HTTP)
            →  api_server (:8080)  →  blender_addon (bpy)
            →  /canvas + /ws (noVNC)
```

Voir [ARCHITECTURE.md](ARCHITECTURE.md) et [CLAUDE.md](CLAUDE.md).

## Tests

```bash
python -m pytest tests/ -q
```

## Licence / contributions

Issues et PR : [github.com/nic01asFr/BlenderRemoteMCP](https://github.com/nic01asFr/BlenderRemoteMCP).
