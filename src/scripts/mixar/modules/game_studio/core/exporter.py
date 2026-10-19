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
from . import bake_plan, characters as game_characters, combat, roles, spec as game_spec, visuals


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


def _game_objects(scene) -> tuple[list, list]:
    """``(objects, excluded)``: the in-game objects the GLB can show, and
    the meshes ``visuals`` leaves out."""
    return visuals.split_visible([obj for obj in roles.game_objects(scene) if roles.in_game(obj)])


def current_spec(scene, split=None) -> tuple[dict, list]:
    """``(spec, in_game_objects)`` for ``scene`` as it stands."""
    objects, _excluded = split or _game_objects(scene)
    settings = game_spec.load_settings(scene)
    nodes = game_spec.build_nodes(objects)
    # Particle fields default to decor: a nested decor node overrides the
    # static role it would get from its ancestor or the untagged default.
    fields = {item["object"] for item in visuals.particle_fields(objects)}
    if fields:
        nodes = sorted([n for n in nodes if n["name"] not in fields]
                       + [{"name": name, "role": "decor", "params": {}, "subtree": True} for name in fields],
                       key=lambda n: n["name"])
    return game_spec.build_spec(settings, nodes, app_version()), objects


def inspect(scene) -> dict:
    """Everything a check needs, without writing: ``{spec, objects,
    characters, errors, warnings, combat_warnings, timing, excluded,
    decor_auto, procedural_materials, bake_materials}`` (``excluded``: meshes ``visuals`` leaves out).
    ``spec["combat"]`` holds PREDICTED lengths here (the action's frames /
    fps); ``write_package`` replaces it, and ``combat_warnings``, with the
    block proven against the written file."""
    split = _game_objects(scene)
    spec, objects = current_spec(scene, split)
    found = game_characters.find(objects)
    errors, warnings = game_spec.validate_spec(spec, found)
    timing, problems = {}, []
    if spec.get("template") == BOSS_TEMPLATE:
        overrides = game_spec.load_settings(scene).get("combat") or {}
        spec["combat"], timing, problems = combat.resolve(found, overrides, combat.scene_fps(scene))
    excluded = split[1]
    bake = bake_plan.plan(objects)["materials"] if game_spec.load_settings(scene).get("bake_materials") else []
    if bake:
        warnings.append(f"{len(bake)} material(s) are baked to textures for the game in the background (the "
                        "first build takes longer): " + ", ".join(bake[:8]) + (" …" if len(bake) > 8 else ""))
    procedural = [name for name in visuals.procedural_materials(objects) if name not in bake]
    decor_auto = visuals.particle_fields(objects)
    if decor_auto:
        warnings.append(f"{len(decor_auto)} particle-field mesh(es) play as decor, without collision (tag one to "
                        "change it): " + ", ".join(e["object"] for e in decor_auto[:6])
                        + (" …" if len(decor_auto) > 6 else ""))
    if excluded:
        warnings.append(f"{len(excluded)} mesh(es) left out of the game, glTF cannot show them (tag one to keep "
                        "it): " + ", ".join(f"{e['object']} ({e['reason']})" for e in excluded[:6])
                        + (" …" if len(excluded) > 6 else ""))
    if procedural:
        warnings.append("procedural material(s) export as flat colour; bake or use image textures: "
                        + ", ".join(procedural[:8]) + (" …" if len(procedural) > 8 else ""))
    return {"spec": spec, "objects": objects, "characters": found, "errors": errors,
            "warnings": warnings, "combat_warnings": problems, "timing": timing,
            "excluded": excluded, "decor_auto": decor_auto, "procedural_materials": procedural,
            "bake_materials": bake}


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



def strip_rig_object_motion(glb_path: str, rig_names) -> int:
    """boss_fight: drop every animation channel that moves a character RIG
    as an object (translation / rotation / scale of the rig node). The kit
    moves the body; a rig that rotates or translates in a clip tips the
    character over in game. Bone channels stay. Rewrites only the GLB's JSON
    chunk (unused accessors are allowed by glTF). Returns channels removed."""
    with open(glb_path, "rb") as handle:
        data = handle.read()
    if data[:4] != b"glTF":
        raise ValueError("not a GLB file")
    json_length = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(data[20:20 + json_length])
    rest = data[20 + json_length:]
    rigs = {index for index, node in enumerate(doc.get("nodes") or []) if node.get("name") in set(rig_names)}
    removed = 0
    for anim in doc.get("animations") or []:
        keep = [c for c in anim.get("channels") or []
                if not (c.get("target", {}).get("node") in rigs
                        and c.get("target", {}).get("path") in ("translation", "rotation", "scale"))]
        removed += len(anim.get("channels") or []) - len(keep)
        used = sorted({c["sampler"] for c in keep})
        remap = {old: new for new, old in enumerate(used)}
        anim["samplers"] = [anim["samplers"][i] for i in used]
        for channel in keep:
            channel["sampler"] = remap[channel["sampler"]]
        anim["channels"] = keep
    if not removed:
        return 0
    body = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    body += b" " * (-len(body) % 4)
    total = 12 + 8 + len(body) + len(rest)
    temp = glb_path + ".tmp"
    with open(temp, "wb") as handle:
        handle.write(b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I", len(body)) + b"JSON" + body + rest)
    os.replace(temp, glb_path)
    return removed


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
    visuals.clear_caches()  # the panels' cached verdicts may predate an edit
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
        rigs = [name for character in checked["characters"] for name in character["rigs"]]
        try:
            result["rig_object_channels_removed"] = strip_rig_object_motion(glb, rigs)
        except (OSError, ValueError, KeyError, IndexError) as exc:
            errors.append(f"could not clean the character rigs' clips in {SCENE_FILE} ({exc.__class__.__name__})")
            return result
        _prove_combat(scene, checked, glb, clips, result)
    try:
        _write_json(os.path.join(export_dir, SPEC_FILE), spec)
    except OSError as exc:
        errors.append(f"could not write {SPEC_FILE} ({exc.__class__.__name__})")
        return result
    result["ok"] = True
    return result
