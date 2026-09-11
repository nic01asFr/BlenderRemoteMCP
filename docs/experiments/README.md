# Boucle expériences → service

Ce dossier capitalise les **essais** pour qu’ils redeviennent des
**fonctionnalités / specs / skills / templates** sans perte d’information.

## Principe

```
Intention métier (user expert)
        ↓
Expérience documentée (docs/experiments/<track>/)
        ↓
Observations (JOURNAL + résultats mesurables)
        ↓
Promotion (checklist ci-dessous)
        ↓
Service enrichi (expertise/, gn_lib/, mat_lib/, MCP tools, specs)
```

## Règles

1. **Ne rien laisser dans le chat seulement** — toute décision utile va dans
   `JOURNAL.md` du track + éventuel extrait dans `expertise/` ou `docs/superpowers/specs/`.
2. **GN + materials** = littératie opérateur Blender (toujours). Les résultats
   métier (maquette LOD, voirie, BIM…) sont des **tracks** séparés qui
   *utilisent* ces écrans.
3. Chaque expérience a : objectif, données, procédure, résultat, écarts,
   **ce qui est promu** (ou reporté).
4. Les fixtures de test (GeoJSON, etc.) vivent sous `fixtures/` et restent
   versionnées si légalement redistribuables (sinon README + procédure d’obtention).

## Checklist de promotion

Quand un essai fonctionne :

- [ ] Entrée `JOURNAL.md` complète (date, commande, métriques)
- [ ] Skill ou paragraphe d’expertise mis à jour
- [ ] Recipe / template `gn_*` / `mat_*` si reproductible
- [ ] Spec design mise à jour (`docs/superpowers/specs/`)
- [ ] Plan d’implémentation ajusté (`docs/superpowers/plans/`)
- [ ] Contrat `expertise/integrations/`
- [ ] Test automatisé si possible sans Docker Blender (registry, parse GeoJSON…)

## Tracks actifs

| Track | Dossier | Statut |
|-------|---------|--------|
| GIS maquette urbaine LOD1→2 | `gis-urban-lod/` | amorcé |
| Geometry Nodes (opérateur) | voir branche `feature/blender-geometry-nodes` | fait (socle) |
| Materials (opérateur) | voir branche `feature/blender-materials` | fait (socle) |
