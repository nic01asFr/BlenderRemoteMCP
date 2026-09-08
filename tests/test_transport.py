"""Tests du transport MCP Streamable HTTP.

Ce que ces tests prouvent, sans Docker ni Blender :

  - la negociation de version de protocole ;
  - qu'une session est ouverte, portee par l'en-tete mcp-session-id, et que
    DEUX sessions coexistent pour le meme utilisateur — c'est la propriete qui
    permet a plusieurs agents de travailler sur une meme instance ;
  - que la reponse part en SSE quand le client l'accepte, en JSON sinon ;
  - qu'une notification est acquittee par 202 sans corps ;
  - que DELETE ferme la session sans toucher aux autres ;
  - qu'une session explicitement inconnue est refusee, mais qu'un client sans
    session reste accepte.

Aucun appel d'outil ici : tools/call demande un container, il est verifie de
bout en bout separement.
"""

import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

# Isoler le magasin d'utilisateurs AVANT d'importer les modules applicatifs :
# src/auth.py lit AUTH_DATA_FILE au chargement.
os.environ["AUTH_DATA_FILE"] = str(Path(tempfile.mkdtemp()) / "auth_test.json")

from fastapi.testclient import TestClient  # noqa: E402

import main_mcp  # noqa: E402
from src.auth import UserCreate  # noqa: E402


@pytest.fixture(scope="module")
def client():
    # TestClient sans gestionnaire de contexte : le lifespan n'est pas joue,
    # donc aucune connexion a Docker n'est tentee.
    return TestClient(main_mcp.app)


@pytest.fixture(scope="module")
def cle(client):
    reponse = client.post(
        "/api/auth/register",
        json={"email": f"transport-{uuid.uuid4().hex[:8]}@example.com", "password": "motdepasse"},
    )
    assert reponse.status_code == 200, reponse.text
    return reponse.json()["api_key"]


@pytest.fixture(autouse=True)
def sessions_propres():
    main_mcp._sessions.clear()
    yield
    main_mcp._sessions.clear()


def _entetes(cle, session_id=None, sse=False):
    h = {"Authorization": f"Bearer {cle}", "Content-Type": "application/json"}
    if session_id:
        h["mcp-session-id"] = session_id
    h["Accept"] = "application/json, text/event-stream" if sse else "application/json"
    return h


def _initialiser(client, cle, version="2025-06-18", sse=False):
    return client.post(
        "/mcp",
        headers=_entetes(cle, sse=sse),
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": version, "clientInfo": {"name": "test", "version": "1"}},
        },
    )


# ── Metadonnees et authentification ──────────────────────────────────────────

def test_get_sans_sse_renvoie_les_metadonnees(client):
    r = client.get("/mcp")
    assert r.status_code == 200
    d = r.json()
    assert d["transport"] == "streamable-http"
    assert d["protocolVersion"] == main_mcp.PROTOCOL_VERSION
    assert "2024-11-05" in d["supportedProtocolVersions"]


def test_post_sans_authentification_refuse(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401


def test_cle_invalide_refusee(client):
    r = client.post(
        "/mcp",
        headers={"Authorization": "Bearer blender_inexistante"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert r.status_code == 401


# ── Negociation et sessions ──────────────────────────────────────────────────

def test_initialize_ouvre_une_session(client, cle):
    r = _initialiser(client, cle)
    assert r.status_code == 200
    session_id = r.headers.get("mcp-session-id")
    assert session_id, "l'en-tete mcp-session-id doit etre renvoye"
    assert session_id in main_mcp._sessions
    assert r.json()["result"]["protocolVersion"] == "2025-06-18"


def test_version_de_protocole_negociee(client, cle):
    """Une version connue est reprise, une version inconnue est corrigee."""
    assert _initialiser(client, cle, "2024-11-05").json()["result"]["protocolVersion"] == "2024-11-05"
    assert _initialiser(client, cle, "1999-01-01").json()["result"]["protocolVersion"] == main_mcp.PROTOCOL_VERSION


def test_deux_sessions_coexistent_pour_un_meme_utilisateur(client, cle):
    """La propriete centrale du lot : deux agents, une seule instance."""
    a = _initialiser(client, cle).headers["mcp-session-id"]
    b = _initialiser(client, cle).headers["mcp-session-id"]
    assert a != b
    assert {a, b} <= set(main_mcp._sessions)
    assert main_mcp._sessions[a]["user_id"] == main_mcp._sessions[b]["user_id"]

    # et les deux peuvent travailler
    for sid in (a, b):
        r = client.post("/mcp", headers=_entetes(cle, sid),
                        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert r.status_code == 200
        assert len(r.json()["result"]["tools"]) == 35


def test_session_inconnue_refusee_mais_absence_toleree(client, cle):
    _initialiser(client, cle)  # il faut au moins une session active
    r = client.post("/mcp", headers=_entetes(cle, "session-fantome"),
                    json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert r.status_code == 400
    assert "Session inconnue" in r.json()["error"]["message"]

    # sans en-tete, le client reste accepte
    r = client.post("/mcp", headers=_entetes(cle),
                    json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
    assert r.status_code == 200


def test_delete_ferme_une_seule_session(client, cle):
    a = _initialiser(client, cle).headers["mcp-session-id"]
    b = _initialiser(client, cle).headers["mcp-session-id"]
    r = client.delete("/mcp", headers=_entetes(cle, a))
    assert r.status_code == 204
    assert a not in main_mcp._sessions
    assert b in main_mcp._sessions


# ── Forme des reponses ───────────────────────────────────────────────────────

def test_reponse_sse_quand_le_client_l_accepte(client, cle):
    r = _initialiser(client, cle, sse=True)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers.get("x-accel-buffering") == "no", "nginx accumulerait le flux"
    corps = r.text
    assert corps.startswith("event: message\ndata: ")
    charge = json.loads(corps.split("data: ", 1)[1].strip())
    assert charge["result"]["serverInfo"]["name"] == "BlenderRemoteMCP"


def test_reponse_json_quand_le_client_ne_gere_pas_le_sse(client, cle):
    r = _initialiser(client, cle, sse=False)
    assert r.headers["content-type"].startswith("application/json")


def test_accept_sse_ne_se_laisse_pas_tromper():
    assert main_mcp._accepts_sse("application/json, text/event-stream")
    assert main_mcp._accepts_sse("text/event-stream;q=0.9")
    assert not main_mcp._accepts_sse("text/event-stream-autre")
    assert not main_mcp._accepts_sse("application/json")
    assert not main_mcp._accepts_sse("")


# ── Notifications et lots ────────────────────────────────────────────────────

def test_notification_acquittee_par_202(client, cle):
    session_id = _initialiser(client, cle).headers["mcp-session-id"]
    r = client.post("/mcp", headers=_entetes(cle, session_id),
                    json={"jsonrpc": "2.0", "method": "notifications/cancelled"})
    assert r.status_code == 202
    assert r.headers.get("mcp-session-id") == session_id
    assert r.content == b""


def test_lot_de_requetes_refuse(client, cle):
    r = client.post("/mcp", headers=_entetes(cle),
                    json=[{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
    assert r.status_code == 400
    assert "lots" in r.json()["error"]["message"].lower()


def test_corps_illisible_refuse(client, cle):
    r = client.post("/mcp", headers=_entetes(cle), content=b"{ pas du json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32700


# ── Peremption ───────────────────────────────────────────────────────────────

def test_les_sessions_inactives_sont_oubliees(client, cle):
    session_id = _initialiser(client, cle).headers["mcp-session-id"]
    main_mcp._sessions[session_id]["last_seen"] -= main_mcp.SESSION_IDLE_SECONDS + 1
    assert main_mcp._evict_idle_sessions() == 1
    assert session_id not in main_mcp._sessions
