# Blender Studio - MCP Server Architecture

## Concept

**Cloud Blender via MCP** - L'utilisateur n'a pas besoin d'installer Blender localement.
Il configure simplement son client MCP (Claude Desktop, etc.) et peut immédiatement créer en 3D.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           UTILISATEUR                                   │
│                                                                         │
│   ┌──────────────────────────┐         ┌─────────────────────────────┐  │
│   │     Claude Desktop       │         │     Navigateur Web          │  │
│   │     (Client MCP)         │         │     (Viewer optionnel)      │  │
│   │                          │         │                             │  │
│   │   User: "Crée une        │         │   ┌─────────────────────┐   │  │
│   │         maison 3D"       │         │   │  Stream Live        │   │  │
│   │                          │         │   │  Blender Viewport   │   │  │
│   │   Claude: "Je crée..."   │         │   │                     │   │  │
│   └────────────┬─────────────┘         │   └─────────────────────┘   │  │
│                │                        └──────────────┬──────────────┘  │
└────────────────┼───────────────────────────────────────┼────────────────┘
                 │                                       │
                 │ MCP Protocol                          │ MJPEG
                 │ X-API-Key: blender_xxx                │
                 ▼                                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     BLENDER STUDIO SERVICE                              │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                        FastMCP Server                             │  │
│  │                                                                   │  │
│  │   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │  │
│  │   │   RESOURCES     │  │     TOOLS       │  │    PROMPTS      │  │  │
│  │   │                 │  │                 │  │                 │  │  │
│  │   │ blender://      │  │ create_object() │  │ new-project     │  │  │
│  │   │   status        │  │ modify_object() │  │ scene-from-     │  │  │
│  │   │   scene         │  │ delete_object() │  │   description   │  │  │
│  │   │   projects      │  │ set_color()     │  │ improve-scene   │  │  │
│  │   │   guide         │  │ execute_python()│  │                 │  │  │
│  │   │                 │  │ save_project()  │  │                 │  │  │
│  │   │                 │  │ load_project()  │  │                 │  │  │
│  │   │                 │  │ clear_scene()   │  │                 │  │  │
│  │   │                 │  │ screenshot()    │  │                 │  │  │
│  │   └─────────────────┘  └─────────────────┘  └─────────────────┘  │  │
│  │                                                                   │  │
│  │   Auto-start: Première commande → démarre Blender                │  │
│  │   Auto-save:  Toutes les 5 minutes                               │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      Container Manager                            │  │
│  │                                                                   │  │
│  │   • Démarre un container Docker à la première requête             │  │
│  │   • 1 container isolé par utilisateur                            │  │
│  │   • Cleanup automatique après inactivité (30 min)                │  │
│  │   • Health checks continus                                        │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
└────────────────────────────────────┼────────────────────────────────────┘
                                     │
                  ┌──────────────────┴───────────────────┐
                  ▼                                      ▼
          ┌──────────────────┐                  ┌──────────────────┐
          │   User A         │                  │   User B         │
          │   Container      │                  │   Container      │
          │                  │                  │                  │
          │  ┌────────────┐  │                  │  ┌────────────┐  │
          │  │   Xvfb     │  │                  │  │   Xvfb     │  │
          │  │  (écran    │  │                  │  │  (écran    │  │
          │  │   virtuel) │  │                  │  │   virtuel) │  │
          │  └─────┬──────┘  │                  │  └─────┬──────┘  │
          │        │         │                  │        │         │
          │  ┌─────▼──────┐  │                  │  ┌─────▼──────┐  │
          │  │  Blender   │  │                  │  │  Blender   │  │
          │  │  GUI Mode  │  │                  │  │  GUI Mode  │  │
          │  └─────┬──────┘  │                  │  └─────┬──────┘  │
          │        │         │                  │        │         │
          │  ┌─────▼──────┐  │                  │  ┌─────▼──────┐  │
          │  │  MJPEG     │  │                  │  │  MJPEG     │  │
          │  │  Stream    │──┼──► Browser       │  │  Stream    │  │
          │  └────────────┘  │                  │  └────────────┘  │
          │                  │                  │                  │
          │  📁 /projects/   │                  │  📁 /projects/   │
          │     (volume)     │                  │     (volume)     │
          └──────────────────┘                  └──────────────────┘
```

## Expérience Utilisateur

### Configuration (une seule fois)

1. **S'inscrire** sur le site web → Obtenir une API Key
2. **Configurer** Claude Desktop:

```json
{
  "mcpServers": {
    "blender": {
      "url": "https://blender.example.com/mcp",
      "headers": {
        "Authorization": "Bearer blender_abc123xyz..."
      }
    }
  }
}
```

### Utilisation

L'utilisateur parle naturellement à Claude:

```
User: "Crée une scène avec une table et deux chaises"

Claude: Je vais créer cette scène pour vous.
        [Appelle create_object, modify_object, etc.]

        ✓ Table créée au centre
        ✓ Chaise 1 positionnée à gauche
        ✓ Chaise 2 positionnée à droite

        Vous pouvez voir le résultat en direct sur:
        https://studio.blender.example/stream
```

**Pas besoin de:**
- Installer Blender
- Configurer un bridge MCP local
- Comprendre les commandes Blender

## Ce que le Serveur MCP Fournit

### Resources (Contexte pour l'IA)

| URI | Description |
|-----|-------------|
| `blender://status` | État de la session, capacités disponibles |
| `blender://scene` | Objets actuels, propriétés de la scène |
| `blender://projects` | Liste des projets sauvegardés |
| `blender://guide` | Guide d'utilisation pour l'IA |

### Tools (Actions)

| Tool | Description |
|------|-------------|
| `start_session()` | Démarre Blender (auto si nécessaire) |
| `list_objects()` | Liste les objets de la scène |
| `create_object(type, name, location, color)` | Crée un objet 3D |
| `modify_object(name, location, rotation, scale)` | Modifie un objet |
| `set_object_color(name, color)` | Applique une couleur |
| `delete_object(name)` | Supprime un objet |
| `execute_python(code)` | Code Blender avancé |
| `save_project(name)` | Sauvegarde le projet |
| `load_project(name)` | Charge un projet |
| `clear_scene()` | Efface la scène |
| `take_screenshot()` | Capture le viewport |
| `get_help()` | Aide pour l'IA |

### Prompts (Workflows prédéfinis)

| Prompt | Description |
|--------|-------------|
| `new-project` | Démarre un nouveau projet vierge |
| `scene-from-description` | Crée une scène à partir d'une description |
| `improve-scene` | Analyse et suggère des améliorations |

## Fonctionnalités Automatiques

### Auto-Start
```
Première commande MCP
        │
        ▼
┌───────────────────┐
│ User authentifié  │
│ via API Key       │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Container Docker  │
│ démarré auto      │
│ (~10-30 sec)      │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Blender prêt      │
│ Commande exécutée │
└───────────────────┘
```

### Auto-Save
- Sauvegarde automatique toutes les 5 minutes
- Fichier: `/projects/autosave.blend`
- Transparent pour l'utilisateur

### Auto-Cleanup
- Après 30 min d'inactivité → Container arrêté
- Volumes persistants → Projets conservés
- Reconnexion → Redémarre le container

## Stack Technique

### Composants

| Service | Technologie | Rôle |
|---------|-------------|------|
| MCP Server | FastMCP + FastAPI | Point d'entrée MCP |
| Auth | JWT + API Keys | Authentification |
| Containers | Docker | Isolation utilisateurs |
| Blender | Blender 4.0 + Xvfb | Rendu 3D |
| Streaming | FFmpeg MJPEG | Preview live |
| Storage | Volumes Docker | Projets persistants |

### Fichiers Principaux

```
src/
├── mcp_blender_service.py   # Serveur MCP principal
├── container_manager.py     # Gestion Docker
├── auth.py                  # Authentification
└── ...

docker/
└── blender-canvas/
    ├── Dockerfile           # Image Blender + streaming
    ├── blender_addon.py     # API socket dans Blender
    ├── api_server.py        # HTTP API container
    └── stream_server.py     # MJPEG streaming
```

## Déploiement

### Développement Local

```bash
# 1. Build l'image Blender
docker build -t blender-canvas:latest docker/blender-canvas/

# 2. Lancer le service
python main_multiuser.py

# 3. Configurer Claude Desktop avec localhost:8000/mcp
```

### Production (Docker Compose)

```bash
docker-compose up -d
```

Services:
- API Gateway: port 8000
- PostgreSQL: utilisateurs, sessions
- MinIO: stockage projets (optionnel)

## Sécurité

- **API Keys**: Identifient chaque utilisateur
- **Isolation**: 1 container Docker par user
- **Limits**: CPU/RAM par container
- **Cleanup**: Containers arrêtés après inactivité

## Scaling

| Plan | Containers | Storage | Notes |
|------|-----------|---------|-------|
| Free | 1 | 1 GB | Timeout 30min |
| Pro | 3 | 10 GB | GPU disponible |
| Team | 10 | 50 GB | Collaboration |
