"""Couche guidance L1–L3 : skills, recipes, prompts, contexte."""

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["AUTH_DATA_FILE"] = str(Path(tempfile.mkdtemp()) / "guidance_auth.json")

import main_mcp  # noqa: E402
from src.guidance import GuidanceCatalog, build_context, substitute_params  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(main_mcp.app)


@pytest.fixture(scope="module")
def cle(client):
    r = client.post(
        "/api/auth/register",
        json={"email": f"guidance-{uuid.uuid4().hex[:8]}@example.com", "password": "motdepasse"},
    )
    assert r.status_code == 200
    return r.json()["api_key"]


def _mcp(client, cle, method, params=None, sid=None):
    headers = {
        "Authorization": f"Bearer {cle}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if sid:
        headers["mcp-session-id"] = sid
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", headers=headers, json=body)


def test_catalog_charge_expertise():
    cat = GuidanceCatalog()
    assert "bpy-pitfalls" in cat.skills
    assert "clear_and_studio" in cat.recipes
    assert any(p["name"] == "demarrer_studio" for p in cat.prompts)


def test_substitute_params():
    assert substitute_params({"type": "$object_type"}, {"object_type": "CUBE"}) == {
        "type": "CUBE"
    }


def test_build_context_hint():
    ctx = build_context("light")
    assert ctx["phase"] == "light"
    assert "lighting" in ctx["hint"] or "studio" in ctx["hint"].lower()


def test_initialize_mentionne_expertise(client, cle):
    r = _mcp(
        client, cle, "initialize",
        {"protocolVersion": "2025-06-18", "clientInfo": {"name": "t", "version": "1"}},
    )
    assert r.status_code == 200
    inst = r.json()["result"]["instructions"]
    assert "skill://" in inst
    assert "list_recipes" in inst
    assert "prompts" in r.json()["result"]["capabilities"]


def test_resources_incluent_skills(client, cle):
    init = _mcp(
        client, cle, "initialize",
        {"protocolVersion": "2025-06-18", "clientInfo": {"name": "t", "version": "1"}},
    )
    sid = init.headers["mcp-session-id"]
    r = _mcp(client, cle, "resources/list", {}, sid=sid)
    uris = [x["uri"] for x in r.json()["result"]["resources"]]
    assert "skill://bpy-pitfalls" in uris
    read = _mcp(
        client, cle, "resources/read",
        {"uri": "skill://bpy-pitfalls"}, sid=sid,
    )
    text = read.json()["result"]["contents"][0]["text"]
    assert "execute_python" in text or "bpy" in text


def test_prompts_list_et_get(client, cle):
    init = _mcp(
        client, cle, "initialize",
        {"protocolVersion": "2025-06-18", "clientInfo": {"name": "t", "version": "1"}},
    )
    sid = init.headers["mcp-session-id"]
    listed = _mcp(client, cle, "prompts/list", {}, sid=sid)
    names = {p["name"] for p in listed.json()["result"]["prompts"]}
    assert "demarrer_studio" in names
    got = _mcp(
        client, cle, "prompts/get",
        {"name": "demarrer_studio", "arguments": {"object_type": "MONKEY"}},
        sid=sid,
    )
    msg = got.json()["result"]["messages"][0]["content"]["text"]
    assert "MONKEY" in msg


def test_list_recipes_tool(client, cle):
    init = _mcp(
        client, cle, "initialize",
        {"protocolVersion": "2025-06-18", "clientInfo": {"name": "t", "version": "1"}},
    )
    sid = init.headers["mcp-session-id"]
    r = _mcp(
        client, cle, "tools/call",
        {"name": "list_recipes", "arguments": {}},
        sid=sid,
    )
    text = r.json()["result"]["content"][0]["text"]
    assert "clear_and_studio" in text
    assert "_context" in text
