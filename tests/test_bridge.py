"""Tests du pont entre api_server et Blender.

Ce que ces tests prouvent, sans Blender :

  - le cadrage en longueur prefixee tient sur des charges utiles superieures
    a un buffer de lecture ;
  - une commande est executee sur le thread qui pompe la file, JAMAIS sur le
    thread du socket — c'est la correction centrale, bpy n'etant pas
    thread-safe ;
  - une connexion porte plusieurs commandes a la suite ;
  - l'absence de reponse du thread principal produit une erreur explicite et
    non un blocage.

L'hote Windows n'expose pas AF_UNIX : les tests se rabattent sur une boucle
locale TCP. Le chemin AF_UNIX de production est verifie dans le container.
"""

import importlib.util
import json
import socket
import struct
import sys
import threading
import time
import types
from pathlib import Path

import pytest

ADDON = Path(__file__).resolve().parents[1] / "docker" / "blender-canvas" / "blender_addon.py"


def _stub_bpy():
    """Minimal bpy pour permettre l'import du module hors de Blender."""
    bpy = types.ModuleType("bpy")

    timers = types.SimpleNamespace(
        registered=[],
        register=lambda fn, **kw: timers.registered.append(fn),
        unregister=lambda fn: timers.registered.remove(fn),
        is_registered=lambda fn: fn in timers.registered,
    )
    bpy.app = types.SimpleNamespace(timers=timers)
    bpy.data = types.SimpleNamespace(objects=[], materials=[], meshes=[], collections=[])
    bpy.context = types.SimpleNamespace(scene=None)
    bpy.ops = types.SimpleNamespace()
    return bpy


@pytest.fixture(scope="module")
def addon():
    sys.modules.setdefault("bpy", _stub_bpy())
    spec = importlib.util.spec_from_file_location("blender_addon_under_test", ADDON)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HandlerEspion:
    """Enregistre le thread d'execution et compte les appels."""

    def __init__(self):
        self.thread_ids = []
        self.commandes = []
        self.appels = threading.Semaphore(0)

    def handle_command(self, command):
        self.thread_ids.append(threading.get_ident())
        self.commandes.append(command)
        self.appels.release()
        if command.get("action") == "boom":
            raise RuntimeError("echec volontaire")
        return {"success": True, "echo": command.get("payload", command.get("action"))}


@pytest.fixture
def pont(addon):
    """Serveur demarre sur une boucle locale, file non pompee par defaut."""
    espion = HandlerEspion()
    addon._handler = espion
    addon._running = True
    # Repartir d'une file vide entre deux tests
    while not addon._request_queue.empty():
        addon._request_queue.get_nowait()
    addon._response_queues.clear()

    serveur = addon.SocketServer("/tmp/test_bridge.sock", family=socket.AF_INET)
    thread = threading.Thread(target=serveur.start, daemon=True)
    thread.start()
    assert serveur._ready.wait(timeout=5), "le serveur n'a pas ouvert son socket"

    yield serveur, espion, addon

    addon._running = False
    serveur.stop()
    thread.join(timeout=3)


def _connecter(serveur):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(10)
    client.connect(serveur.address)
    return client


def _envoyer(client, commande):
    charge = json.dumps(commande).encode("utf-8")
    client.sendall(struct.pack(">I", len(charge)) + charge)


def _recevoir(client):
    entete = client.recv(4)
    assert len(entete) == 4, "entete tronquee"
    (taille,) = struct.unpack(">I", entete)
    reste = b""
    while len(reste) < taille:
        morceau = client.recv(taille - len(reste))
        assert morceau, "corps tronque"
        reste += morceau
    return json.loads(reste.decode("utf-8"))


def _pomper(addon, espion, attendus=1, delai=5.0):
    """Joue le role du thread principal de Blender."""
    limite = time.time() + delai
    obtenus = 0
    while obtenus < attendus and time.time() < limite:
        avant = len(espion.thread_ids)
        addon._poll_queue()
        obtenus += len(espion.thread_ids) - avant
        if obtenus < attendus:
            time.sleep(0.01)
    return obtenus


def test_aller_retour_simple(pont):
    serveur, espion, addon = pont
    client = _connecter(serveur)
    _envoyer(client, {"action": "ping"})
    assert _pomper(addon, espion) == 1
    reponse = _recevoir(client)
    assert reponse == {"success": True, "echo": "ping"}
    client.close()


def test_execution_sur_le_thread_qui_pompe(pont):
    """Le coeur de la correction : bpy ne doit jamais tourner sur le socket."""
    serveur, espion, addon = pont
    client = _connecter(serveur)
    _envoyer(client, {"action": "ping"})
    assert _pomper(addon, espion) == 1
    _recevoir(client)
    client.close()

    assert espion.thread_ids == [threading.get_ident()], (
        "la commande n'a pas ete executee sur le thread appelant _poll_queue"
    )


def test_plusieurs_commandes_sur_une_connexion(pont):
    serveur, espion, addon = pont
    client = _connecter(serveur)
    for i in range(3):
        _envoyer(client, {"action": "ping", "payload": i})
        assert _pomper(addon, espion) == 1
        assert _recevoir(client)["echo"] == i
    client.close()
    assert len(espion.commandes) == 3


def test_charge_utile_volumineuse(pont):
    """Une capture base64 depasse largement un buffer de 4096 octets."""
    serveur, espion, addon = pont
    gros = "x" * 500_000
    client = _connecter(serveur)
    _envoyer(client, {"action": "ping", "payload": gros})
    assert _pomper(addon, espion) == 1
    assert _recevoir(client)["echo"] == gros
    client.close()


def test_erreur_du_handler_remonte_sans_tuer_le_pont(pont):
    serveur, espion, addon = pont
    client = _connecter(serveur)
    _envoyer(client, {"action": "boom"})
    assert _pomper(addon, espion) == 1
    reponse = _recevoir(client)
    assert reponse["success"] is False
    assert "echec volontaire" in reponse["error"]
    assert "traceback" in reponse

    # le pont reste utilisable
    _envoyer(client, {"action": "ping"})
    assert _pomper(addon, espion) == 1
    assert _recevoir(client)["success"] is True
    client.close()


def test_timeout_si_le_thread_principal_ne_repond_pas(pont):
    """Sans pompage, la reponse doit etre une erreur explicite, pas un blocage."""
    serveur, espion, addon = pont
    client = _connecter(serveur)
    _envoyer(client, {"action": "ping", "timeout": 0.3})
    reponse = _recevoir(client)
    assert reponse["success"] is False
    assert "Timeout" in reponse["error"]
    client.close()


def test_serialisation_des_types_blender(addon):
    """_serialize doit rendre des listes, pas des chaines illisibles."""

    class FauxVector:
        def to_list(self):
            return [1.0, 2.0, 3.0]

    class FauxMatrix:
        def to_tuple(self):
            return ((1, 0), (0, 1))

    assert addon._serialize(FauxVector()) == [1.0, 2.0, 3.0]
    assert addon._serialize(FauxMatrix()) == [(1, 0), (0, 1)]
    assert addon._serialize({"v": FauxVector()}) == {"v": [1.0, 2.0, 3.0]}
    assert addon._serialize([1, "a", None, True]) == [1, "a", None, True]
    assert addon._serialize(object()).startswith("<object")
