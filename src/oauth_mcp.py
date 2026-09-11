"""OAuth 2.1 MCP (AS + RS) — découverte, DCR, authorize, token.

Calqué sur le hub QGIS SSPCloud pour Claude Desktop / claude.ai.
L'access_token émis est l'api_key Blender existante : le Bearer /mcp
ne change pas.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
from typing import Callable, Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

COOKIE_NAME = "blender_token"
CODE_TTL_S = 600
TOKEN_TTL_S = 90 * 24 * 3600

router = APIRouter(tags=["oauth-mcp"])

_pending_codes: dict = {}
_auth_manager = None
_public_base_url: Optional[Callable] = None
_templates: Optional[Jinja2Templates] = None


def mount_oauth(app, *, auth_manager, public_base_url, templates=None) -> None:
    """Branche le routeur OAuth sur l'app FastAPI."""
    global _auth_manager, _public_base_url, _templates
    _auth_manager = auth_manager
    _public_base_url = public_base_url
    _templates = templates
    app.include_router(router)


def resource_metadata_url(base: str) -> str:
    return f"{base.rstrip('/')}/.well-known/oauth-protected-resource"


def www_authenticate_header(base: str) -> str:
    rm = resource_metadata_url(base)
    return f'Bearer resource_metadata="{rm}"'


def _base(request: Request) -> str:
    if _public_base_url is None:
        return str(request.base_url).rstrip("/")
    return _public_base_url(request).rstrip("/")


def _purge_codes() -> None:
    now = time.time()
    for k in [k for k, v in _pending_codes.items() if v["expires"] < now]:
        del _pending_codes[k]


async def _user_from_api_key(api_key: str):
    if not api_key or _auth_manager is None:
        return None
    return await _auth_manager.verify_api_key(api_key.strip())


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource(request: Request):
    base = _base(request)
    return JSONResponse({
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["blender"],
    })


@router.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server(request: Request):
    base = _base(request)
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "grant_types_supported": ["authorization_code", "client_credentials", "refresh_token"],
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
        "scopes_supported": ["blender"],
    })


@router.post("/oauth/register")
async def oauth_register(request: Request):
    """Dynamic Client Registration (RFC 7591) — permissif, comme QGIS hub."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    client_id = f"mcp-{secrets.token_hex(8)}"
    return JSONResponse({
        "client_id": client_id,
        "client_id_issued_at": int(time.time()),
        "redirect_uris": body.get("redirect_uris", []),
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": body.get("client_name", "MCP Client"),
    }, status_code=201)


@router.get("/authorize", response_class=HTMLResponse)
async def oauth_authorize(
    request: Request,
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    scope: str = "",
    error: str = "",
):
    _purge_codes()
    if response_type != "code":
        raise HTTPException(400, "response_type non supporté")
    if code_challenge_method and code_challenge_method != "S256":
        raise HTTPException(400, "Seul S256 est supporté pour PKCE")

    cookie_key = request.cookies.get(COOKIE_NAME, "")
    user = await _user_from_api_key(cookie_key) if cookie_key else None
    if user and redirect_uri:
        return _issue_auth_code(
            cookie_key, code_challenge, redirect_uri, state, set_cookie=False
        )

    params = {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method or "S256",
    }
    if scope:
        params["scope"] = scope

    if _templates is not None:
        return _templates.TemplateResponse(
            request,
            "oauth_authorize.html",
            {
                "error": error,
                "confirm_query": urllib.parse.urlencode(params),
                "public_base": _base(request),
            },
        )

    err = "<p>Clé invalide.</p>" if error == "invalid_key" else ""
    return HTMLResponse(
        f"<html><body><h1>Autoriser BlenderRemoteMCP</h1>{err}"
        f"<form method='post' action='/authorize/confirm?{urllib.parse.urlencode(params)}'>"
        f"<input name='api_key' type='password' required placeholder='blender_…'>"
        f"<button type='submit'>Autoriser</button></form></body></html>"
    )


@router.post("/authorize/confirm", response_class=HTMLResponse)
async def oauth_authorize_confirm(
    request: Request,
    api_key: str = Form(...),
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    scope: str = "",
):
    key = api_key.strip()
    user = await _user_from_api_key(key)
    if not user:
        q = urllib.parse.urlencode({
            "response_type": response_type,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "error": "invalid_key",
        })
        return RedirectResponse(f"/authorize?{q}", status_code=302)

    if not redirect_uri:
        raise HTTPException(400, "redirect_uri requis")

    return _issue_auth_code(
        key, code_challenge, redirect_uri, state, set_cookie=True, request=request
    )


def _issue_auth_code(
    api_key: str,
    code_challenge: str,
    redirect_uri: str,
    state: str,
    *,
    set_cookie: bool,
    request: Request = None,
) -> RedirectResponse:
    code = secrets.token_urlsafe(32)
    _pending_codes[code] = {
        "api_key": api_key,
        "code_challenge": code_challenge or "",
        "redirect_uri": redirect_uri,
        "expires": time.time() + CODE_TTL_S,
    }
    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    resp = RedirectResponse(
        f"{redirect_uri}{sep}{urllib.parse.urlencode(params)}",
        status_code=302,
    )
    if set_cookie and request is not None:
        resp.set_cookie(
            COOKIE_NAME,
            api_key,
            httponly=True,
            samesite="lax",
            secure=(request.url.scheme == "https"),
            max_age=TOKEN_TTL_S,
        )
    return resp


@router.post("/oauth/token")
async def oauth_token(
    request: Request,
    grant_type: str = Form(...),
    code: str = Form(None),
    code_verifier: str = Form(None),
    redirect_uri: str = Form(None),
    client_id: str = Form(None),
    client_secret: str = Form(None),
    refresh_token: str = Form(None),
):
    _purge_codes()

    if grant_type == "authorization_code":
        if not code or code not in _pending_codes:
            raise HTTPException(400, "Code invalide ou expiré")
        pending = _pending_codes.pop(code)
        if time.time() > pending["expires"]:
            raise HTTPException(400, "Code expiré")
        if redirect_uri and redirect_uri != pending.get("redirect_uri"):
            raise HTTPException(400, "redirect_uri invalide")

        if pending.get("code_challenge"):
            if not code_verifier:
                raise HTTPException(400, "code_verifier requis")
            if _pkce_challenge(code_verifier) != pending["code_challenge"]:
                raise HTTPException(400, "PKCE invalide")

        return JSONResponse({
            "access_token": pending["api_key"],
            "token_type": "bearer",
            "expires_in": TOKEN_TTL_S,
            "refresh_token": pending["api_key"],
            "scope": "blender",
        })

    if grant_type == "client_credentials":
        secret = (client_secret or "").strip()
        if not secret:
            raise HTTPException(400, "client_secret requis")
        user = await _user_from_api_key(secret)
        if not user:
            raise HTTPException(401, "client_secret invalide")
        return JSONResponse({
            "access_token": secret,
            "token_type": "bearer",
            "expires_in": TOKEN_TTL_S,
            "scope": "blender",
        })

    if grant_type == "refresh_token":
        token = (refresh_token or client_secret or "").strip()
        user = await _user_from_api_key(token)
        if not user:
            raise HTTPException(401, "refresh_token invalide")
        return JSONResponse({
            "access_token": token,
            "token_type": "bearer",
            "expires_in": TOKEN_TTL_S,
            "refresh_token": token,
            "scope": "blender",
        })

    raise HTTPException(400, f"grant_type non supporté: {grant_type}")
