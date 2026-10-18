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

from . import exporter, jobs, pipeline


def busy() -> dict | None:
    job = jobs.running()
    if job is None:
        return None
    return {"ok": False, "job_id": job["job_id"], "state": "failed", "error_code": "busy",
            "error": f"A {job['kind']} job is still running."}


def context(scene, package: dict, store_page=None, capsule: str = "") -> dict:
    from mixar.config.config import get_community_api_url, get_community_web_url
    from .agent_api import _godot_config, _store_identity
    return {"game_dir": package["game_dir"], "title": package["spec"]["title"],
            "slug": package["spec"]["slug"], "warnings": list(package["warnings"]),
            "godot_config": _godot_config(), "api_base": get_community_api_url(),
            "web_base": get_community_web_url(), "store": _store_identity(scene),
            "scene_name": scene.name, "store_page": store_page or {}, "capsule": capsule}


def refused(package: dict) -> dict:
    return {"ok": False, "job_id": None, "state": "failed", "error_code": "invalid_spec",
            "error": "; ".join(package["errors"]), "errors": package["errors"],
            "warnings": package["warnings"]}


def _run(kind: str, scene, make_work, store_page=None, job_id=None, capsule_hook=None) -> dict:
    blocked = busy()
    if blocked:
        return blocked
    package = exporter.write_package(scene)
    if not package["ok"]:
        return refused(package)
    capsule = capsule_hook(package["export_dir"]) if capsule_hook else ""
    job_id = jobs.start(kind, make_work(context(scene, package, store_page, capsule or "")), job_id)
    return {"ok": True, "job_id": job_id, "state": "running",
            "warnings": package["warnings"], "game_dir": package["game_dir"]}


def start(kind: str, scene, play=False, platforms=None) -> dict:
    if kind == "build":
        return _run("build", scene, lambda ctx: pipeline.build_work(ctx, bool(play)))
    if kind == "export":
        return _run("export", scene, lambda ctx: pipeline.export_work(ctx, platforms))
    raise ValueError(kind)


def start_approved_publish(request_id: str, payload: dict, capsule_hook=None) -> dict:
    """The user approved ``request_id`` in the UI: export and publish."""
    scene = bpy.data.scenes.get(payload.get("scene_name", ""))
    if scene is None:
        return {"ok": False, "job_id": request_id, "state": "failed", "error_code": "scene_missing",
                "error": "The scene this publish was requested for no longer exists."}
    if scene != bpy.context.scene:
        return {"ok": False, "job_id": request_id, "state": "failed", "error_code": "wrong_scene",
                "error": f"Switch to the scene '{scene.name}' to publish it."}
    platforms = list(payload.get("platforms") or ["web"])
    return _run("publish", scene, lambda ctx: pipeline.publish_work(ctx, platforms),
                payload.get("store_page"), request_id, capsule_hook)
