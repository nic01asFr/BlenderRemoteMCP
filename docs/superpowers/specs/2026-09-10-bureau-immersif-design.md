# Design — Bureau immersif BlenderRemoteMCP (hub-ready)

**Date :** 2026-09-10  
**Statut :** approuvé (approche 2)

## Contexte

BlenderRemoteMCP est la couche **workspace / bureau MCP**, analogue à QgisRemoteMCP. Un futur hub SSPCloud (comme `qgis-sspcloud`) s’appuiera dessus. On ne construit pas le hub ici.

## Objectif

Rendre l’interface utilisateur **normale et transparente** : plein framebuffer Blender, sans chrome web ni jargon noVNC/VNC, avec un **contrat d’embed** pour un hub ultérieur.

## Surfaces

| Surface | Rôle |
|--------|------|
| `/desktop` | URL canonique du bureau immersif |
| `/canvas` | Alias de compatibilité (même handler) |
| `?embed=1` | Mode hub-ready (même UI ; documenté pour iframe) |
| `/ws/{user_id}` | Transport RFB inchangé |
| `/` | Landing : CTA « Ouvrir le bureau », sans « noVNC » |
| MCP App / `get_canvas_url` | Liens vers `/desktop` ; wording produit |

Hors scope : desk header type QGIS hub, workspace d’études, agent collé.

## UI

- Retirer : pastille status, boutons Fullscreen/Help/Exit, modal fullscreen, panneau raccourcis.
- Garder : RFB plein viewport (`scaleViewport`, `resizeSession`), focus, credentials vides, reconnexion limitée.
- Boot / reconnexion : écran neutre (« Démarrage… » / « Reconnexion… »).
- Connecté : uniquement Blender.
- Échec : message court + « Réessayer ».
- Auth inchangée (`?token=` / cookie `blender_token`).

## Langage runtime

Remplacer « canvas noVNC » / « VNC » par « bureau » / « session Blender » dans landing, instructions MCP, MCP App. Le nom d’outil `get_canvas_url` est conservé (compat clients).

## Tests

- `/desktop` et `/canvas` rendent la page RFB + cookie.
- `get_canvas_url` et resource MCP App pointent vers `/desktop?token=`.
- Instructions mentionnent `/desktop`.
- Page sans chrome (pas de `#controls`, `#fullscreen-hint`, `#status-indicator`).
