# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent API for game publishing (contract §5) — what the backend's
``game_studio`` tools call from their Blender scripts.

Every function returns at once with a JSON-safe dict. The GLB export runs
here, on the main thread the agent script already holds; Godot, hashing
and uploads run on worker threads (``jobs``), polled with
``game_job_status``. Nothing depends on ``ui/`` registration, so this works
in ``--background``.

Sandbox note: process-, path- and network-capable modules (runner,
locator, exporter, jobs, pipeline, store client) are imported lazily inside
functions and are denied to agent scripts (``sandbox_modules``), so this
module never hands a script a way to start an arbitrary process or write
an arbitrary path. Home-directory paths are reported as ``~``.
"""

from __future__ import annotations

import json
import os

import bpy

from ..constants import GODOT_PATH_CONFIG_KEY, STORE_PROP
from . import roles, spec as game_spec

ROLE_LIST_LIMIT = 200


def _redact(value):
    """JSON-safe copy with the home directory shown as ``~``."""
    home = os.path.expanduser("~")
    if isinstance(value, dict):
        return {str(k): _redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        return value.replace(home, "~") if home and len(home) > 1 else value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _scene():
    return bpy.context.scene


def _store_identity(scene) -> dict:
    try:
        data = json.loads(scene.get(STORE_PROP) or "{}")
    except (ValueError, TypeError, AttributeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _godot_config() -> str:
    try:
        from mixar.config.config import get_godot_path
        return get_godot_path()
    except Exception:
        return ""


def _godot_status() -> dict:
    from . import godot_locator
    verdict = godot_locator.cached_status()
    if verdict is None:
        godot_locator.locate_async(_godot_config())
        return {"found": False, "checking": True, "path": None, "version": None}
    return {"found": bool(verdict.get("found")), "checking": godot_locator.is_locating(),
            "path": verdict.get("path") or None, "version": verdict.get("version") or None,
            "godot": verdict.get("godot") or None, "error": verdict.get("error"),
            "message": verdict.get("message") or ""}


def _spec_report(scene) -> dict:
    from .exporter import current_spec
    spec, _objects = current_spec(scene)
    errors, warnings = game_spec.validate_spec(spec)
    settings = {k: v for k, v in spec.items() if k not in ("nodes", "schema", "scene_file",
                                                           "up_axis", "generator")}
    return {"settings": settings, "node_count": len(spec["nodes"]), "valid": not errors,
            "errors": errors, "warnings": warnings}


def game_status() -> dict:
    from . import jobs
    jobs.drain()
    scene = _scene()
    objects = roles.game_objects(scene)
    tagged = [{"object": obj.name, "role": roles.get_role(obj), "params": roles.get_params(obj)}
              for obj in objects if roles.get_role(obj)]
    return _redact({
        "godot": _godot_status(),
        "roles": {**roles.role_summary([o for o in objects if roles.in_game(o)]),
                  "assignments": tagged[:ROLE_LIST_LIMIT], "truncated": len(tagged) > ROLE_LIST_LIMIT},
        "spec": _spec_report(scene),
        "store": _store_identity(scene),
        "last_build": jobs.last("build"),
        "last_export": jobs.last("export"),
        "last_publish": jobs.last("publish"),
    })


def set_game_roles(assignments=None) -> dict:
    scene = _scene()
    applied, errors = [], []
    for item in assignments or ():
        if not isinstance(item, dict):
            errors.append({"object": None, "error": "each assignment must be an object"})
            continue
        name = str(item.get("object") or "")
        obj = scene.objects.get(name) if name else None
        if obj is None:
            errors.append({"object": name, "error": "no such object in the active scene"})
            continue
        done, problems = roles.set_role(obj, item.get("role"), item.get("params"))
        if not done:
            errors.append({"object": name, "error": "; ".join(problems)})
            continue
        applied.append({"object": name, "role": roles.get_role(obj), "params": roles.get_params(obj)})
        errors.extend({"object": name, "error": p} for p in problems)
    report = _spec_report(scene)
    return _redact({"ok": not errors, "applied": applied, "errors": errors,
                    "spec_errors": report["errors"], "spec_warnings": report["warnings"]})


def auto_assign_roles(apply=False) -> dict:
    """Heuristic suggestions for untagged objects; ``apply=True`` tags them."""
    scene = _scene()
    by_name = {obj.name: obj for obj in roles.game_objects(scene)}
    suggestions = roles.suggest_roles(list(by_name.values()))
    if apply:
        for item in suggestions:
            if item["role"]:
                roles.set_role(by_name[item["object"]], item["role"])
    return _redact({"ok": True, "assignments": suggestions, "applied": bool(apply)})


def configure_game(title=None, template=None, rules=None, player=None, camera=None,
                   world=None, ui=None) -> dict:
    scene = _scene()
    changes = {"title": title, "template": template, "rules": rules, "player": player,
               "camera": camera, "world": world, "ui": ui}
    merged, errors = game_spec.merge_settings(game_spec.load_settings(scene), changes)
    game_spec.save_settings(scene, merged)
    from .exporter import current_spec
    spec, _objects = current_spec(scene)
    return _redact({"ok": not errors, "errors": errors, "spec": spec})


def start_game_build(play=False) -> dict:
    from . import launch
    return _redact(launch.start("build", _scene(), play=play))


def start_game_export(platforms=None) -> dict:
    platforms, errors = game_spec.validate_platforms(platforms)
    if errors:
        return {"ok": False, "job_id": None, "state": "failed", "error_code": "bad_platform",
                "error": "; ".join(errors)}
    from . import launch
    return _redact(launch.start("export", _scene(), platforms=platforms))


def _publish_summary(scene, platforms, page) -> dict:
    report = _spec_report(scene)
    identity = _store_identity(scene)
    settings = report["settings"]
    slug = identity.get("slug") or settings.get("slug")
    return {
        "title": settings.get("title"), "slug": slug, "platforms": platforms,
        "price_cents": page.get("price_cents", 0), "store_page": page,
        "files": ["scene.glb"] + [f"{slug}-{platform}.zip" for platform in platforms],
        "action": "update" if identity.get("game_id") else "create",
        # Only a URL the store returned earlier; the store owns its URLs.
        "store_url": identity.get("store_url") or None,
        "node_count": report["node_count"], "errors": report["errors"],
        "warnings": report["warnings"],
        "review": "The store page goes live at once; builds become playable "
                  "only after a moderator approves them.",
    }


def _ask_user(request_id: str, summary: dict) -> None:
    """A sticky toast with Publish / Cancel; the buttons run the UI operators."""
    try:
        from mixar.modules.common.i18n import n_, rpt_
        from mixar.modules.common.notifications import get_notification_store
        from mixar.modules.common.notifications.store import NotificationAction
        platforms = ", ".join(summary["platforms"])
        get_notification_store().push(
            "info", rpt_("Publish \"{title}\" to the Mixar Store?").format(title=summary["title"]),
            body=rpt_("Mixie asks to publish it for {platforms}. Builds are playable after review.")
            .format(platforms=platforms),
            actions=[NotificationAction(label=n_("Publish"), operator="mixar.game_publish_approve",
                                        style="primary"),
                     NotificationAction(label=n_("Cancel"), operator="mixar.game_publish_decline")],
            ttl_ms=int(10 * 60 * 1000), id=f"game-publish-{request_id}")
    except Exception:  # noqa: BLE001 — the Game tab still offers the same buttons
        pass


def start_game_publish(store_page=None, platforms=None, confirm=False) -> dict:
    """``confirm=False`` only previews. ``confirm=True`` creates a request the
    USER must approve in the app (toast or Game tab); nothing here can
    approve it, and ``--background`` has nobody to ask."""
    platforms, platform_errors = game_spec.validate_platforms(platforms)
    page, page_errors = game_spec.normalize_store_page(store_page)
    errors = platform_errors + page_errors
    if errors:
        return {"ok": False, "job_id": None, "state": "failed", "error_code": "bad_request",
                "error": "; ".join(errors), "errors": errors}
    scene = _scene()
    summary = _publish_summary(scene, platforms, page)
    if not confirm:
        return _redact({"ok": not summary["errors"], "needs_confirmation": True, "summary": summary})
    if bpy.app.background:
        return {"ok": False, "job_id": None, "state": "failed", "error_code": "approval_required_ui",
                "error": "Publishing needs the user's approval in the Mixar app; "
                         "this session has no interface."}
    if summary["errors"]:
        return _redact({"ok": False, "job_id": None, "state": "failed", "error_code": "invalid_spec",
                        "error": "; ".join(summary["errors"]), "errors": summary["errors"]})
    from . import approvals
    request_id = approvals.create(summary, {"platforms": platforms, "store_page": page,
                                            "scene_name": scene.name})
    _ask_user(request_id, summary)
    return _redact({"ok": True, "state": "awaiting_user_approval", "request_id": request_id,
                    "job_id": request_id, "summary": summary,
                    "message": "Waiting for the user to click Publish in Mixar (expires in 10 minutes)."})


def game_job_status(job_id=None) -> dict:
    from . import approvals, jobs
    jobs.drain()
    job = jobs.get(job_id)
    if job is not None:
        return _redact(job)
    request = approvals.get(job_id)
    if request is not None:
        return {"job_id": request["request_id"], "kind": "publish", "state": request["state"]
                if request["state"] != "approved" else "running", "pct": 0.0,
                "message": "Waiting for the user to approve the publish."
                if request["state"] == "awaiting_user_approval" else "",
                "result": None, "error": request["error"], "error_code": request["error_code"]}
    return {"job_id": job_id, "kind": None, "state": "failed", "pct": 0, "message": "",
            "result": None, "error": "No such job.", "error_code": "unknown_job"}


def cancel_game_job(job_id=None) -> dict:
    from . import approvals, jobs
    return {"ok": jobs.cancel(job_id) or approvals.cancel(job_id), "job_id": job_id}


def play_game() -> dict:
    """Launch the last built game window (non-blocking)."""
    from . import godot_locator, godot_runner, jobs
    from .exporter import current_spec, game_dir_for
    from .pipeline import paths
    last = jobs.last("build") or jobs.last("export") or jobs.last("publish")
    project = ((last or {}).get("result") or {}).get("project_dir")
    if not project:
        spec, _objects = current_spec(_scene())
        project = paths(game_dir_for(spec["slug"]))["project"]
    if not os.path.isfile(os.path.join(project, "project.godot")):
        return {"ok": False, "error_code": "not_built",
                "error": "Build the game first (start_game_build)."}
    config = _godot_config()

    def work():
        verdict = godot_locator.locate(config)
        if verdict.get("found"):
            godot_runner.launch(verdict["path"], ["--path", project, "--mixar-play"])

    import threading
    threading.Thread(target=work, name="mixar-game-play", daemon=True).start()
    return {"ok": True, "launching": True}
