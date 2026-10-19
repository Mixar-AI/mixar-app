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

from ..constants import STORE_PROP, platform_list
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


def _spec_report(scene, checked=None) -> dict:
    from .exporter import inspect
    checked = checked or inspect(scene)
    spec = checked["spec"]
    settings = {k: v for k, v in spec.items() if k not in ("nodes", "schema", "scene_file",
                                                           "up_axis", "generator")}
    return {"settings": settings, "node_count": len(spec["nodes"]), "valid": not checked["errors"],
            "errors": checked["errors"], "warnings": checked["warnings"] + checked["combat_warnings"]}


def _characters_report(checked) -> list:
    """Contract v1.3 §5: per character its rig, clips by state, missing
    states and the timing source of each attack/dodge clip."""
    from .characters import public
    timing = checked["timing"]
    return [{**public(c), "timing": {clip: timing[clip] for names in c["clips"].values()
                                     for clip in names if clip in timing}}
            for c in checked["characters"]]


def game_status() -> dict:
    from . import jobs
    jobs.drain()
    from .exporter import inspect
    scene = _scene()
    objects = roles.game_objects(scene)
    tagged = [{"object": obj.name, "role": roles.get_role(obj), "params": roles.get_params(obj)}
              for obj in objects if roles.get_role(obj)]
    checked = inspect(scene)
    return _redact({
        "godot": _godot_status(),
        "roles": {**roles.role_summary([o for o in objects if roles.in_game(o)]),
                  "assignments": tagged[:ROLE_LIST_LIMIT], "truncated": len(tagged) > ROLE_LIST_LIMIT},
        "spec": _spec_report(scene, checked),
        "characters": _characters_report(checked),
        "excluded": checked["excluded"][:ROLE_LIST_LIMIT],
        "decor_auto": checked["decor_auto"][:ROLE_LIST_LIMIT],
        "procedural_materials": checked["procedural_materials"][:ROLE_LIST_LIMIT],
        "store": _store_identity(scene),
        "last_build": jobs.last("build"),
        "last_export": jobs.last("export"),
        "last_publish": jobs.last("publish"),
    })


def _hierarchy(scene):
    from .assemblies import Hierarchy
    return Hierarchy(roles.game_objects(scene))


def _clear_parts(hierarchy, root, keep_deliberate: bool = False) -> None:
    """One role per assembly: drop part-level tags inside ``root``
    (deliberate "This part only" tags too unless ``keep_deliberate``)."""
    for part in hierarchy.descendants(root):
        if roles.get_role(part) and not (keep_deliberate and roles.is_deliberate_part(part)):
            roles.set_role(part, None)


def set_game_roles(assignments=None) -> dict:
    """Tag objects. A role belongs to an ASSEMBLY: naming a part tags its
    assembly root (``applied_to``) and clears part-level tags inside it,
    unless the assignment says ``"part_only": true``."""
    scene = _scene()
    hierarchy = _hierarchy(scene)
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
        part_only = bool(item.get("part_only"))
        target = obj if part_only else hierarchy.assembly_root(obj)
        done, problems = roles.set_role(target, item.get("role"), item.get("params"),
                                        part_only=part_only and target is not hierarchy.assembly_root(obj))
        if not done:
            errors.append({"object": name, "error": "; ".join(problems)})
            continue
        if not part_only:
            _clear_parts(hierarchy, target)
        applied.append({"object": name, "applied_to": target.name, "role": roles.get_role(target),
                        "params": roles.get_params(target),
                        "parts": len(hierarchy.parts(target))})
        errors.extend({"object": name, "error": p} for p in problems)
    report = _spec_report(scene)
    return _redact({"ok": not errors, "applied": applied, "errors": errors,
                    "spec_errors": report["errors"], "spec_warnings": report["warnings"]})


def auto_assign_roles(apply=False, overwrite=False) -> dict:
    """Score each ASSEMBLY (root name + part names) and suggest a role for
    its root; ``apply=True`` tags them. Assets the user tagged (root tag or
    a "This part only" part) are kept; stale part tags from the old per-part
    auto-assign are replaced. ``overwrite=True`` re-assigns everything."""
    from .auto_roles import suggest_roles
    scene = _scene()
    objects = roles.game_objects(scene)
    by_name = {obj.name: obj for obj in objects}
    template = game_spec.load_settings(scene).get("template")
    suggestions = suggest_roles(objects, overwrite=bool(overwrite), template=template)
    if apply:
        hierarchy = _hierarchy(scene)
        if overwrite:
            for root in hierarchy.assemblies():
                if not hierarchy.is_container(root):
                    roles.set_role(root, None)
                    _clear_parts(hierarchy, root)
        for item in suggestions:
            if item["role"]:
                root = by_name[item["object"]]
                roles.set_role(root, item["role"])
                _clear_parts(hierarchy, root, keep_deliberate=not overwrite)
        if not overwrite:  # stale part tags of assets that got no new role
            for root in hierarchy.assemblies():
                if not hierarchy.is_container(root) and not roles.get_role(root):
                    _clear_parts(hierarchy, root, keep_deliberate=True)
    return _redact({"ok": True, "assignments": suggestions, "applied": bool(apply)})


def configure_game(title=None, template=None, rules=None, player=None, camera=None,
                   world=None, ui=None, combat=None) -> dict:
    """``combat`` (v1.3, boss_fight) overrides clip windows in seconds and
    the boss/player tuning; a clip set to null drops its override."""
    scene = _scene()
    changes = {"title": title, "template": template, "rules": rules, "player": player,
               "camera": camera, "world": world, "ui": ui, "combat": combat}
    merged, errors = game_spec.merge_settings(game_spec.load_settings(scene), changes)
    game_spec.save_settings(scene, merged)
    from .exporter import inspect
    checked = inspect(scene)
    return _redact({"ok": not errors, "errors": errors, "spec": checked["spec"],
                    "warnings": checked["combat_warnings"]})


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
        platforms = platform_list(summary["platforms"])
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
        settled = "done" if request["kind"] == "launch" else "running"
        return {"job_id": request["request_id"], "kind": request["kind"], "state": request["state"]
                if request["state"] != "approved" else settled, "pct": 0.0,
                "message": f"Waiting for the user to approve the {request['kind']}."
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


# --- Mixar Library (contract v1.1) ------------------------------------------------

def _library_refresh(force=False):
    """The running/started refresh job id, or None when the listing is fresh."""
    from mixar.config.config import get_community_api_url
    from . import jobs, library, library_install
    running = jobs.running("library")
    if running is not None:
        return running["job_id"]
    _games, age, _error = library.listing()
    if not force and age < library.LISTING_STALE_S:
        return None
    return jobs.start("library", library_install.refresh_work(library.library_root(),
                                                              get_community_api_url()))


def library_list(refresh=False) -> dict:
    """Owned games with their install state on this computer. Returns the
    last listing at once and refreshes it in the background when stale."""
    from . import jobs, library
    jobs.drain()
    job_id = _library_refresh(bool(refresh))
    games, _age, error = library.listing()
    index = library.installed() or {}
    platform = library.host_platform()
    out, listed = [], set()
    for game in games or ():
        build = game["builds"].get(platform)
        record = index.get(game["slug"])
        listed.add(game["slug"])
        out.append({
            "slug": game["slug"], "title": game["title"], "game_id": game["game_id"],
            "platforms": sorted(game["builds"]),
            "available": {"build_id": build["build_id"], "version": build["version"]} if build else None,
            "installed": _installed_view(record),
            "update_available": bool(build and record and record.get("build_id") != build["build_id"]),
        })
    for slug, record in index.items():
        if slug not in listed:
            out.append({"slug": slug, "title": record.get("title") or slug, "game_id": record.get("game_id"),
                        "platforms": [], "available": None, "installed": _installed_view(record),
                        "update_available": False})
    return _redact({"ok": games is not None or error is None, "platform": platform, "games": out,
                    "loading": games is None, "refresh_job_id": job_id, "error": error})


def _installed_view(record):
    if not record:
        return None
    check = record.get("selftest")
    return {"build_id": record.get("build_id"), "version": record.get("version"),
            "selftest": "not_run" if check is None else ("passed" if check.get("ok") else "failed"),
            "selftest_error": (check or {}).get("error")}


def start_library_install(slug=None) -> dict:
    """Install or update ``slug`` for this computer (a job; poll
    ``game_job_status``): download, verify, extract — nothing is executed.
    Installing is allowed for the agent; running the game is not."""
    from mixar.config.config import get_community_api_url
    from . import jobs, library, library_install
    slug = str(slug or "")
    if not slug:
        return {"ok": False, "job_id": None, "state": "failed", "error_code": "bad_request",
                "error": "slug is required"}
    running = jobs.running("install")
    if running is not None:
        return {"ok": False, "job_id": running["job_id"], "state": "failed", "error_code": "busy",
                "error": "Another game is installing."}
    # Agents never execute the download: no self-test here (it runs before
    # the first user-approved launch).
    job_id = jobs.start("install", library_install.install_by_slug_work(
        library.library_root(), get_community_api_url(), slug, library.host_platform(),
        run_selftest=False))
    return {"ok": True, "job_id": job_id, "state": "running"}


def start_library_uninstall(slug=None) -> dict:
    from . import jobs, library, library_install
    job_id = jobs.start("uninstall", library_install.uninstall_work(library.library_root(), str(slug or "")))
    return {"ok": True, "job_id": job_id, "state": "running"}


def launch_library_game(slug=None) -> dict:
    """Launching runs a program, so only the user may do it: this asks them
    in the app (toast / Library panel) and returns ``awaiting_user_approval``;
    ``--background`` has nobody to ask."""
    from . import approvals, library
    slug = str(slug or "")
    if bpy.app.background:
        return {"ok": False, "job_id": None, "state": "failed", "error_code": "approval_required_ui",
                "error": "Launching a game needs the user's click in the Mixar app."}
    record = (library.installed() or {}).get(slug)
    if record is None:
        return {"ok": False, "job_id": None, "state": "failed", "error_code": "not_installed",
                "error": "That game is not installed (start_library_install first)."}
    summary = {"title": record.get("title") or slug, "slug": slug, "version": record.get("version")}
    request_id = approvals.create(summary, {"slug": slug}, kind="launch")
    _ask_user_launch(request_id, summary)
    return {"ok": True, "state": "awaiting_user_approval", "request_id": request_id,
            "job_id": request_id, "summary": summary}


def _ask_user_launch(request_id: str, summary: dict) -> None:
    try:
        from mixar.modules.common.i18n import n_, rpt_
        from mixar.modules.common.notifications import get_notification_store
        from mixar.modules.common.notifications.store import NotificationAction
        get_notification_store().push(
            "info", rpt_("Play \"{title}\"?").format(title=summary["title"]),
            body=rpt_("Mixie asks to launch this game from your Library."),
            actions=[NotificationAction(label=n_("Play"), operator="mixar.game_library_launch_approve",
                                        style="primary"),
                     NotificationAction(label=n_("Cancel"), operator="mixar.game_library_launch_decline")],
            ttl_ms=int(10 * 60 * 1000), id=f"game-launch-{request_id}")
    except Exception:  # noqa: BLE001 — the Library panel offers the same buttons
        pass
