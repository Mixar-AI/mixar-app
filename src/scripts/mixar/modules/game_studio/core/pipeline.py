# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Worker bodies for the build / export / publish jobs.

Every input is captured on the main thread into a plain ``ctx`` dict
(paths, config values, store identity) before the job starts; these
functions then run on a worker thread and never touch ``bpy``. The one
write back into Blender data — the published game's identity — is queued
with ``jobs.call_on_main``.
"""

from __future__ import annotations

import json
import os
import time

from ..constants import (BUILDS_DIRNAME, EXPORT_DIRNAME, PROJECT_DIRNAME, RESULTS_DIRNAME,
                         SPEC_FILE, STORE_PROP)
from . import godot_locator, godot_runner, jobs
from .jobs import JobError


def paths(game_dir: str) -> dict:
    return {
        "game_dir": game_dir,
        "spec": os.path.join(game_dir, EXPORT_DIRNAME, SPEC_FILE),
        "project": os.path.join(game_dir, PROJECT_DIRNAME),
        "builds": os.path.join(game_dir, BUILDS_DIRNAME),
        "results": os.path.join(game_dir, RESULTS_DIRNAME),
    }


def _godot_verdict(ctx: dict) -> dict:
    verdict = godot_locator.locate(ctx.get("godot_config", ""))
    if not verdict.get("found"):
        raise JobError(verdict.get("message") or "Mixar Godot was not found.",
                       verdict.get("error") or "godot_missing")
    return verdict


def _godot(ctx: dict) -> str:
    return _godot_verdict(ctx)["path"]


# Store art rendered by the fork from the built game (never a window grab of
# Mixar's UI): (media kind, file name, size).
CAPTURES = (("capsule", "capsule.png", "1280x720"), ("screenshot", "screenshot-1.png", "1920x1080"))
CAPTURE_TIMEOUT_S = 180.0


def capture_stage(ctx: dict, handle, verdict: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """``([(kind, path)], warnings)``. Only when the fork advertises the
    ``capture`` capability: an older fork would treat the flag as unknown
    and open its editor. A failed capture is a warning, never a failure."""
    if "capture" not in (verdict.get("capabilities") or ()):
        return [], ["This Mixar Godot cannot render store images; the game was published without them."]
    where = paths(ctx["game_dir"])
    os.makedirs(where["results"], exist_ok=True)
    images, warnings = [], []
    for kind, name, size in CAPTURES:
        out = os.path.join(where["results"], name)
        try:
            os.remove(out)
        except OSError:
            pass
        result = godot_runner.run(
            verdict["path"], ["--path", where["project"], "--mixar-capture", out,
                              "--mixar-capture-size", size],
            os.path.join(where["results"], f"capture-{kind}.json"), "capture",
            cancel=handle.cancel_event, timeout=CAPTURE_TIMEOUT_S)
        produced = result.get("artifact") or out
        if result.get("ok") and os.path.isfile(produced):
            images.append((kind, produced))
        else:
            warnings.append(f"The store {kind} image could not be rendered "
                            f"({result.get('error_code') or 'failed'}).")
    return images, warnings


def _scaled(handle, low: float, high: float):
    def report(pct, step, message):
        handle.progress(low + (high - low) * pct / 100.0, message or step)
    return report


def _fork_failure(result: dict) -> JobError:
    return JobError(result.get("error") or "Godot failed.", result.get("error_code") or "failed",
                    result)


def build_stage(ctx: dict, handle, godot: str, low=0.0, high=100.0) -> dict:
    where = paths(ctx["game_dir"])
    os.makedirs(where["results"], exist_ok=True)
    handle.progress(low, "Building the Godot project", force=True)
    result = godot_runner.run(
        godot, ["--headless", "--mixar-build", where["spec"], "--mixar-out", where["project"]],
        os.path.join(where["results"], "build.json"), "build",
        on_progress=_scaled(handle, low, high), cancel=handle.cancel_event)
    if not result.get("ok"):
        raise _fork_failure(result)
    return result


PLATFORM_LABELS = {"web": "Web", "macos": "macOS", "windows": "Windows", "linux": "Linux"}


def export_stage(ctx: dict, handle, godot: str, platforms, low=0.0, high=100.0,
                 skipped: list | None = None) -> list[dict]:
    """Export each platform into its own folder. A desktop platform whose
    export templates are missing is skipped with a warning appended to
    ``skipped`` (when given) as long as another platform exports; every
    other failure fails the job."""
    where = paths(ctx["game_dir"])
    os.makedirs(where["results"], exist_ok=True)
    artifacts, span = [], (high - low) / max(1, len(platforms))
    for index, platform in enumerate(platforms):
        start = low + span * index
        handle.progress(start, f"Exporting {platform}", force=True)
        result = godot_runner.run(
            godot, ["--headless", "--path", where["project"], "--mixar-export", platform,
                    "--mixar-out", os.path.join(where["builds"], platform)],
            os.path.join(where["results"], f"export-{platform}.json"), "export",
            on_progress=_scaled(handle, start, start + span), cancel=handle.cancel_event)
        if not result.get("ok"):
            if (skipped is not None and result.get("error_code") == "templates_missing"
                    and platform != "web" and len(platforms) > 1):
                skipped.append(f"{PLATFORM_LABELS.get(platform, platform)} build skipped: "
                               "export templates not installed.")
                continue
            raise _fork_failure(result)
        artifact = result.get("artifact")
        if not artifact or not os.path.isfile(artifact):
            raise JobError(f"The {platform} export produced no file.", "export_failed", result)
        artifacts.append({"platform": platform, "artifact": artifact,
                          "size_bytes": os.path.getsize(artifact),
                          # Desktop only: the store refuses launch/signing on web and
                          # linux builds (the fork reports launch "index.html" for web).
                          "launch": _for_platform(result.get("launch"), platform)
                          if platform in DESKTOP_STORE_PLATFORMS else None,
                          "signing": _for_platform(result.get("signing"), platform)
                          if platform in DESKTOP_STORE_PLATFORMS else None,
                          "warnings": list(result.get("warnings") or [])})
    if not artifacts:
        raise JobError("No platform could be exported.", "templates_missing")
    return artifacts


DESKTOP_STORE_PLATFORMS = ("macos", "windows")


def _for_platform(value, platform: str):
    """The fork reports ``launch``/``signing`` as ``{platform: value}`` (v1.1);
    a plain string is taken as-is. None when absent (web builds)."""
    if isinstance(value, dict):
        value = value.get(platform)
    return str(value) if isinstance(value, str) and value else None


def _build_summary(ctx: dict, result: dict) -> dict:
    return {"game_dir": ctx["game_dir"], "project_dir": result.get("project_dir") or paths(ctx["game_dir"])["project"],
            "warnings": list(ctx.get("warnings") or []) + list(result.get("warnings") or []),
            "stats": result.get("stats") or {}, "duration_s": result.get("duration_s")}


def build_work(ctx: dict, play: bool = False):
    def work(handle):
        godot = _godot(ctx)
        result = build_stage(ctx, handle, godot, 0.0, 95.0)
        summary = _build_summary(ctx, result)
        if play:
            summary["playing"] = godot_runner.launch(godot, ["--path", summary["project_dir"], "--mixar-play"])
        return summary
    return work


def export_work(ctx: dict, platforms):
    def work(handle):
        godot = _godot(ctx)
        build = build_stage(ctx, handle, godot, 0.0, 40.0)
        skipped = []
        artifacts = export_stage(ctx, handle, godot, platforms, 40.0, 98.0, skipped)
        summary = {**_build_summary(ctx, build), "artifacts": artifacts}
        summary["warnings"] = summary["warnings"] + skipped
        return summary
    return work


def store_fields(ctx: dict, platforms) -> dict:
    page = ctx.get("store_page") or {}
    return {"title": ctx["title"], "slug": ctx["slug"], "tagline": page.get("tagline", ""),
            "description": page.get("description", ""), "genres": page.get("genres", []),
            "tags": page.get("tags", []), "price_cents": page.get("price_cents", 0),
            "platforms": list(platforms), "content_rating": page.get("content_rating", "everyone")}


def _create_or_update(client, ctx: dict, fields: dict) -> dict:
    from .store_client import StoreError
    game_id = (ctx.get("store") or {}).get("game_id")
    if game_id:
        try:
            return client.update_game(game_id, {k: v for k, v in fields.items() if k != "slug"})
        except StoreError as exc:
            if exc.status not in (403, 404):
                raise
    try:
        return client.create_game(fields)
    except StoreError as exc:
        if exc.status != 409:
            raise
        mine = exc.detail.get("game_id")
        if mine:  # our own draft under this slug (the scene lost its identity)
            return client.update_game(str(mine), {k: v for k, v in fields.items() if k != "slug"})
        # Taken by someone else: let the store choose a free slug.
        return client.create_game({k: v for k, v in fields.items() if k != "slug"})


def _upload_media(client, game_id: str, kind: str, path: str, cancel) -> str:
    """Best effort: a failed image upload is a warning, never a failed publish."""
    from .store_client import StoreError, sha256_file
    if not path or not os.path.isfile(path):
        return ""
    try:
        digest, size = sha256_file(path, cancel)
        slot = client.create_media(game_id, kind, os.path.basename(path), size, digest)
        client.upload(slot["put_url"], slot.get("headers") or {}, path, None, cancel)
        client.complete_media(game_id, str(slot["upload_id"]))
    except (StoreError, KeyError, OSError) as exc:
        return f"The {kind} image was not uploaded ({getattr(exc, 'message', exc.__class__.__name__)})."
    return ""


def _upload_build(client, handle, game_id: str, item: dict, version: str, start: float, span: float) -> dict:
    from .store_client import StoreError, sha256_file
    handle.progress(start, f"Uploading the {item['platform']} build", force=True)
    digest, size = sha256_file(item["artifact"], handle.cancel_event)
    build = client.create_build(game_id, item["platform"], version,
                                os.path.basename(item["artifact"]), size, digest,
                                launch=item.get("launch"), signing=item.get("signing"))
    build_id = str(build.get("build_id") or "")
    if not build_id or not build.get("put_url"):
        raise StoreError("The store did not return an upload slot.", "bad_response")
    client.upload(build["put_url"], build.get("headers") or {}, item["artifact"],
                  lambda f: handle.progress(start + span * 0.9 * f, None), handle.cancel_event)
    done = client.complete_build(game_id, build_id)
    return {"build_id": build_id, "platform": item["platform"], "version": version,
            "size_bytes": size, "sha256": digest, "launch": item.get("launch"),
            "signing": item.get("signing"),
            "review_status": (done.get("build") or done).get("review_status", "pending")}


def _store_failure(exc, ctx: dict) -> JobError:
    if exc.code == "profile_required":
        link = f"{ctx['web_base'].rstrip('/')}/settings/profile"
        return JobError(f"Claim your Mixar community profile first, then publish again: {link}",
                        exc.code, {"profile_url": link})
    return JobError(exc.message, exc.code)


def publish_work(ctx: dict, platforms, client_factory=None):
    def work(handle):
        from .store_client import StoreClient, StoreError
        verdict = _godot_verdict(ctx)
        godot = verdict["path"]
        build_stage(ctx, handle, godot, 0.0, 22.0)
        skipped = []
        artifacts = export_stage(ctx, handle, godot, platforms, 22.0, 48.0, skipped)
        offered = [item["platform"] for item in artifacts]  # what the store page offers
        handle.progress(49.0, "Rendering store images", force=True)
        images, warnings = capture_stage(ctx, handle, verdict)
        warnings = skipped + warnings
        client = (client_factory or StoreClient)(ctx["api_base"])
        try:
            handle.progress(56.0, "Creating the store page", force=True)
            game = _create_or_update(client, ctx, store_fields(ctx, offered))
            game_id = str(game.get("game_id") or game.get("id") or "")
            if not game_id:
                raise StoreError("The store did not return a game id.", "bad_response")
            for kind, path in images:
                warning = _upload_media(client, game_id, kind, path, handle.cancel_event)
                if warning:
                    warnings.append(warning)
            builds, version = [], time.strftime("%Y.%m.%d.%H%M%S", time.gmtime())
            span = 38.0 / max(1, len(artifacts))
            for index, item in enumerate(artifacts):
                builds.append(_upload_build(client, handle, game_id, item, version,
                                            58.0 + span * index, span))
            handle.progress(97.0, "Publishing", force=True)
            page = client.publish(game_id) or {}
        except StoreError as exc:
            raise _store_failure(exc, ctx) from exc
        # The store owns its URLs: open what it returns, never a composed one.
        store_url = str(page.get("store_url") or game.get("store_url") or "") or None
        slug = str(page.get("slug") or game.get("slug") or ctx["slug"])
        _remember(ctx.get("scene_name", ""), {"game_id": game_id, "slug": slug, "store_url": store_url})
        by_id = {b["build_id"]: b for b in builds}
        for remote in page.get("builds") or ():
            local = by_id.get(str(remote.get("build_id") or remote.get("id") or ""))
            if local is not None and remote.get("review_status"):
                local["review_status"] = remote["review_status"]
        result = {"game_id": str(page.get("game_id") or game_id), "store_url": store_url,
                  "review_status": str(page.get("review_status") or "pending"), "builds": builds}
        if warnings:
            result["warnings"] = warnings
        return result
    return work


def _remember(scene_name: str, identity: dict) -> None:
    def write():
        import bpy
        scene = bpy.data.scenes.get(scene_name)
        if scene is not None:
            scene[STORE_PROP] = json.dumps(identity, sort_keys=True)
    jobs.call_on_main(write)
