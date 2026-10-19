# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Write the game package ``<game_dir>/mixar_export/`` (contract §2).

Main thread only: the GLB goes through the shared export lane
(``agent_export.export_to_path`` with the ``game`` preset — export_extras
OFF, active scene only, modifiers applied), never a second glTF call. The
spec beside it is a few kilobytes. Everything after this (Godot, hashing,
upload) belongs to a worker thread.

``boss_fight`` (contract v1.3): the characters' rigs travel with them and
only their ``<prefix><state>`` clips are exported (an explicit
``animations`` selection; helper actions stay out). The ``combat`` block
is resolved AFTER the GLB is written, from the file's own clip timeline
(``combat.prove``), so every time in the spec is measured, not assumed.
"""

from __future__ import annotations

import json
import os
import struct

import bpy

from ..constants import BOSS_TEMPLATE, EXPORT_DIRNAME, GAMES_SUBDIR, SCENE_FILE, SPEC_FILE
from . import characters as game_characters, combat, roles, spec as game_spec, visuals


def games_root() -> str:
    """``<user config>/mixar/games`` (created)."""
    base = bpy.utils.user_resource('CONFIG', path=GAMES_SUBDIR, create=True)
    if not isinstance(base, str) or not base:
        raise OSError("user config directory unavailable")
    return base


def game_dir_for(slug: str, root: str = "") -> str:
    return os.path.join(root or games_root(), game_spec.slugify(slug))


def app_version() -> str:
    try:
        from mixar.config.config import get_config
        return str((get_config().get("app_info") or {}).get("version") or "")
    except Exception:
        return ""


def current_spec(scene) -> tuple[dict, list]:
    """``(spec, in_game_objects)`` for ``scene`` as it stands."""
    objects, _excluded = visuals.split_visible([obj for obj in roles.game_objects(scene) if roles.in_game(obj)])
    settings = game_spec.load_settings(scene)
    return game_spec.build_spec(settings, game_spec.build_nodes(objects), app_version()), objects


def inspect(scene) -> dict:
    """Everything a check needs, without writing: ``{spec, objects,
    characters, errors, warnings, combat_warnings, timing, excluded,
    procedural_materials}`` (``excluded``: meshes ``visuals`` leaves out).
    ``spec["combat"]`` holds PREDICTED lengths here (the action's frames /
    fps); ``write_package`` replaces it, and ``combat_warnings``, with the
    block proven against the written file."""
    spec, objects = current_spec(scene)
    found = game_characters.find(objects)
    errors, warnings = game_spec.validate_spec(spec, found)
    timing, problems = {}, []
    if spec.get("template") == BOSS_TEMPLATE:
        overrides = game_spec.load_settings(scene).get("combat") or {}
        spec["combat"], timing, problems = combat.resolve(found, overrides, combat.scene_fps(scene))
    _kept, excluded = visuals.split_visible([obj for obj in roles.game_objects(scene) if roles.in_game(obj)])
    procedural = visuals.procedural_materials(objects)
    if excluded:
        warnings.append(f"{len(excluded)} mesh(es) left out of the game, glTF cannot show them (tag one to keep "
                        "it): " + ", ".join(f"{e['object']} ({e['reason']})" for e in excluded[:6])
                        + (" …" if len(excluded) > 6 else ""))
    if procedural:
        warnings.append("procedural material(s) export as flat colour; bake or use image textures: "
                        + ", ".join(procedural[:8]) + (" …" if len(procedural) > 8 else ""))
    return {"spec": spec, "objects": objects, "characters": found, "errors": errors,
            "warnings": warnings, "combat_warnings": problems, "timing": timing,
            "excluded": excluded, "procedural_materials": procedural}


def scene_lights(scene) -> list:
    """v1.4 ``world.scene_lights``: the scene's visible, renderable lights
    that no ``ignore`` role covers (a preview rig tagged ignore keeps its
    lights out), name order. The lane turns area lights into spots."""
    found = []
    for obj in getattr(scene, "objects", ()) or ():
        if getattr(obj, "type", "") == 'LIGHT' and roles.is_visible(obj) and roles.governing(obj)[0] != "ignore":
            found.append(obj)
    return sorted(found, key=lambda obj: obj.name)


def export_spec(objects, animations=None, lights=None) -> dict:
    """The shared lane's spec for a game GLB of ``objects``. ``animations``
    None exports every clip (v1 templates); a list selects clips. ``lights``
    (v1.4) are carried as glTF punctual lights; None keeps them out."""
    meshes = [obj.name for obj in objects if obj.type == 'MESH']
    extras = [obj.name for obj in objects if obj.type in ('EMPTY', 'ARMATURE')]
    spec = {"format": "glb", "use_case": "game", "target_scope": "scene",
            "mesh_names": meshes, "extra_object_names": extras,
            "suggested_filename": SCENE_FILE}
    if animations is not None:
        spec["animations"] = list(animations)
    if lights is not None:
        spec["scene_lights"] = True
        spec["extra_object_names"] = extras + [obj.name for obj in lights]
    return spec


def read_timeline(glb_path: str) -> dict:
    """``{animation name: (min_s, max_s)}`` from a GLB's JSON chunk (sampler
    input accessors' ``min``/``max``, which glTF requires)."""
    with open(glb_path, "rb") as handle:
        header = handle.read(20)
        if len(header) < 20 or header[:4] != b"glTF":
            raise ValueError("not a GLB file")
        length = struct.unpack("<I", header[12:16])[0]
        doc = json.loads(handle.read(length))
    accessors = doc.get("accessors") or []
    timeline = {}
    for anim in doc.get("animations") or []:
        lows, highs = [], []
        for sampler in anim.get("samplers") or []:
            acc = accessors[sampler["input"]] if sampler.get("input") is not None else {}
            if acc.get("min") and acc.get("max"):
                lows.append(float(acc["min"][0]))
                highs.append(float(acc["max"][0]))
        if lows:
            timeline[str(anim.get("name") or "")] = (min(lows), max(highs))
    return timeline



def _prove_combat(scene, checked: dict, glb: str, clips: list, result: dict) -> None:
    """Resolve ``spec["combat"]`` against the clip timeline of the GLB just
    written; the per-clip proof goes to ``result["combat_proof"]``."""
    spec, warnings = result["spec"], result["warnings"]
    fps = combat.scene_fps(scene)
    actions = {name: action for character in checked["characters"]
               for name, action in character["actions"].items()}
    try:
        timeline = read_timeline(glb)
    except (OSError, ValueError, KeyError, IndexError) as exc:
        warnings.append(f"could not read the clip timeline of {SCENE_FILE} ({exc.__class__.__name__}); "
                        "combat timing left out")
        timeline = {}
    extra = sorted(set(timeline) - set(clips))
    if extra:
        warnings.append(f"{SCENE_FILE} holds clips outside the selection: {', '.join(extra[:6])}")
    proof = combat.prove(actions, timeline, fps)
    overrides = game_spec.load_settings(scene).get("combat") or {}
    spec["combat"], _timing, problems = combat.resolve(checked["characters"], overrides, fps, proof)
    warnings.extend(problems)
    result["combat_proof"] = {"fps": round(fps, 4), "rule": "t = frame / fps + shift", "clips": proof}


def _write_json(path: str, data: dict) -> None:
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.replace(temp, path)


def write_package(scene, game_dir: str = "") -> dict:
    """Validate, export ``scene.glb`` and write ``game_spec.json``.

    Returns ``{"ok", "game_dir", "export_dir", "spec", "warnings", "errors",
    "export"}``; nothing is written when the spec has errors.
    """
    checked = inspect(scene)
    spec, objects, errors, warnings = (checked["spec"], checked["objects"], checked["errors"],
                                       checked["warnings"])
    boss_fight = spec.get("template") == BOSS_TEMPLATE
    clips = game_characters.export_clips(checked["characters"]) if boss_fight else None
    if not any(obj.type == 'MESH' for obj in objects):
        errors.append("no visible meshes to export")
    game_dir = game_dir or game_dir_for(spec["slug"])
    export_dir = os.path.join(game_dir, EXPORT_DIRNAME)
    result = {"ok": False, "game_dir": game_dir, "export_dir": export_dir, "spec": spec,
              "errors": errors, "warnings": warnings, "export": None}
    if errors:
        return result
    from mixar.modules.space_mixie_chat.core.agent_export import export_to_path
    glb = os.path.join(export_dir, SCENE_FILE)
    lights = scene_lights(scene) if (spec.get("world") or {}).get("scene_lights") else None
    exported = export_to_path(glb, export_spec(objects, clips, lights))
    result["export"] = {key: exported.get(key) for key in
                        ("success", "error", "mesh_count", "file_size_bytes", "warning", "verification",
                         "clips", "clips_missing", "scene_objects")}
    if not exported.get("success"):
        errors.append(f"GLB export failed: {exported.get('error') or 'unknown error'}")
        return result
    if exported.get("warning"):
        warnings.append(exported["warning"])
    for issue in (exported.get("verification") or {}).get("issues") or ():
        warnings.append(f"scene.glb: {issue}")
    if boss_fight:
        _prove_combat(scene, checked, glb, clips, result)
    try:
        _write_json(os.path.join(export_dir, SPEC_FILE), spec)
    except OSError as exc:
        errors.append(f"could not write {SPEC_FILE} ({exc.__class__.__name__})")
        return result
    result["ok"] = True
    return result
