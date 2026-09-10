# Vitrine produit (GitHub Pages)

Page publique déployée sur <https://nic01asfr.github.io/BlenderRemoteMCP/>.

## Structure (standard Nic01asFr)

| Fichier | Rôle |
|---|---|
| `vitrine.json` | Contenu éditable (schéma type Wikichat) |
| `generate.mjs` | Génère `dist/index.html` |
| `generate.test.mjs` | Smoke Node |
| `dist/` | Artifact Pages |
| `.github/workflows/pages.yml` | Build + deploy |

Sections HTML (`id`) calquées sur QGIS Service : `promesse`, `parcours`, `stack`, `journal` (+ `fonctionnalites`, `usages`).

## Local

```bash
node site/generate.mjs
node --test site/generate.test.mjs
```

Ne pas confondre avec `templates/landing.html` (page runtime du service `/`) ni avec `docs/` (doc technique éventuelle).
