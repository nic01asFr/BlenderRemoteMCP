"""OAuth MCP (AS + RS) — découverte, DCR, authorize, token, WWW-Authenticate."""

import base64
import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

os.environ["AUTH_DATA_FILE"] = str(Path(tempfile.mkdtemp()) / "oauth_auth.json")

import main_mcp  # noqa: E402
from src import oauth_mcp  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(main_mcp.app)


@pytest.fixture(scope="module")
def cle(client):
    r = client.post(
        "/api/auth/register",
        json={"email": f"oauth-{uuid.uuid4().hex[:8]}@example.com", "password": "motdepasse"},
    )
    assert r.status_code == 200, r.text
    return r.json()["api_key"]


@pytest.fixture(autouse=True)
def codes_propres():
    oauth_mcp._pending_codes.clear()
    yield
    oauth_mcp._pending_codes.clear()


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def test_protected_resource_metadata(client):
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    d = r.json()
    assert d["resource"].endswith("/mcp")
    assert len(d["authorization_servers"]) == 1
    assert d["bearer_methods_supported"] == ["header"]


def test_authorization_server_metadata(client):
    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    d = r.json()
    assert d["authorization_endpoint"].endswith("/authorize")
    assert d["token_endpoint"].endswith("/oauth/token")
    assert d["registration_endpoint"].endswith("/oauth/register")
    assert "S256" in d["code_challenge_methods_supported"]
    assert "authorization_code" in d["grant_types_supported"]


def test_dynamic_client_registration(client):
    r = client.post(
        "/oauth/register",
        json={
            "client_name": "Claude",
            "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
        },
    )
    assert r.status_code == 201
    d = r.json()
    assert d["client_id"].startswith("mcp-")
    assert d["token_endpoint_auth_method"] == "none"


def test_authorize_page_rend_le_formulaire(client):
    r = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "mcp-test",
            "redirect_uri": "https://example.com/cb",
            "state": "abc",
            "code_challenge": "x",
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code == 200
    assert "Autoriser" in r.text
    assert "blender_" in r.text


def test_authorization_code_flow_avec_pkce(client, cle):
    verifier, challenge = _pkce_pair()
    redirect = "https://example.com/cb"
    r = client.post(
        "/authorize/confirm",
        data={"api_key": cle},
        params={
            "response_type": "code",
            "client_id": "mcp-test",
            "redirect_uri": redirect,
            "state": "st1",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(redirect)
    qs = parse_qs(urlparse(loc).query)
    assert qs["state"] == ["st1"]
    code = qs["code"][0]

    tok = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect,
            "client_id": "mcp-test",
        },
    )
    assert tok.status_code == 200, tok.text
    body = tok.json()
    assert body["access_token"] == cle
    assert body["token_type"].lower() == "bearer"

    # Le jeton OAuth ouvre /mcp
    mcp = client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {body['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "oauth-test", "version": "1"},
            },
        },
    )
    assert mcp.status_code == 200
    assert mcp.json()["result"]["protocolVersion"] == "2025-06-18"


def test_pkce_invalide_refuse(client, cle):
    _, challenge = _pkce_pair()
    r = client.post(
        "/authorize/confirm",
        data={"api_key": cle},
        params={
            "redirect_uri": "https://example.com/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    bad = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": "verifier-incorrect-volontairement",
            "redirect_uri": "https://example.com/cb",
        },
    )
    assert bad.status_code == 400


def test_client_credentials_avec_api_key(client, cle):
    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "nic01asfr",
            "client_secret": cle,
        },
    )
    assert r.status_code == 200
    assert r.json()["access_token"] == cle


def test_mcp_401_porte_www_authenticate(client):
    r = client.post(
        "/mcp",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert r.status_code == 401
    wa = r.headers.get("www-authenticate", "")
    assert "resource_metadata=" in wa
    assert "oauth-protected-resource" in wa


def test_cle_invalide_sur_authorize_renvoie_au_formulaire(client):
    r = client.post(
        "/authorize/confirm",
        data={"api_key": "blender_fausse"},
        params={"redirect_uri": "https://example.com/cb", "code_challenge": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "/authorize?" in r.headers["location"]
    assert "invalid_key" in r.headers["location"]
