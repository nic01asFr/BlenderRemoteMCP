# Architecture Blender MCP Server - Mode Unifié

## 📋 Document de Référence
**Version:** 2.0
**Date:** 2026-01-04
**Type:** Architecture unifiée avec support VNC intégré

---

## 🎯 PRINCIPE GÉNÉRAL

### Vue d'ensemble

Le **Blender MCP Server** adopte une **architecture unifiée** où chaque instance Blender est accessible à la fois :
- **Programmatiquement** via API REST (pour le contrôle MCP/LLM)
- **Visuellement** via interface web noVNC (pour interaction humaine)

Cette approche permet une **collaboration hybride** entre IA et humains sur la même instance Blender en temps réel.

### Philosophie de conception

```
Un seul mode = Maximum de flexibilité + Minimum de complexité
```

**Principes directeurs :**
1. ✅ **Toujours accessible** : VNC et API disponibles en permanence
2. ✅ **Overhead minimal** : Services légers (~50MB RAM, <5% CPU)
3. ✅ **Debuggable** : Visualisation temps réel de ce que fait le LLM
4. ✅ **Flexible** : Supporte tous les cas d'usage sans reconfiguration
5. ✅ **Simple** : Une seule configuration à maintenir

---

## 🏗️ ARCHITECTURE TECHNIQUE

### Schéma global

```
┌─────────────────────────────────────────────────────────────────┐
│                     UTILISATEURS / CLIENTS                       │
├──────────────────────────┬──────────────────────────────────────┤
│   Claude Desktop (MCP)   │   Navigateur Web                     │
│   API REST               │   noVNC HTML5                        │
└──────────┬───────────────┴──────────────┬───────────────────────┘
           │                              │
           │ HTTP/JSON-RPC                │ WebSocket (VNC)
           │ Port 8100 → 8080             │ Port 6080
           │                              │
┌──────────▼──────────────────────────────▼───────────────────────┐
│              BLENDER MCP SERVER (Container Host)                │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  main_mcp.py - Orchestrateur principal                     │ │
│  │  - Gestion des sessions utilisateurs                       │ │
│  │  - Création/démarrage des containers Blender               │ │
│  │  - Routage des requêtes MCP → API Blender                  │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          │ Crée et gère
                          │
           ┌──────────────┴──────────────┐
           │                             │
┌──────────▼─────────────┐    ┌─────────▼──────────────┐
│  Blender User A        │    │  Blender User B        │
│  (Container isolé)     │    │  (Container isolé)     │
│                        │    │                        │
│  ┌──────────────────┐  │    │  ┌──────────────────┐  │
│  │ AFFICHAGE        │  │    │  │ AFFICHAGE        │  │
│  │                  │  │    │  │                  │  │
│  │ Xvfb :99         │  │    │  │ Xvfb :99         │  │
│  │ (Virtual X)      │  │    │  │ (Virtual X)      │  │
│  │   └─ fluxbox     │  │    │  │   └─ fluxbox     │  │
│  │      (WM léger)  │  │    │  │      (WM léger)  │  │
│  │        └─ Blender│  │    │  │        └─ Blender│  │
│  │           (GUI)  │  │    │  │           (GUI)  │  │
│  └───────┬──────────┘  │    │  └───────┬──────────┘  │
│          │             │    │          │             │
│    ┌─────┴─────┐       │    │    ┌─────┴─────┐       │
│    │           │       │    │    │           │       │
│    ▼           ▼       │    │    ▼           ▼       │
│ ┌──────┐  ┌─────────┐ │    │ ┌──────┐  ┌─────────┐ │
│ │ VNC  │  │ API REST│ │    │ │ VNC  │  │ API REST│ │
│ │ 6080 │  │ 8080    │ │    │ │ 6080 │  │ 8080    │ │
│ │      │  │         │ │    │ │      │  │         │ │
│ │x11vnc│  │api_     │ │    │ │x11vnc│  │api_     │ │
│ │noVNC │  │server.py│ │    │ │noVNC │  │server.py│ │
│ │      │  │         │ │    │ │      │  │         │ │
│ │      │  │blender_ │ │    │ │      │  │blender_ │ │
│ │      │  │addon.py │ │    │ │      │  │addon.py │ │
│ └──────┘  └─────────┘ │    │ └──────┘  └─────────┘ │
│                        │    │                        │
│ Ports: 9000, 9100      │    │ Ports: 9001, 9101      │
└────────────────────────┘    └────────────────────────┘
```

### Stack technologique

#### Container Blender (par utilisateur)

| Composant | Rôle | Port/Config |
|-----------|------|-------------|
| **Xvfb** | Serveur X virtuel (display :99) | Display virtuel |
| **fluxbox** | Window manager léger | Gère les fenêtres |
| **Blender 4.0** | Application 3D (mode GUI) | Connecté à :99 |
| **Mesa llvmpipe** | OpenGL software rendering | LIBGL_ALWAYS_SOFTWARE=1 |
| **x11vnc** | Serveur VNC (capture display) | Port interne 5900 |
| **noVNC** | Client VNC web (WebSocket) | Port 6080 |
| **api_server.py** | API REST FastAPI | Port 8080 |
| **stream_server.py** | Stream MJPEG viewport | Port 8081 |
| **blender_addon.py** | Plugin Blender (socket UNIX) | /tmp/blender.sock |
| **supervisor** | Orchestrateur de processus | Gère tous les services |

---

## 🔄 FLUX D'INTERACTION

### Cas d'usage 1 : LLM seul (API)

```
Claude Desktop
    │
    │ MCP JSON-RPC
    ▼
main_mcp.py (port 8100)
    │
    │ HTTP POST /api/create_object
    ▼
api_server.py (port 8080)
    │
    │ UNIX socket
    ▼
blender_addon.py
    │
    │ bpy.ops.mesh.primitive_cube_add()
    ▼
Blender (exécute)
    │
    │ Rendu viewport
    ▼
Display Xvfb :99
    │
    │ (VNC disponible mais non utilisé)
    ▼
x11vnc + noVNC (en attente)
```

### Cas d'usage 2 : Humain seul (VNC)

```
Navigateur
    │
    │ WebSocket
    ▼
noVNC (port 6080)
    │
    │ VNC Protocol
    ▼
x11vnc
    │
    │ Capture display :99
    ▼
Display Xvfb :99
    │
    │ Blender s'affiche
    ▼
Humain interagit
    │
    │ Clics/Clavier via VNC
    ▼
Blender (reçoit inputs)
```

### Cas d'usage 3 : Collaboration (LLM + Humain) 🔥

```
         Claude (MCP)              Humain (Navigateur)
              │                            │
              │                            │
              ▼                            ▼
         api_server                    noVNC
              │                            │
              └────────┬───────────────────┘
                       │
                       ▼
                  Blender (scène partagée)
                       │
                       ▼
                 Display :99
                       │
              ┌────────┴────────┐
              │                 │
              ▼                 ▼
         x11vnc (stream)   Rendu temps réel
              │
              ▼
      Humain voit les actions de Claude en direct !
```

**Exemple concret :**
1. Claude crée un cube via MCP → `create_object`
2. Humain voit le cube apparaître en temps réel dans le navigateur
3. Humain ajuste manuellement la position via VNC
4. Claude ajoute une texture via MCP → `set_material`
5. Humain voit la texture s'appliquer immédiatement

---

## 🎨 SUPPORT RENDU (Software OpenGL)

### Problématique

**Sans Mesa llvmpipe :**
```
Eevee/Cycles → OpenGL requis → Xvfb basique ne supporte pas → SIGABRT crash
```

**Avec Mesa llvmpipe :**
```
Eevee/Cycles → OpenGL → llvmpipe (software) → Rendu CPU → ✅ Fonctionne
```

### Configuration

```dockerfile
# Packages Mesa pour software rendering
RUN apt-get install -y \
    mesa-utils \
    libgl1-mesa-dri \
    libgl1-mesa-glx \
    libosmesa6 \
    libglapi-mesa

# Variables d'environnement
ENV LIBGL_ALWAYS_SOFTWARE=1  # Force software OpenGL
ENV GALLIUM_DRIVER=llvmpipe   # Driver Mesa software
ENV LP_NUM_THREADS=4          # Threads pour llvmpipe
```

### Moteurs de rendu supportés

| Moteur | Mode | Performance | Qualité |
|--------|------|-------------|---------|
| **Workbench** | CPU | ⚡ Rapide | Preview |
| **Eevee** | CPU (llvmpipe) | 🐌 Lent | Temps réel |
| **Cycles** | CPU | 🐌 Très lent | Photorealistic |

**Note :** Phase 3 (GPU) accélère Eevee/Cycles si NVIDIA disponible.

---

## 📊 OVERHEAD ET PERFORMANCE

### Ressources consommées (par container)

| Composant | RAM | CPU (idle) | CPU (actif) |
|-----------|-----|------------|-------------|
| Xvfb | 20 MB | 0% | 1-2% |
| fluxbox | 10 MB | 0% | <1% |
| x11vnc | 15 MB | 0% | 2-5% (si client connecté) |
| noVNC | 5 MB | 0% | <1% |
| **Total overhead VNC** | **~50 MB** | **<1%** | **5-8%** |
| Blender | 400-800 MB | 5-10% | Variable |
| **TOTAL container** | **~500-900 MB** | **5-10%** | Variable |

### Analyse

**Overhead VNC = 5-10% des ressources totales**
- Négligeable pour les bénéfices apportés
- Pas de dégradation de performance perceptible
- Toujours accessible pour debug

---

## 🔒 SÉCURITÉ

### Contrôle d'accès

```yaml
# Production : Désactiver VNC externe
ports:
  - "8080:8080"  # API exposée
  # - "6080:6080"  # VNC NON exposé (commenté)

# Développement : VNC accessible
ports:
  - "8080:8080"  # API
  - "6080:6080"  # VNC pour debug
```

### Authentification

- **API REST** : JWT token + API key (existant)
- **VNC** : Pas de mot de passe par défaut (-nopw)
  - ✅ OK si ports non exposés publiquement
  - ⚠️ Ajouter `-passwd /path/to/vncpasswd` pour sécuriser si exposé

---

## 🧪 TESTABILITÉ

### Points de test

1. **Software OpenGL** : `glxinfo | grep "OpenGL renderer"`
   - Attendu : `llvmpipe (LLVM...)`

2. **VNC accessible** : `curl http://localhost:6080/vnc.html`
   - Attendu : HTTP 200, page HTML noVNC

3. **Blender répond** : `curl http://localhost:8080/health`
   - Attendu : `{"status": "ok"}`

4. **Screenshot Cycles** : `curl http://localhost:8080/api/screenshot`
   - Attendu : Base64 PNG, pas de SIGABRT

5. **Interaction VNC** : Ouvrir navigateur → Voir Blender
   - Attendu : Interface Blender responsive

---

## 📝 JUSTIFICATIONS ARCHITECTURALES

### Pourquoi mode unifié ?

| Critère | Mode unique | Deux modes |
|---------|-------------|------------|
| **Complexité code** | ✅ Simple | ❌ Conditionnelle |
| **Maintenance** | ✅ Un seul chemin | ❌ Deux chemins à tester |
| **Debug** | ✅ Toujours visualisable | ❌ Parfois aveugle |
| **Overhead** | ⚠️ +50MB (+10%) | ✅ Minimal |
| **Flexibilité** | ✅ Tous cas d'usage | ⚠️ Choix au déploiement |
| **Démo/Formation** | ✅ Wow effect | ❌ Pas d'interface |

**Verdict :** Mode unique optimal pour ce projet (overhead négligeable, bénéfices énormes).

### Pourquoi Software OpenGL d'abord ?

1. **Universel** : Marche partout (GPU ou pas)
2. **Simple** : Variables d'env + packages
3. **Stable** : Pas de drivers GPU à gérer
4. **Suffisant** : Pour prévisualisation MCP

GPU (Phase 3) = Bonus performance, pas requis.

### Pourquoi noVNC vs autres ?

| Solution | Avantages | Inconvénients |
|----------|-----------|---------------|
| **noVNC** | ✅ HTML5 pur, pas d'install client | ⚠️ Latence légère |
| TurboVNC | Performance maximale | ❌ Client natif requis |
| Guacamole | Interface riche | ❌ Architecture complexe |
| X11 forwarding | Natif | ❌ SSH tunnel, pas web |

**Verdict :** noVNC = meilleur compromis simplicité/fonctionnalité.

---

## 🚀 ÉVOLUTION FUTURE

### Phase 3 (optionnelle) : GPU Support

```yaml
# Si NVIDIA GPU disponible sur l'hôte
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

**Bénéfices :**
- Eevee/Cycles 10-50x plus rapides
- Rendu temps réel possible
- Viewport fluide à 60fps

**Quand l'implémenter ?**
- Si serveur avec GPU NVIDIA
- Si besoin de rendus rapides
- Si interactions temps réel critiques

### Extensions possibles

1. **Multi-utilisateurs simultanés** : Partage de scène temps réel
2. **Enregistrement sessions** : Replay des actions
3. **Snapshots automatiques** : Versioning de scènes
4. **API WebSocket** : Events temps réel (objet créé, modifié, etc.)

---

## 📚 RÉFÉRENCES

- [Mesa llvmpipe Documentation](https://docs.mesa3d.org/drivers/llvmpipe.html)
- [noVNC Project](https://github.com/novnc/noVNC)
- [Blender Headless Rendering](https://docs.blender.org/manual/en/latest/advanced/command_line/render.html)
- [Xvfb Manual](https://www.x.org/releases/X11R7.6/doc/man/man1/Xvfb.1.xhtml)

---

**Document maintenu par :** Claude Code
**Dernière révision :** 2026-01-04
**Statut :** Architecture approuvée, prête pour implémentation
