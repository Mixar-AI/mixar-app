# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The engine project's own assets for the agent: find them by name, place them.

Mixar Link places only the packages Mixar exported and has no asset search,
so content the user brought into the project (Fab, Marketplace, Quixel
Megaplants, their own meshes) was out of the agent's reach: it asked the user
for exact asset paths. Two engine calls close that, answered here on the
desktop (`engine_link.link_call` routes them):

- ``assets`` ``{query, folder, kind, limit}``: the project's assets whose
  name contains ``query`` under ``folder``, each with its kind, plus the
  folder's subfolders (the project's structure). Unreal: Epic's EditorToolset
  (``AssetTools.find_assets``, the asset registry, one typed search per kind;
  enabled with Mixar Link's AllToolsets); Godot: Mixar Link's ``list_files``.
- ``place`` of a project asset (an ``assets`` path) — Unreal: Epic's
  ``SceneTools.add_to_scene_from_asset`` at a Blender-frame position, yaw
  and scale, then the level is saved (also a user's own level in plugin mode:
  the user chose place-and-save, but only a level that had no unsaved changes
  of theirs; see ``_save``). Mixar packages (``/Game/Mixar/…``) and every
  Godot scene still go to Mixar Link's own ``place``. A timeout from the spawn
  on is ``engine_link.PLACE_TIMED_OUT``: the actor may be in the level.

Results use ``engine_link``'s shape (``{success, data | error}``); package
paths (``/Game/…``, ``res://…``) name things in the project, never the disk.
"""

from __future__ import annotations

import json
import os
import re

EPIC_ASSETS = "editor_toolset.toolsets.asset.AssetTools"
EPIC_SCENE = "editor_toolset.toolsets.scene.SceneTools"
MIXAR_FOLDER = "/Game/Mixar"
# Unreal asset kinds and the class each typed search filters by (Epic's
# find_assets also matches subclasses; an Actor search returns the Blueprints
# whose parent class is an Actor: the placeable ones).
UNREAL_KINDS = {
    "static_mesh": "/Script/Engine.StaticMesh",
    "skeletal_mesh": "/Script/Engine.SkeletalMesh",
    "blueprint": "/Script/Engine.Actor",
    "effect": "/Script/Niagara.NiagaraSystem",
    "sound": "/Script/Engine.SoundBase",
    "material": "/Script/Engine.MaterialInterface",
    "texture": "/Script/Engine.Texture",
    "level": "/Script/Engine.World",
}
PLACEABLE = ("static_mesh", "skeletal_mesh", "blueprint", "effect", "sound")
KINDS = ("placeable", "any") + tuple(UNREAL_KINDS)
# Godot: what a res:// file is, by extension (scenes and models instance with place).
GODOT_KINDS = {
    "scene": (".tscn", ".scn"),
    "model": (".glb", ".gltf", ".fbx", ".blend", ".obj"),
    "texture": (".png", ".jpg", ".jpeg", ".webp", ".exr", ".hdr", ".svg"),
    "sound": (".wav", ".ogg", ".mp3"),
    "material": (".tres", ".material", ".gdshader"),
    "script": (".gd",),
}
GODOT_PLACEABLE = ("scene", "model")
DEFAULT_LIMIT, MAX_LIMIT, MAX_FOLDERS, MAX_GROUPS = 40, 200, 60, 20
# Per-asset class lookups for an untyped (kind="any") search.
MAX_CLASSIFY = 40
CALL_S = 30.0


class AssetError(RuntimeError):
    """A refusal the agent can act on; its text is safe to show."""


# ---------------------------------------------------------------------------
# Routing (engine_link.link_call)
# ---------------------------------------------------------------------------

def handles(info: dict, tool: str, arguments: dict) -> bool:
    """Whether this module answers ``tool`` for the connected editor."""
    if tool == "assets":
        return True
    return (tool == "place" and info.get("engine") == "unreal"
            and is_project_asset(str((arguments or {}).get("scene") or "")))


def is_project_asset(path: str) -> bool:
    """An Unreal content path that is not a Mixar package (those stay Mixar Link's)."""
    path = path.split(".", 1)[0].rstrip("/")
    return path.startswith("/") and not (path == MIXAR_FOLDER or path.startswith(MIXAR_FOLDER + "/"))


def run(info: dict, client, tool: str, arguments: dict, timeout: float) -> dict:
    """The routed call's answer, never raising for a refusal."""
    from . import engine_link

    args = dict(arguments or {})
    try:
        if tool == "assets":
            if info.get("engine") == "unreal":
                data = search_unreal(_Epic(client, timeout), args)
            else:
                data = search_godot(client, args, timeout)
        else:
            data = place_unreal(_Epic(client, timeout), client, args, timeout)
    except (AssetError, engine_link.LinkError) as err:
        return {"success": False, "error": engine_link.scrub(str(err))}
    return {"success": True, "data": engine_link.scrub(data)}


# place arguments only a project asset takes; Mixar Link's own place (Unreal's
# schema refuses an unknown argument) never receives them.
ASSET_ONLY_ARGS = ("scale", "snap_to_ground")


def adapter_args(tool: str, arguments) -> dict:
    """``arguments`` as the editor's Mixar Link takes them."""
    args = dict(arguments or {})
    if tool == "place":
        for key in ASSET_ONLY_ARGS:
            args.pop(key, None)
    return args


def tools_with_assets(tools) -> list:
    """``status``'s tool list with the calls answered here."""
    out = list(tools or [])
    return out + [t for t in ("assets",) if t not in out]


# ---------------------------------------------------------------------------
# Epic's toolsets through Unreal's MCP server
# ---------------------------------------------------------------------------

class _Epic:
    """Calls into Epic's EditorToolset beside Mixar Link: ``returnValue`` out,
    an error raised as AssetError. Unreal's schema makes every string argument
    required, so callers pass them all."""

    def __init__(self, client, timeout: float):
        self.client, self.timeout = client, min(float(timeout or CALL_S), 120.0)

    def __call__(self, toolset: str, tool: str, arguments: dict):
        from . import engine_link

        raw = engine_link.McpClient.call(self.client, "call_tool", {
            "toolset_name": toolset, "tool_name": tool, "arguments": arguments}, self.timeout)
        content = raw.get("content") if isinstance(raw.get("content"), list) else []
        text = next((c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"), "")
        if raw.get("isError"):
            first = (text or "the engine refused the call").strip().splitlines()[0]
            if "toolset" in first.lower() and ("not found" in first.lower() or "unknown" in first.lower()):
                raise AssetError("Unreal's Editor toolset is off in this project; reconnect it from the engine "
                                 "chip (Connect enables All Toolsets).")
            raise AssetError(first[:300])
        try:
            return json.loads(text).get("returnValue")
        except (ValueError, AttributeError):
            raise AssetError("Unreal sent an unreadable reply.") from None


def _limit(args: dict) -> int:
    try:
        return max(1, min(int(args.get("limit") or DEFAULT_LIMIT), MAX_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def _words(query: str) -> list:
    """A query's words ("willow tree", "SM_Rock-01" -> sm, rock, 01)."""
    return [w for w in re.split(r"[\s_\-./]+", query.lower()) if w]


def _matches(path: str, words: list) -> bool:
    """Every word is somewhere in the path (the asset's name or its folders)."""
    low = path.lower()
    return all(w in low for w in words)


def _rank(query: str):
    """Most query words in the NAME first (a tree over the branches of the
    tree's folder), then an exact or leading match, then the shortest path."""
    words, q = _words(query), query.strip().lower()

    def key(entry):
        name = entry["name"].lower()
        return (-sum(w in name for w in words), 0 if name == q else 1 if name.startswith(q) else 2,
                len(entry["path"]), entry["path"])
    return key


def _groups(assets: list) -> list:
    """Where the matches live: per folder, how many and of which kinds (the
    project's structure around a search), largest first."""
    by_folder: dict = {}
    for a in assets:
        group = by_folder.setdefault(a["path"].rsplit("/", 1)[0], {})
        group[a["kind"]] = group.get(a["kind"], 0) + 1
    rows = [{"folder": f, "count": sum(k.values()), "kinds": k} for f, k in by_folder.items()]
    return sorted(rows, key=lambda r: (-r["count"], r["folder"]))[:MAX_GROUPS]


def _folder(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path.strip("/") else path


def search_unreal(epic, args: dict) -> dict:
    query = str(args.get("query") or "").strip()
    folder = str(args.get("folder") or "/Game").strip().rstrip("/") or "/Game"
    if not folder.startswith("/"):
        raise AssetError("folder is a content path such as /Game or /Game/Megaplant_Library.")
    kind = str(args.get("kind") or "placeable").strip().lower()
    if kind not in KINDS:
        raise AssetError(f"kind must be one of {', '.join(KINDS)}.")
    words = _words(query)
    # The registry filters by one name substring: the longest word; the rest
    # must be in the path (a folder "Tree_Goat_Willow" names its assets too).
    probe = max(words, key=len) if words else ""
    found: dict[str, str] = {}
    if kind == "any":
        paths = [p for p in epic(EPIC_ASSETS, "find_assets", {"folder_path": folder, "name": probe,
                                                               "recursive": True}) or []
                 if isinstance(p, str) and _matches(p, words)]
        for path in paths[:MAX_CLASSIFY]:
            try:
                found[path] = _kind_of(str(epic(EPIC_ASSETS, "get_asset_class", {"asset_path": path}) or ""))
            except AssetError:
                found[path] = "other"
        total = len(paths)
    else:
        for k in (PLACEABLE if kind == "placeable" else (kind,)):
            paths = epic(EPIC_ASSETS, "find_assets", {"folder_path": folder, "name": probe, "recursive": True,
                                                      "asset_type": {"refPath": UNREAL_KINDS[k]}}) or []
            for path in paths:
                if isinstance(path, str) and _matches(path, words):
                    found.setdefault(path, k)
        total = len(found)
    assets = sorted(({"path": p, "name": p.rsplit("/", 1)[-1], "kind": k} for p, k in found.items()),
                    key=_rank(query))
    limit = _limit(args)
    try:
        folders = [f.rstrip("/") for f in epic(EPIC_ASSETS, "list_folders", {"root_path": folder, "recursive": False})
                   or [] if isinstance(f, str) and "__External" not in f]
    except AssetError:
        folders = []
    return {"folder": folder, "query": query, "kind": kind, "assets": assets[:limit], "total": total,
            "truncated": len(assets) > limit, "groups": _groups(assets), "folders": folders[:MAX_FOLDERS],
            "next": "engine_place(scene=<an asset's path>, position=[x, y, z]) puts a placeable one in the open "
                    "level; search a subfolder or a name to narrow."}


_CLASS_KIND = {"StaticMesh": "static_mesh", "SkeletalMesh": "skeletal_mesh", "Blueprint": "blueprint",
               "NiagaraSystem": "effect", "World": "level", "Texture2D": "texture", "Material": "material",
               "MaterialInstanceConstant": "material", "SoundWave": "sound", "SoundCue": "sound"}


def _kind_of(class_name: str) -> str:
    return _CLASS_KIND.get(class_name.rsplit(".", 1)[-1], class_name or "other")


def search_godot(client, args: dict, timeout: float) -> dict:
    from . import engine_link

    query = str(args.get("query") or "").strip().lower()
    words = _words(query)
    folder = str(args.get("folder") or "res://").strip()
    folder = folder if folder.startswith("res://") else "res://" + folder.lstrip("/")
    folder = folder.rstrip("/") if folder != "res://" else folder
    prefix = folder if folder.endswith("/") else folder + "/"
    kind = str(args.get("kind") or "placeable").strip().lower()
    kinds = GODOT_PLACEABLE if kind == "placeable" else tuple(GODOT_KINDS) if kind == "any" else (kind,)
    if any(k not in GODOT_KINDS for k in kinds):
        raise AssetError(f"Godot kinds: placeable, any, {', '.join(GODOT_KINDS)}.")
    listed = engine_link._result(client.call("list_files", {"dir": folder, "max_files": 2000},
                                             float(timeout or CALL_S)))
    if not listed.get("success"):
        raise AssetError(listed.get("error") or "the engine could not list the project")
    files = [f.get("path", "") for f in (listed.get("data") or {}).get("files") or [] if isinstance(f, dict)]
    assets, folders = [], set()
    for path in files:
        rel = path[len(prefix):] if path.startswith(prefix) else ""
        if "/" in rel:
            folders.add(prefix + rel.split("/", 1)[0])
        name, ext = os.path.splitext(path.rsplit("/", 1)[-1])
        k = next((k for k in kinds if ext.lower() in GODOT_KINDS[k]), "")
        if k and _matches(path, words) and not path.startswith("res://addons/"):
            assets.append({"path": path, "name": name, "kind": k})
    assets.sort(key=_rank(query))
    limit = _limit(args)
    return {"folder": folder, "query": query, "kind": kind, "assets": assets[:limit],
            "total": len(assets), "truncated": len(assets) > limit or bool(listed["data"].get("truncated")),
            "groups": _groups(assets), "folders": sorted(folders)[:MAX_FOLDERS],
            "next": "engine_place(scene=<a scene or model path>, position=[x, y, z]) instances it in the open scene."}


# ---------------------------------------------------------------------------
# Placing a project asset in Unreal
# ---------------------------------------------------------------------------

def _status(client, timeout: float) -> dict:
    from . import engine_link

    out = engine_link._result(client.call("status", {}, min(float(timeout or CALL_S), 30.0)))
    if not out.get("success"):
        raise AssetError(out.get("error") or "Mixar Link did not answer.")
    return out.get("data") or {}


def _vector(values, default: float) -> list:
    if values is None or values == "":
        return [default] * 3
    if isinstance(values, (int, float)):
        return [float(values)] * 3
    values = [float(v) for v in values]
    if len(values) != 3:
        raise AssetError("position and scale take three numbers [x, y, z].")
    return values


def _unique_label(epic, base: str) -> str:
    taken = set()
    for ref in epic(EPIC_SCENE, "find_actors", {"name": base, "tag": "", "collision_channels": []}) or []:
        path = str((ref or {}).get("refPath") or "") if isinstance(ref, dict) else ""
        taken.add(path)
    if not taken:
        return base
    for n in range(2, 1000):
        candidate = f"{base}_{n}"
        if not epic(EPIC_SCENE, "find_actors", {"name": candidate, "tag": "", "collision_channels": []}):
            return candidate
    return base


def place_unreal(epic, client, args: dict, timeout: float) -> dict:
    from . import engine_link

    asset = str(args.get("scene") or "").split(".", 1)[0].rstrip("/")
    status = _status(client, timeout)
    if status.get("playing"):
        raise AssetError("The game is running: stop it first (engine_play action=stop), then place.")
    level = str(epic(EPIC_SCENE, "get_current_level", {}) or "")
    if not level:
        raise AssetError("No level is open; open or make one first.")
    if level.startswith("/Temp/"):
        raise AssetError("The open level was never saved; open a level under /Game, or make one with engine_scene.")
    if not epic(EPIC_ASSETS, "exists", {"path": asset}):
        raise AssetError(f"No asset at {asset}; find one with engine_assets.")
    x, y, z = _vector(args.get("position"), 0.0)
    scale = _vector(args.get("scale"), 1.0)
    yaw = float(args.get("yaw_deg") or 0.0)
    label = _unique_label(epic, str(args.get("name") or "").strip() or asset.rsplit("/", 1)[-1])
    package = level.split(".", 1)[0]
    # Plugin mode saves through Epic, and only a level the user had left clean: read it before the spawn dirties it.
    was_dirty = _level_dirty(epic, package) if status.get("project_mode") != "owned" else False
    request = {"asset_path": asset, "name": label,
               # Blender's frame (Z up, metres, right-handed) -> Unreal's (cm, left-handed): see Mixar Link's frames.
               "xform": {"location": {"x": x * 100.0, "y": -y * 100.0, "z": z * 100.0},
                         "rotation": {"pitch": 0.0, "yaw": -yaw, "roll": 0.0},
                         "scale": {"x": scale[0], "y": scale[1], "z": scale[2]}},
               "snap_to_ground": bool(args.get("snap_to_ground"))}
    parent = str(args.get("parent") or "").strip()
    if parent:
        refs = epic(EPIC_SCENE, "find_actors", {"name": parent.rsplit("/", 1)[-1], "tag": "",
                                                "collision_channels": []}) or []
        if not refs:
            raise AssetError(f"No actor at {parent} (paths come from engine_scene_tree).")
        request["parent"] = refs[0]
    try:
        actor = epic(EPIC_SCENE, "add_to_scene_from_asset", request)
        if not actor:
            raise AssetError(f"Unreal could not make an actor from {asset} (a {asset.rsplit('/', 1)[-1]} "
                             "may not be placeable: place a mesh, a Blueprint, an effect or a sound).")
        saved, note = _save(epic, client, package, timeout, was_dirty)
    except engine_link.LinkError as err:
        if err.timed_out:  # the editor may finish the spawn after the wait: never invite a second one
            raise AssetError(engine_link.PLACE_TIMED_OUT) from None
        raise
    out = {"node": label, "asset": asset, "position": [x, y, z], "yaw_deg": yaw, "scale": scale,
           "scene": level, "saved": saved}
    if note:
        out["note"] = note
    return engine_link.scrub(out)


NOT_SAVED = "Placed but not saved; the user can save with Ctrl+S."


def _level_dirty(epic, level: str):
    """Whether the level's package has unsaved changes (Epic's
    ``AssetTools.is_dirty``), or None when Unreal cannot say. The argument's
    name is not published; both of the toolset's path names are tried."""
    for key in ("asset_path", "path"):
        try:
            value = epic(EPIC_ASSETS, "is_dirty", {key: level})
        except AssetError:
            continue
        if isinstance(value, bool):
            return value
    return None


def _external_actors(epic, level: str) -> bool:
    """An Open World (World Partition) level: its actors live in their own
    packages under ``__ExternalActors__``, which saving the level does not write."""
    mount, _, rest = level.strip("/").partition("/")
    try:
        return bool(epic(EPIC_ASSETS, "list_folders", {"root_path": f"/{mount}/__ExternalActors__/{rest}",
                                                       "recursive": False}))
    except AssetError:
        return False


def _save(epic, client, level: str, timeout: float, was_dirty) -> tuple[bool, str]:
    """Save the level the asset went into: Mixar Link's save (the open level
    and its actors) where it may. In a user's own project (plugin mode) it
    refuses, and Epic's ``save_assets`` saves that level's package ALONE
    (``/Game/Maps/Foo``, never the empty list: Unreal's save of every dirty
    package), and only when the level had no unsaved changes before the place
    (``was_dirty`` False) and the place is what dirtied it: the user's own
    edits are never written. An Open World level is not saved (each actor is
    its own package)."""
    from . import engine_link

    saved = engine_link._result(client.call("save_scene", {}, min(float(timeout or CALL_S), 60.0)))
    if saved.get("success") and (saved.get("data") or {}).get("saved") is not False:
        return True, ""
    if not level:
        return False, NOT_SAVED
    if was_dirty:
        return False, ("Placed but not saved: the level already had unsaved changes of the user's, which Mixar "
                       "never saves; the user can save with Ctrl+S.")
    if _external_actors(epic, level):
        return False, ("Placed but not saved: this Open World level keeps each actor in its own file, which only "
                       "the user's save writes (Ctrl+S).")
    if was_dirty is None or _level_dirty(epic, level) is not True:  # the place must be what dirtied it
        return False, ("Placed but not saved: Unreal could not say whether the level had unsaved changes of the "
                       "user's, so saving is left to them (Ctrl+S).")
    try:
        if epic(EPIC_ASSETS, "save_assets", {"asset_paths": [level]}):
            return True, f"Saved only the level {level}; it had no unsaved changes of the user's before the place."
    except AssetError as err:
        return False, f"Placed but not saved ({err}); the user can save with Ctrl+S."
    return False, NOT_SAVED
