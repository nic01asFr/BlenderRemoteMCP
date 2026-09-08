# Architecture BlenderRemoteMCP

Version 3.0 — 2026-09-06
Remplace la v2.0 (2026-01-04, « Mode Unifié »), dont le principe de collaboration
hybride IA/humain sur une même instance reste valide et est repris ici.

---

## 1. Place du service dans la chaîne

BlenderRemoteMCP n'est pas un produit autonome : c'est le maillon *runtime 3D*
d'une chaîne qui existe déjà dans l'écosystème.

```
capture 3D           panoramax3d (STAC Panoramax -> cubemap -> COLMAP SfM
                     -> DepthPro -> fusion TSDF -> PLY/LAS), pix2hdr,
                     recalage visuel
      |
géo / référentiels   QgisRemoteMCP, Atlas, Scene Manifest V0.2
      |
runtime 3D           BlenderRemoteMCP        <-- ce dépôt
      |
métier               route : ARP 2022 / ICTAAL / ICTAVRU / Girabase
                     BIM  : DTU 60.1, DTU 68.3, NF C 15-100, RE2020, IFC 4.3
      |
restitution          Atlas (widget + runtime + app), widgets Grist,
                     storymaps, Strate
```

C'est le seul maillon dont ni l'amont ni l'aval ne sont câblés aujourd'hui.

### Répartition du rendu

Point structurant, souvent mal compris : **Blender ne rend pas pour Atlas.**

Le contrat Scene Manifest V0.2 définit `kind: 3d_model` avec `gltf_url` requis
(plus `scale_field`, `rotation_field`), et `kind: extrusion` avec `height_field`.
Le moteur Models3D du widget Atlas instancie ces GLTF en `InstancedMesh`, selon
le pattern MapLibre custom layer + Three.js (en production dans cinq projets de
l'écosystème). Atlas est donc le runtime de rendu et le livrable autonome.

Il en découle deux sorties distinctes pour ce service :

| Sortie | Consommateur | Nature |
|---|---|---|
| Assets GLTF + fragment de Scene Manifest | Atlas, widgets Grist | interactif, rendu côté client |
| Images / vidéos / séquences | rapports, storymaps figées | rendu Blender (Eevee/Cycles) |

La première est la voie principale et n'utilise pas le moteur de rendu de
Blender. La seconde est un livrable séparé, pas une dégradation de la première.

---

## 2. Architecture interne actuelle

Tout appel d'outil traverse quatre frontières de processus :

```
client MCP
  | HTTP POST /mcp, Authorization: Bearer blender_xxx
main_mcp.py            handler JSON-RPC écrit à la main (spec 2024-11-05)
  | httpx vers le port hôte publié
src/container_manager.py
  |
docker/blender-canvas/api_server.py        FastAPI :8080 dans le container
  | socket Unix /tmp/blender_api.sock
docker/blender-canvas/blender_addon.py     thread socket dans le process Blender
  |
bpy
```

Le canvas navigateur suit un chemin parallèle : `/canvas` sert
`templates/blender_canvas.html`, qui ouvre `/ws/{user_id}` ; le serveur relaie
vers websockify, qui fronte x11vnc sur l'affichage Xvfb. Agent et humain
partagent ainsi la même session GUI — c'est l'acquis de la v2.0, à conserver.

### Défauts structurels de l'existant

1. **bpy exécuté hors du thread principal.** `SocketServer` tourne dans un
   thread daemon et `handle_client` appelle le handler directement. `bpy` n'est
   pas thread-safe : c'est une source de crashs et d'états corrompus.
2. **Session MCP et utilisateur confondus.** `user_id` sert à la fois de clé de
   session et de clé de container, ce qui interdit plusieurs agents sur une
   instance.
3. **Transport sans sessions.** `POST /mcp` simple, sans `Mcp-Session-Id` ni
   SSE : pas de connecteur MCP distant, pas de progression sur les appels longs.
4. **Isolation obligatoire.** Un container par utilisateur via le socket Docker
   de l'hôte : modèle non portable sur un pod.

---

## 3. Architecture cible

Quatre couches, chacune reprise d'une source éprouvée plutôt que réécrite.

| Couche | Source | Contenu |
|---|---|---|
| Hébergement | ce dépôt | container Blender, Xvfb, noVNC, canvas, isolation, autosave, cleanup |
| Pont vers bpy | BigLocalApps | `addons/blender/bigdesktop_bridge.py` |
| Métier | BigDesktop | `profile_manager.py`, `conductor_engine.py`, `tools_app.py`, corpus YAML |
| Forme de service | QgisRemoteMCP | streamable HTTP, flag mono/multi, skills en resources, auth, chart Onyxia |

### Pont vers bpy

`bigdesktop_bridge.py` remplace `blender_addon.py`. Il résout le défaut 1 :
file de requêtes plus files de réponses par `request_id`, exécution sur le
thread principal via `bpy.app.timers.register(_poll_queue, persistent=True)`, et
cadrage des messages sur 4 octets big-endian au lieu du délimiteur newline.
C'est aussi le prérequis pour exécuter les actions de profil.

### Surface MCP : divulgation progressive

Les actions métier ne sont pas exposées une par une. Le catalogue vit dans les
profils, filtré par contexte et par posture, derrière une poignée d'outils
génériques — c'est le modèle BigDesktop, et c'est le bon :

- `blender_action(action_id, params)` — dispatch dans le catalogue, validation
  des paramètres, hook de feedback conducteur
- `blender_context()` — détection d'état (workspace, mode, sélection)
- `activate_extension(ext_id)` / `deactivate_extension(ext_id)`
- `generate_code(...)` — voie d'échappement
- outils propres à l'hébergement : capture d'écran, canvas exposé en resource
  `ui://`, gestion des projets et fichiers

Les 35 outils actuels recouvrent largement les 62 actions du profil Blender :
ils sont à fusionner dans le catalogue, pas à empiler à côté.

### Transport

FastMCP fournit nativement le streamable HTTP et BigDesktop l'utilise déjà, ses
décorateurs portent donc sans conversion. De QgisRemoteMCP ne sont repris à la
main que les éléments que FastMCP ne donne pas : le shim `/sse` de
compatibilité `mcp-remote`, et la progression sur les rendus longs.

`type QgisRemoteMCP` désigne ici la *forme de service* — mono/multi, skills en
resources, auth, déployable sur pod — et non son transport écrit à la main.

### Modes

- `MULTI_USER_MODE=false` : image tout-en-un, le serveur MCP parle directement
  à `api_server:8080` dans le même container ; un `program:mcp_server` s'ajoute
  à `supervisord.conf`. C'est le mode déployable sur pod Onyxia, et il autorise
  plusieurs sessions agent sur une même instance.
- `MULTI_USER_MODE=true` : le gestionnaire de containers actuel, hors pod.

---

## 4. Où vit le métier

Le découpage n'est pas « YAML ou modules Python ». C'est la place de la norme.

Girabase établit le pattern dans l'écosystème : un noyau de calcul (`engine.py`)
vérifié par des tests de fidélité au VB6 CERTU d'origine, servi par plusieurs
surfaces — API REST, page web, widget Grist, outil MCP. Le document
`DEMARCHE.md` parle d'alternative « pluriforme ».

Conséquence pour ce service : **une action Blender est une surface, pas le lieu
du métier.** Les contrôles normatifs (ARP, DTU, NF C 15-100, capacité de
giratoire) appartiennent à un noyau partagé, indépendant de toute surface. Les
enfermer dans des YAML d'actions Blender, ou dans un `src/route/norms.py`,
revient au même défaut vu des deux côtés.

Le coût de ne pas tenir ce principe est déjà mesurable : le moteur Girabase
existe en deux exemplaires divergents (471 et 615 lignes) synchronisés par un
script de copie.

Piste ouverte : la spec formulaire de l'écosystème (axe
`grist-forms-blocknote-binding`) pourrait déclarer une seule fois les paramètres
d'une action et en dériver le formulaire Grist et l'`inputSchema` MCP.

---

## 5. Contrats d'entrée et de sortie à câbler

Ni la verticale route ni la verticale BIM ne les couvrent :

- **entrée** : consommer un Scene Manifest (`layers[]`, `style.declarative`,
  `camera`) pour construire une scène
- **entrée** : importer des nuages de points PLY/LAS produits par panoramax3d
- **sortie** : produire des GLTF et le fragment de Scene Manifest qui les
  référence (`kind: 3d_model`, `gltf_url`)

Le contrat Scene Manifest est en lecture seule ici : sa source de vérité est le
modèle Pydantic de `cerema-offre-de-service`. Ne pas le redéclarer.

---

## 6. Décisions ouvertes

1. **Positionnement.** Les documents `COMPETITIVE_ANALYSIS.md` et
   `BRAND_ARCHITECTURE.md` visent un SaaS créatif grand public (« grille de
   calcul 3D », `blendergrid.ai`). Tout l'usage réel documenté est un outil
   métier Cerema. Le code actuel — inscription email/mot de passe, clé API,
   cleanup à 30 minutes — sert le premier alors que la chaîne sert le second.
2. **Format d'expression des actions métier**, avant que route et BIM ne
   divergent définitivement (`PLAN.md` de BlenderRoads acte des modules Python
   pour la route, BigDesktop reste en YAML pour le BIM).
3. **Source de vérité du corpus** de profils, partagé entre BigDesktop
   (desktop Windows) et ce service (container) : package versionné commun, pas
   copie.
4. **BlenderRoads.** Décision prise : ce n'est ni un fork ni une extension à
   replier ici. C'est un produit métier — le pipeline complet de conception
   routière professionnelle, guides et doctrines traduits en formules puis
   gérées dans Blender — dont ce service est le socle d'hébergement. Reste à
   organiser la dépendance : dépôt distinct consommant ce service, et remontée
   ici des corrections de socle faites là-bas (capture X11, Workbench forcé en
   headless, `clip_end` caméra).
5. **`execute_python`.** Exécution arbitraire non bornée, structurelle pour un
   service Blender. À assumer explicitement (container jetable, utilisateur non
   root, pas de socket Docker en mode pod, quotas) plutôt qu'à sandboxer.
6. **Licences.** Le `README.md` de ce dépôt annonce MIT sans fichier `LICENSE`.
   BigLocalApps est MIT. Girabase est GPL-3.0, hérité du VB6 CERTU libéré par le
   CEREMA — et BlenderRoads en embarque une copie. S'ajoute le fait que le code
   exécuté à l'intérieur de Blender (addon, pont) relève des obligations GPL de
   Blender, contrairement au serveur qui l'entoure. À trancher avant toute
   publication ou fusion de ces briques.

---

## 8. État des dépôts (relevé 2026-09-06)

À corriger avant tout portage, indépendamment des choix d'architecture :

- Le dépôt GitHub porte déjà le nom `BlenderRemoteMCP` (privé) ; le remote local
  pointe encore sur l'ancienne URL et ne fonctionne que par redirection.
- `origin/main` ne contient que le commit initial : le commit local du canvas
  noVNC n'est pas poussé.
- Le dépôt sert d'hôte de *releases* pour pix2hdr (deux tags posés sur le commit
  initial). Usage à assumer explicitement ou à déplacer.
- **BlenderRoads n'a aucun dépôt git**, pas plus que le dossier Girabase local ;
  panoramax3d a un git sans remote. Le métier route, l'étude `PLAN.md` et le
  widget maître Girabase ne sont donc ni versionnés ni sauvegardés.
- Le dépôt public `nic01asFr/Girabase` existe pourtant : fork du dépôt CEREMA
  (sources VB6, exécutable, `LICENSE` GPL-3.0) avec le portage moderne sous
  `web/`, servi par GitHub Pages. Le dossier local en est déconnecté.
- Rythme : QgisRemoteMCP, Qgis-sspcloud et Widgets-Grist sont actifs au
  2026-09-06 ; ce dépôt est au 2026-01-09 et BigDesktop au 2026-03-28, ce
  dernier en avance d'un mois sur son propre remote.

---

## 7. État projet et concurrence

- L'état conducteur (manifeste, trame vivante) doit vivre dans le volume
  `/projects` de l'utilisateur, jamais dans un fichier global.
- Le cas d'usage BIM réel est deux agents de postures différentes (plomberie,
  électricité) sur la même instance. La file du pont sérialise déjà les appels
  bpy ; reste à câbler le verrouillage par lot sur les sessions MCP — le
  `lot_interface` et la porte `AUTO_PASS | PENDING_MOE` existent déjà côté
  BigDesktop.
- Le profil vise Blender 4.5, l'image container est en 4.0.2 : à aligner avant
  tout test d'action.
