# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Start game jobs on the main thread: export the package, capture the
inputs, hand the rest to a worker.

``start("build"|"export", …)`` backs the agent API. ``start_approved_publish``
is called ONLY by the publish approval operator after the user clicked
Publish (``approvals``); ``agent_api`` never imports it (pinned by
``test_game_studio_approval.py``) and this module is denied to agent scripts.
"""

from __future__ import annotations

import bpy

from ..constants import DEFAULT_PLATFORMS
from . import bake_job, exporter, jobs, pipeline


def busy() -> dict | None:
    """A running build/export/publish (library jobs don't block a build)."""
    job = next((j for j in (jobs.running(k) for k in ("build", "export", "publish")) if j), None)
    if job is None:
        return None
    return {"ok": False, "job_id": job["job_id"], "state": "failed", "error_code": "busy",
            "error": f"A {job['kind']} job is still running."}


def context(scene, package: dict, store_page=None) -> dict:
    from mixar.config.config import get_community_api_url, get_community_web_url
    from .agent_api import _godot_config, _store_identity
    return {"game_dir": package["game_dir"], "title": package["spec"]["title"],
            "slug": package["spec"]["slug"], "warnings": list(package["warnings"]),
            "godot_config": _godot_config(), "api_base": get_community_api_url(),
            "web_base": get_community_web_url(), "store": _store_identity(scene),
            "scene_name": scene.name, "store_page": store_page or {},
            # What this project was remixed from (None for an original).
            "remixed_from": _remixed_from(scene)}


def _remixed_from(scene):
    try:
        from mixar.modules.remix.core import lineage
        return lineage.origin_of(scene)
    except Exception:  # noqa: BLE001 — lineage is never a reason to refuse a build
        return None


def _with_remix_source(ctx: dict, allow_remix: bool) -> dict:
    """Main thread: capture the project file a remixable game carries. A
    failed capture publishes the game without a source, with a warning."""
    ctx = dict(ctx, allow_remix=bool(allow_remix))
    if not allow_remix:
        return ctx
    try:
        from mixar.modules.remix.core import source_job
        ctx["remix_source"] = source_job.prepare(ctx["game_dir"], ctx["slug"])
    except Exception as exc:  # noqa: BLE001
        ctx["warnings"] = list(ctx.get("warnings") or []) + [
            f"The project was not included for remixing ({exc.__class__.__name__})."]
    return ctx


def refused(package: dict) -> dict:
    return {"ok": False, "job_id": None, "state": "failed", "error_code": "invalid_spec",
            "error": "; ".join(package["errors"]), "errors": package["errors"],
            "warnings": package["warnings"]}


def _run(kind: str, scene, make_work, store_page=None, job_id=None) -> dict:
    blocked = busy()
    if blocked:
        return blocked
    checked = exporter.inspect(scene)
    if checked["bake_materials"]:
        return _run_baked(kind, scene, make_work, checked, store_page, job_id)
    package = exporter.write_package(scene)
    if not package["ok"]:
        return refused(package)
    job_id = jobs.start(kind, make_work(context(scene, package, store_page)), job_id)
    return {"ok": True, "job_id": job_id, "state": "running",
            "warnings": package["warnings"], "game_dir": package["game_dir"]}


def _run_baked(kind: str, scene, make_work, checked: dict, store_page, job_id) -> dict:
    """Materials need a bake: the main thread only saves a temporary copy;
    the bake, the GLB and the spec come from a background Mixar process
    (``bake_job``) before the Godot stages."""
    spec = checked["spec"]
    errors = list(checked["errors"])
    if not any(obj.type == 'MESH' for obj in checked["objects"]):
        errors.append("no visible meshes to export")
    game_dir = exporter.game_dir_for(spec["slug"])
    package = {"ok": not errors, "game_dir": game_dir, "spec": spec, "errors": errors,
               "warnings": list(checked["warnings"])}
    if errors:
        return refused(package)
    try:
        bake = bake_job.prepare(scene, game_dir)
    except (OSError, RuntimeError) as exc:
        return {"ok": False, "job_id": None, "state": "failed", "error_code": "bake_prepare_failed",
                "error": f"Could not save a copy of the scene to bake ({exc.__class__.__name__})."}
    work = bake_job.with_bake(bake, make_work(context(scene, package, store_page)))
    job_id = jobs.start(kind, work, job_id)
    return {"ok": True, "job_id": job_id, "state": "running", "warnings": package["warnings"],
            "game_dir": game_dir, "baking": checked["bake_materials"]}


def start(kind: str, scene, play=False, platforms=None) -> dict:
    if kind == "build":
        return _run("build", scene, lambda ctx: pipeline.build_work(ctx, bool(play)))
    if kind == "export":
        return _run("export", scene, lambda ctx: pipeline.export_work(ctx, platforms))
    raise ValueError(kind)


def start_approved_publish(request_id: str, payload: dict) -> dict:
    """The user approved ``request_id`` in the UI: export and publish."""
    scene = bpy.data.scenes.get(payload.get("scene_name", ""))
    if scene is None:
        return {"ok": False, "job_id": request_id, "state": "failed", "error_code": "scene_missing",
                "error": "The scene this publish was requested for no longer exists."}
    if scene != bpy.context.scene:
        return {"ok": False, "job_id": request_id, "state": "failed", "error_code": "wrong_scene",
                "error": f"Switch to the scene '{scene.name}' to publish it."}
    platforms = list(payload.get("platforms") or DEFAULT_PLATFORMS)
    allow_remix = bool(payload.get("allow_remix", True))
    return _run("publish", scene,
                lambda ctx: pipeline.publish_work(_with_remix_source(ctx, allow_remix), platforms),
                payload.get("store_page"), request_id)
