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


# ── Mode mono-utilisateur ────────────────────────────────────────────────────

def test_mode_mono_resout_l_instance_locale(monkeypatch):
    """En mono, l'instance est jointe sur localhost sans passer par Docker."""
    monkeypatch.setattr(main_mcp, "MULTI_USER_MODE", False)
    hote, api, flux, novnc = main_mcp._points_d_acces("peu-importe")
    assert (hote, api, flux, novnc) == ("localhost", 8080, 8081, 6080)


def test_mode_multi_sans_session_leve(monkeypatch):
    monkeypatch.setattr(main_mcp, "MULTI_USER_MODE", True)
    monkeypatch.setattr(main_mcp.container_manager, "get_session", lambda uid: None)
    with pytest.raises(Exception, match="Aucune session active"):
        main_mcp._points_d_acces("inconnu")


def test_sante_annonce_le_mode(client):
    d = client.get("/health").json()
    assert d["status"] == "ok"
    assert isinstance(d["multi_user"], bool)
    assert d["protocolVersion"] == main_mcp.PROTOCOL_VERSION


def test_disponibilite_distincte_de_la_vie(client, monkeypatch):
    """/health dit que le serveur repond, /health/ready que Blender repond."""
    monkeypatch.setattr(main_mcp, "MULTI_USER_MODE", True)
    monkeypatch.setattr(main_mcp.container_manager, "docker_client", None)
    r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not-ready"
    # la sonde de vie, elle, reste satisfaite : inutile de tuer le pod
    assert client.get("/health").status_code == 200

    monkeypatch.setattr(main_mcp.container_manager, "docker_client", object())
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


# ── Rendu des gabarits ───────────────────────────────────────────────────────

def test_canvas_rend_la_page_en_mode_mono(client, cle, monkeypatch):
    """Garde-fou contre la signature de TemplateResponse.

    Starlette 1.x a retire la forme TemplateResponse(nom, contexte) : elle y
    echoue sur « unhashable type: dict », le contexte etant pris pour une cle
    de cache. Le defaut ne s'est vu qu'en deployant, l'image installant des
    paquets plus recents que l'environnement local.
    """
    monkeypatch.setattr(main_mcp, "MULTI_USER_MODE", False)
    r = client.get(f"/canvas?token={cle}")
    assert r.status_code == 200, r.text[:300]
    assert "/static/novnc/core/rfb.js" in r.text


def test_accueil_rend_la_page(client):
    r = client.get("/")
    assert r.status_code == 200


# ── Authentification des canaux media ────────────────────────────────────────
#
# Ces deux routes portent l'identifiant utilisateur dans le chemin. Elles ne
# verifiaient rien : en mode mono, ou la resolution ignore l'identifiant,
# /ws/<n-importe-quoi> ouvrait le clavier et la souris de Blender a tout
# venant, et /stream/<n-importe-quoi> son ecran. Constate sur le service
# public le 08/09/2026.

def test_flux_refuse_sans_jeton(client):
    assert client.get("/stream/utilisateur-invente").status_code == 401


def test_flux_refuse_un_autre_utilisateur(client, cle, monkeypatch):
    monkeypatch.setattr(main_mcp, "MULTI_USER_MODE", False)
    r = client.get("/stream/quelqu-un-d-autre", headers={"Authorization": f"Bearer {cle}"})
    assert r.status_code == 401, "un porteur valide ne doit pas voir l'ecran d'un autre"


def test_websocket_vnc_refuse_sans_jeton(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/utilisateur-invente"):
            pass
    assert excinfo.value.code == 4401


def test_websocket_vnc_refuse_un_autre_utilisateur(client, cle):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/ws/quelqu-un-d-autre?token={cle}"):
            pass
    assert excinfo.value.code == 4401


def test_canvas_pose_le_cookie_du_websocket(client, cle, monkeypatch):
    """Sans ce cookie le canvas ne peut plus s'authentifier : un navigateur ne
    pose pas d'en-tete Authorization sur un WebSocket."""
    monkeypatch.setattr(main_mcp, "MULTI_USER_MODE", False)
    r = client.get(f"/canvas?token={cle}")
    assert r.status_code == 200
    biscuit = r.cookies.get("blender_token")
    assert biscuit == cle
    entete = r.headers.get("set-cookie", "")
    assert "httponly" in entete.lower(), "le jeton doit rester hors de portee du JavaScript"
    assert "samesite=strict" in entete.lower()


# ── Cles scopees ─────────────────────────────────────────────────────────────
#
# Une cle maitresse identifie une personne, une cle scopee identifie un agent.
# Sans elles, une cle qui fuit oblige a tout faire tourner, et on ne peut
# confier a un participant d'atelier qu'un pouvoir complet — dont
# execute_python, c'est-a-dire l'execution de code dans le container.

def _maitre(cle):
    return {"Authorization": f"Bearer {cle}", "Content-Type": "application/json"}


def test_cle_scopee_ne_voit_que_ses_outils(client, cle):
    r = client.post("/api/keys", headers=_maitre(cle),
                    json={"label": "lecture seule", "tools": ["list_objects", "get_scene_info"]})
    assert r.status_code == 200
    sk = r.json()["api_key"]
    assert sk.startswith("blender_sk_")

    outils = client.post("/mcp", headers=_maitre(sk),
                         json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
                         ).json()["result"]["tools"]
    assert {o["name"] for o in outils} == {"list_objects", "get_scene_info"}


def test_cle_scopee_refusee_sur_un_outil_hors_portee(client, cle):
    sk = client.post("/api/keys", headers=_maitre(cle),
                     json={"tools": ["list_objects"]}).json()["api_key"]
    r = client.post("/mcp", headers=_maitre(sk),
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                          "params": {"name": "execute_python", "arguments": {"code": "pass"}}})
    assert r.status_code == 200
    assert "hors de la portee" in r.json()["error"]["message"]


def test_cle_scopee_ne_peut_pas_emettre_de_cle(client, cle):
    """Sans cela, une cle restreinte se delivrerait une cle complete."""
    sk = client.post("/api/keys", headers=_maitre(cle), json={"tools": ["list_objects"]}).json()["api_key"]
    assert client.post("/api/keys", headers=_maitre(sk), json={}).status_code == 403
    assert client.get("/api/keys", headers=_maitre(sk)).status_code == 403


def test_revocation_immediate(client, cle):
    sk = client.post("/api/keys", headers=_maitre(cle), json={"label": "jetable"}).json()["api_key"]
    assert client.post("/mcp", headers=_maitre(sk),
                       json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
                       ).status_code == 200

    ident = next(k["id"] for k in client.get("/api/keys", headers=_maitre(cle)).json()["keys"]
                 if k["label"] == "jetable")
    assert client.delete(f"/api/keys/{ident}", headers=_maitre(cle)).status_code == 204
    assert client.post("/mcp", headers=_maitre(sk),
                       json={"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}}
                       ).status_code == 401


def test_outil_inconnu_refuse_a_l_emission(client, cle):
    r = client.post("/api/keys", headers=_maitre(cle), json={"tools": ["outil_qui_n_existe_pas"]})
    assert r.status_code == 400
    assert "inconnus" in r.json()["detail"]


def test_cle_expiree_ne_vaut_plus_rien(client, cle):
    import main_mcp as m
    sk = client.post("/api/keys", headers=_maitre(cle),
                     json={"label": "courte", "ttl_seconds": 3600}).json()["api_key"]
    from datetime import datetime, timedelta
    m.auth_manager.scoped[sk]["expires_at"] = (datetime.now() - timedelta(seconds=1)).isoformat()
    assert client.post("/mcp", headers=_maitre(sk),
                       json={"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}}
                       ).status_code == 401
