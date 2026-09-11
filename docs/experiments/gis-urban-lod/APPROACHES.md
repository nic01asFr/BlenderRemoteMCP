# Approches — maquette urbaine pro depuis référentiels

**Date :** 2026-09-11  
**Contexte :** le smoke LOD1 (boîtes) n’est **pas** un livrable.  
Objectif : méthode pour une maquette digne de l’état de l’art (LOD2-ish), agent + expert.

## Principe directeur

```
SIG / référentiels  →  préparation géospatiale  →  assets Blender-ready  →  GN + mats + rendu
     (externe)              (service/script)         (/projects)            (opérateur BlenderRemoteMCP)
```

Ne **pas** faire du GIS lourd *dans* Blender si un outil externe le fait mieux.  
Blender = assemblage 3D / shading / validation desktop.  
QGIS / GDAL / APIs = vérité géométrique et CRS.

---

## Option A — Prétraitement externe (recommandée)

**Quoi :** pipeline hors Blender (Python GDAL/geopandas, ou QGIS model, ou job Onyxia) qui :

1. Télécharge / découpe BD TOPO (bâti), MNT, éventuellement voirie  
2. Reprojette (EPSG:2154 → repère local métrique centré zone)  
3. Exporte :
   - `buildings.cityjson` ou GeoJSON enrichi (height, roof, nature)
   - `terrain.tif` ou mesh `terrain.obj` / `terrain.ply`
   - optionnel : `ortho.jpg` + world file pour texturing sol
4. Blender importe des **assets déjà propres** + GN/mats pour peaufiner

**Pour :** qualité geo, testable sans GUI Blender, réutilise QGIS MCP / stack Cerema, licences et quotas API gérés hors image Blender.  
**Contre :** deux systèmes à orchestrer (agent compose MCP QGIS + Blender).

**Services / briques :**

| Brique | Rôle |
|--------|------|
| IGN Géoplateforme (WFS/WCS) ou dépôt local | Données |
| `geopandas` / GDAL / pyproj | Découpe, reproj, attributs |
| QGIS (BigQgisMCP / qgis-hub déjà dans l’écosystème) | Préparation interactive + scripts |
| CityJSON / glTF | Échange 3D standardisant LOD |
| BlenderRemoteMCP | Import + GN + mats + desktop |

---

## Option B — Addon BlenderGIS (dans l’image)

**Quoi :** installer [BlenderGIS](https://github.com/domlysz/BlenderGIS) dans l’image `blender-canvas` (ou profil `gis`), importer shapefile/GeoTIFF/OSM depuis l’UI ou via bpy si exposé.

**Pour :** un seul outil « Blender-centric », familier aux géomaticiens Blender.  
**Contre :**

- Addon GUI-first → API agent souvent fragile  
- Compat Blender **4.0** à vérifier (upstream suit souvent les dernières versions)  
- Réseau / téléchargements SRTM depuis le pod (firewall SSPCloud)  
- Enrichit l’image (poids, maintenance, licences)  
- Moins bon que GDAL pour BD TOPO métier Cerema

**Verdict :** utile en **profil optionnel** pour exploration humaine sur `/desktop`, **pas** comme colonne vertébrale agent. Si on l’ajoute : wrapper MCP mince (`gis_import_raster`, `gis_import_shp`) qui appelle l’API addon, jamais des clics.

---

## Option C — Tout en Geometry Nodes depuis raw GIS

**Quoi :** lire GeoJSON/CSV d’attributs dans un gros graphe GN / `execute_python` et tout construire dans Blender.

**Pour :** élégant une fois les données déjà « Blender-ready ».  
**Contre :** CRS, topologie, MNT, découpes = mauvais endroit ; le smoke boîtes montre le plafond bas si on commence ici.

**Verdict :** **étape finale** d’assemblage (LOD2 toitures, instances, mats), pas d’ingestion référentielle.

---

## Option D — Formats 3D city déjà faits

**Quoi :** consommer CityGML/CityJSON/3D Tiles produits ailleurs (pipeline IGN, FME, outils internes).

**Pour :** état de l’art immédiat si la source existe.  
**Contre :** dépend d’un producteur amont ; moins pédagogique pour « maîtriser » la chaîne ; importer CityGML dans Blender 4.0 n’est pas trivial (souvent via conversion glTF/OBJ).

**Verdict :** excellent **raccourci zone pilote** si un extrait CityJSON existe déjà au Cerema — sinon Option A.

---

## Recommandation (comment s’y prendre)

### Architecture cible

```
┌─────────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│  Passerelle données │     │  Prepare GIS (job)   │     │  BlenderRemoteMCP   │
│  IGN / S3 / PVC     │────▶│  QGIS ou Python GDAL │────▶│  import + GN + mats │
└─────────────────────┘     │  → /projects/zone/   │     │  desktop validation │
                            └──────────────────────┘     └─────────────────────┘
         agent orchestre les deux MCP (QGIS + Blender) + user expert valide
```

### Phases de travail

1. **Contrat d’échange** (figer)  
   `zone/buildings.geojson` + `terrain.obj` + `meta.json` (CRS, bbox, counts, source, date).

2. **Job `prepare_urban_lod`** (script repo ou service Onyxia)  
   Entrée : bbox + chemins sources. Sortie : dossier `/projects` conforme au contrat.  
   Tests : hors Blender (pyproj, counts, heights stats).

3. **Import Blender** (outil/recipe, pas BlenderGIS obligatoire)  
   - buildings → objets ou un mesh + attributs  
   - terrain → mesh  
   - mats par `nature` / `usage`  
   - caméra auto bbox  

4. **Enrichissement LOD2** (GN)  
   Toitures selon attributs BD TOPO ; pas avant que LOD1 **réel** soit propre.

5. **BlenderGIS** (optionnel, profil image `gis`)  
   Pour l’expert sur le desktop uniquement ; documenté comme secondaire.

### Ce qu’il ne faut plus faire

- Présenter des cubes synthétiques comme « résultat pro »  
- Coller WFS IGN dans `execute_python` Blender sans couche prepare  
- Attendre LOD3 avant d’avoir terrain + bâti référentiels corrects  

### Critère de succès « professionnel » (à écrire dans la spec)

Une zone pilote réelle où un expert dit : « on voit le tissu urbain, les hauteurs et le relief sont crédibles, ça sert à une revue » — pas seulement `heights_match: True`.

---

## Liens track

- Expériences : `docs/experiments/gis-urban-lod/`  
- Spec produit : `docs/superpowers/specs/2026-09-11-gis-urban-lod-design.md`  
- Smoke (non-livrable) : JOURNAL 2026-09-11 baseline bmesh
