# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Open a downloaded remix source as the user's own project — main thread.

The source never auto-runs scripts. Every scene is cleaned again (a .mixar
attached on the web was never cleaned by its creator's app), stamped with
what it was remixed from, and saved under ``<config>/mixar/remixes`` so the
download is never the file being edited.
"""

from __future__ import annotations

import json
import os
import uuid

from mixar.config.logging_config import get_logger

from ..constants import FORMAT_MIXAR
from . import lineage

logger = get_logger(__name__)


def apply_spec(objects, spec: dict, set_role) -> int:
    """Put the roles of a game package back on imported objects, matched by
    name (the GLB carries no tags; ``game_spec.json`` lists them). Returns
    how many were tagged. Unmatched names are skipped."""
    by_name = {obj.name: obj for obj in objects}
    tagged = 0
    for node in (spec or {}).get("nodes") or ():
        obj = by_name.get(str((node or {}).get("name") or ""))
        if obj is None or not node.get("role"):
            continue
        ok, _errors = set_role(obj, node["role"], node.get("params") or {})
        tagged += 1 if ok else 0
    return tagged


def retitle(scene) -> None:
    """A remix starts with its own title and slug, so publishing it can never
    collide with (or be mistaken for) the original's store page."""
    try:
        from mixar.modules.game_studio.constants import SPEC_PROP, TITLE_MAX
        from mixar.modules.game_studio.core import spec as game_spec
    except Exception:  # noqa: BLE001 — no game lane in this build
        return
    if not scene.get(SPEC_PROP):
        return
    settings = game_spec.load_settings(scene)
    settings["title"] = lineage.remix_title(settings.get("title"), TITLE_MAX)
    # Its own slug, never the parent's: see ``lineage.remix_slug``.
    settings["slug"] = lineage.remix_slug(game_spec.slugify(settings["title"]), uuid.uuid4().hex)
    game_spec.save_settings(scene, settings)


def _import_package(plan: dict) -> None:
    import bpy
    from mixar.modules.common.gltf_import import import_gltf
    bpy.ops.wm.read_homefile()
    import_gltf(plan["path"])
    if not plan.get("spec_path"):
        return
    try:
        with open(plan["spec_path"], encoding="utf-8") as handle:
            spec = json.load(handle)
        from mixar.modules.game_studio.core import roles
        from mixar.modules.game_studio.core import spec as game_spec
        scene = bpy.context.scene
        tagged = apply_spec(scene.objects, spec, roles.set_role)
        settings, _errors = game_spec.merge_settings(game_spec.load_settings(scene), {
            key: value for key, value in spec.items() if key not in ("schema", "nodes", "version")})
        game_spec.save_settings(scene, settings)
        logger.info("remix: re-tagged %d object(s) from the game package", tagged)
    except Exception as exc:  # noqa: BLE001 — the scene still opens, untagged
        logger.warning("remix: could not restore game roles: %s", exc)


def _keep_unsaved_work(plan: dict) -> str:
    """The open file changed while the remix was downloading: keep a copy
    beside the remix rather than lose it. Returns the copy's path, or ""."""
    import bpy
    if not bpy.data.is_dirty:
        return ""
    path = os.path.join(os.path.dirname(plan["project_path"]), "unsaved-before-remix.mixar")
    try:
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("your open project has unsaved changes that could not be kept") from exc
    return path


def _disarm(bpy) -> None:
    """A remix is someone else's file. Its scripts never ran on open
    (``use_scripts=False``); also stop them registering themselves the next
    time the saved project is opened."""
    for text in bpy.data.texts:
        if getattr(text, "use_module", False):
            text.use_module = False


def open_remix(plan: dict) -> dict:
    """Open ``plan`` (from ``intake``) and save it as the user's project.
    Raises when the remix could not be opened and saved."""
    import bpy
    recovered = _keep_unsaved_work(plan)
    if plan["format"] == FORMAT_MIXAR:
        # load_ui=False: take the project's data, not the creator's window
        # layout and window-manager state.
        bpy.ops.wm.open_mainfile(filepath=plan["path"], use_scripts=False, load_ui=False,
                                 display_file_selector=False)
    else:
        _import_package(plan)
    lineage.scrub_file(bpy.data)
    _disarm(bpy)
    for scene in bpy.data.scenes:
        lineage.stamp(scene, plan["origin"])
        retitle(scene)
    bpy.ops.wm.save_as_mainfile(filepath=plan["project_path"])
    if not os.path.isfile(plan["project_path"]) or bpy.data.filepath != plan["project_path"]:
        raise RuntimeError("the remix could not be saved as a new project")
    _welcome(plan, recovered)
    return {"ok": True, "project_path": plan["project_path"], "origin": plan["origin"],
            "recovered": recovered}


def _welcome(plan: dict, recovered: str = "") -> None:
    try:
        from mixar.modules.common.i18n import rpt_
        from mixar.modules.common.notifications import get_notification_store
        prompts = plan.get("starter_prompts") or []
        body = lineage.credit_line(plan["origin"]) + "."
        if prompts:
            body += " " + rpt_("Try asking Mixie: {prompt}").format(prompt=prompts[0])
        if recovered:
            body += " " + rpt_("Your unsaved work was kept as {name} beside it.").format(
                name=os.path.basename(recovered))
        get_notification_store().push("success", rpt_("This copy is yours to change."), body=body,
                                      ttl_ms=20_000)
    except Exception:  # noqa: BLE001
        pass
