# Design — OAuth MCP (AS + RS) pour BlenderRemoteMCP

**Date :** 2026-09-11  
**Statut :** approuvé (approche module `src/oauth_mcp.py`, modèle QGIS hub)

## Objectif

Permettre à Claude Desktop / claude.ai (connecteur MCP distant) de découvrir et d’autoriser l’accès via OAuth 2.1 + PKCE, tout en conservant le Bearer `blender_…` direct.

## Architecture

Le service est **Authorization Server et Resource Server** (comme QGIS hub).

- Module : `src/oauth_mcp.py` (routes + état codes PKCE)
- Branchement : `main_mcp.py` (include router, WWW-Authenticate sur 401 `/mcp`)
- UI : `templates/oauth_authorize.html`
- Validation jeton : inchangée (`auth_manager.verify_api_key` / scoped) — l’`access_token` OAuth **est** l’api_key

## Endpoints

| Méthode | Chemin | Spéc |
|---------|--------|------|
| GET | `/.well-known/oauth-protected-resource` | RFC 9728 |
| GET | `/.well-known/oauth-authorization-server` | RFC 8414 |
| POST | `/oauth/register` | RFC 7591 DCR permissif |
| GET | `/authorize` | Formulaire / cookie → code |
| POST | `/authorize/confirm` | Valide clé `blender_…` |
| POST | `/oauth/token` | code+PKCE ou client_credentials |

## Comportement

1. Client découvre PRM → AS metadata → DCR optionnel → `/authorize`
2. Utilisateur colle sa clé (ou cookie `blender_token`) → redirect `code`
3. Token endpoint renvoie `access_token` = api_key, `token_type=bearer`
4. Appels `/mcp` avec `Authorization: Bearer <api_key>` comme aujourd’hui
5. 401 `/mcp` inclut `WWW-Authenticate: Bearer resource_metadata="<base>/.well-known/oauth-protected-resource"`

## Hors scope

- AS externe (Keycloak)
- Rotation de clés OAuth distinctes des api_key
- CIMD (Client ID Metadata Documents) — DCR suffit pour Claude aujourd’hui

## Tests

Découverte, register, authorize+confirm+token (PKCE), client_credentials, WWW-Authenticate, Bearer existant inchangé.
