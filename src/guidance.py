"""Couche L1–L3 : skills, recipes, prompts, contexte de guidance.

Charge le dossier ``expertise/`` à côté du code (ou EXPERTISE_DIR).
Patron calqué sur BigQgisMCP / BigLocalApps.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(os.environ.get(
    "EXPERTISE_DIR",
    Path(__file__).resolve().parents[1] / "expertise",
))

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_skill(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    meta: Dict[str, str] = {}
    body = text
    m = _FRONT_MATTER.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = text[m.end():]
    sid = meta.get("id") or path.stem.replace("_", "-")
    return {
        "id": sid,
        "title": meta.get("title") or sid,
        "summary": meta.get("summary") or "",
        "uri": f"skill://{sid}",
        "mimeType": "text/markdown",
        "text": body.strip() + "\n",
        "path": str(path),
    }


class GuidanceCatalog:
    """Catalogue chargé une fois (reload possible via reload())."""

    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self.skills: Dict[str, Dict[str, Any]] = {}
        self.recipes: Dict[str, Dict[str, Any]] = {}
        self.prompts: List[Dict[str, Any]] = []
        self.reload()

    def reload(self) -> None:
        self.skills = {}
        skills_dir = self.root / "skills"
        if skills_dir.is_dir():
            for path in sorted(skills_dir.glob("*.md")):
                skill = _parse_skill(path)
                self.skills[skill["id"]] = skill

        self.recipes = {}
        recipes_dir = self.root / "recipes"
        if recipes_dir.is_dir():
            for path in sorted(recipes_dir.glob("*.json")):
                data = json.loads(path.read_text(encoding="utf-8"))
                rid = data.get("id") or path.stem
                data["id"] = rid
                self.recipes[rid] = data

        self.prompts = []
        prompts_file = self.root / "prompts" / "prompts.json"
        if prompts_file.is_file():
            self.prompts = json.loads(prompts_file.read_text(encoding="utf-8"))

    def skill_resources(self) -> List[Dict[str, Any]]:
        return [
            {
                "uri": s["uri"],
                "name": s["title"],
                "description": s["summary"] or s["title"],
                "mimeType": "text/markdown",
            }
            for s in self.skills.values()
        ]

    def read_skill(self, uri: str) -> Optional[Dict[str, Any]]:
        if not uri.startswith("skill://"):
            return None
        sid = uri[len("skill://"):]
        return self.skills.get(sid)

    def list_recipes(self, tag: str = "") -> List[Dict[str, Any]]:
        out = []
        for r in self.recipes.values():
            tags = r.get("tags") or []
            if tag and tag not in tags:
                continue
            out.append({
                "id": r["id"],
                "name": r.get("name", r["id"]),
                "description": r.get("description", ""),
                "tags": tags,
                "parameters": r.get("parameters") or {},
            })
        return out

    def get_recipe(self, recipe_id: str) -> Optional[Dict[str, Any]]:
        return self.recipes.get(recipe_id)

    def list_prompts(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": p["name"],
                "description": p.get("description", ""),
                "arguments": p.get("arguments") or [],
            }
            for p in self.prompts
        ]

    def get_prompt(self, name: str, arguments: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        arguments = arguments or {}
        for p in self.prompts:
            if p["name"] != name:
                continue
            messages = []
            for msg in p.get("messages") or []:
                content = msg.get("content") or {}
                text = content.get("text", "") if isinstance(content, dict) else str(content)
                for k, v in arguments.items():
                    text = text.replace("{{" + k + "}}", str(v))
                # défauts d'arguments optionnels
                text = re.sub(r"\{\{[a-zA-Z0-9_]+\}\}", "", text)
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": {"type": "text", "text": text},
                })
            return {
                "description": p.get("description", ""),
                "messages": messages,
            }
        return None


def substitute_params(value: Any, params: Dict[str, Any]) -> Any:
    """Remplace ``$key`` (valeur entière) et ``{{key}}`` (dans une longue chaîne).

    Pour ``{{key}}``, on utilise ``repr(v)`` afin d'injecter proprement dans
    du ``execute_python`` (nombres, chaînes, listes).
    """
    if isinstance(value, str):
        if value.startswith("$") and len(value) > 1 and "{{" not in value:
            key = value[1:]
            if key in params:
                return params[key]
        if params and "{{" in value:
            out = value
            for key, raw in params.items():
                out = out.replace("{{" + key + "}}", repr(raw))
            return out
        return value
    if isinstance(value, dict):
        return {k: substitute_params(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute_params(v, params) for v in value]
    return value


def build_context(phase: str = "model", *, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Contexte léger joint aux réponses (patron BigQgisMCP / BigLocalApps)."""
    hints = {
        "setup": "Prefere clear_and_studio ou initialize_scene ; lis skill://bpy-pitfalls.",
        "model": "Organise en collections ; skill://modelling ; GN -> skill://geometry-nodes / recipes gn_*.",
        "shade": "mat_apply_preset / skill://materials ; evite d'improviser le Principled a la main.",
        "light": "setup_studio_lighting puis skill://lighting.",
        "render": "detect_gpu / configure_render ; skill://camera-render ; screenshot puis canvas.",
        "review": "get_screenshot + get_canvas_url pour l'utilisateur.",
    }
    ctx = {
        "phase": phase,
        "hint": hints.get(phase, hints["model"]),
        "skills_index": "resources/list -> skill://...",
        "recipes_index": "list_recipes",
    }
    if extra:
        ctx.update(extra)
    return ctx


def infer_phase(tool_name: str) -> str:
    if tool_name in {"clear_scene", "initialize_scene", "setup_studio_lighting", "setup_camera"}:
        return "setup"
    if tool_name in {"set_material", "create_material", "list_materials"} or "material" in tool_name:
        return "shade"
    if "light" in tool_name or tool_name == "setup_studio_lighting":
        return "light"
    if tool_name in {"configure_render", "detect_gpu", "get_screenshot", "get_canvas_url"}:
        return "render" if tool_name != "get_screenshot" else "review"
    if tool_name in {"get_scene_info", "list_objects", "list_meshes"}:
        return "review"
    return "model"


# Singleton pratique pour main_mcp
catalog = GuidanceCatalog()
