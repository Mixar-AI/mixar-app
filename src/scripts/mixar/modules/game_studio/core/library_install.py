# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Library worker bodies: refresh, install/update (+ self-test), uninstall,
and resolving/launching an installed game. Worker threads only — no bpy.

Install = the store's record is the truth: the download's sha256 and size
must equal what ``/me/library`` recorded at upload (and what the download
endpoint repeats) or nothing is extracted. Extraction is ``safe_extract``
into a staging folder renamed into place, so a half-install never looks
installed. Quarantine attributes are never touched: the app writes these
files itself, and it never strips quarantine from anything else.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import time

from . import library, safe_extract
from .jobs import JobError

SELFTEST_PREFIX = "MIXAR_SELFTEST"
SELFTEST_TIMEOUT_S = 120.0


def refresh_work(root: str, api_base: str, client_factory=None):
    def work(handle):
        from .store_client import StoreClient, StoreError
        handle.progress(10.0, "Loading your library", force=True)
        library.load_index(root)
        removed = library.prune(root)
        try:
            data = (client_factory or StoreClient)(api_base).library()
        except StoreError as exc:
            library.set_listing(None, exc.message)
            raise JobError(exc.message, exc.code) from exc
        games = library.normalize_listing(data)
        library.set_listing(games)
        return {"games": len(games), "pruned": removed}
    return work


def executable_for(install_dir: str, launch: str, platform: str) -> str:
    """The program to run for an installed build (``launch`` is the entry
    point inside the zip: ``<Title>.app`` or ``<Title>.exe``)."""
    entry = safe_extract.inside(install_dir, launch)
    if platform == "macos" and entry.endswith(".app"):
        macos = os.path.join(entry, "Contents", "MacOS")
        name = ""
        try:
            with open(os.path.join(entry, "Contents", "Info.plist"), "rb") as handle:
                name = str(plistlib.load(handle).get("CFBundleExecutable") or "")
        except (OSError, ValueError, plistlib.InvalidFileException):
            pass
        if not name and os.path.isdir(macos):
            programs = sorted(os.listdir(macos))
            name = programs[0] if len(programs) == 1 else ""
        program = safe_extract.inside(macos, name) if name else ""
        if not program or not os.path.isfile(program):
            raise JobError("The macOS app has no program inside.", "invalid_build")
        return program
    if not os.path.isfile(entry):
        raise JobError(f"The build has no {os.path.basename(launch)}.", "invalid_build")
    return entry


def _mark_executables(install_dir: str, program: str, platform: str) -> None:
    if platform == "macos":
        macos = os.path.dirname(program)
        for name in os.listdir(macos):
            path = os.path.join(macos, name)
            if os.path.isfile(path):
                safe_extract.make_executable(path)
    elif platform == "linux":
        safe_extract.make_executable(program)


def parse_selftest(output: str) -> dict | None:
    for line in reversed(str(output or "").splitlines()):
        line = line.strip()
        if line.startswith(SELFTEST_PREFIX):
            try:
                data = json.loads(line[len(SELFTEST_PREFIX):].strip())
            except ValueError:
                return None
            return data if isinstance(data, dict) else None
    return None


def selftest(program: str, cwd: str, runner=subprocess.run) -> dict:
    """``--headless -- --mixar-selftest``: ok only on exit 0 AND a
    ``MIXAR_SELFTEST {"ok": true}`` line."""
    started = time.monotonic()
    kwargs = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} \
        if sys.platform.startswith("win") else {}
    try:
        done = runner([program, "--headless", "--", "--mixar-selftest"], cwd=cwd,
                      capture_output=True, text=True, errors="replace",
                      timeout=SELFTEST_TIMEOUT_S, stdin=subprocess.DEVNULL, **kwargs)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "duration_s": SELFTEST_TIMEOUT_S}
    except OSError as exc:
        return {"ok": False, "error": f"launch_failed ({exc.__class__.__name__})", "duration_s": 0.0}
    report = parse_selftest(done.stdout) or {}
    ok = done.returncode == 0 and bool(report.get("ok"))
    result = {"ok": ok, "exit_code": done.returncode,
              "duration_s": round(time.monotonic() - started, 2), "report": report}
    if not ok:
        tail = [line for line in (done.stdout or "").splitlines() if line.strip()][-1:]
        result["error"] = report.get("error") or (tail[0][:200] if tail else "no self-test line")
    return result


def install_work(root: str, api_base: str, game: dict, platform: str, client_factory=None):
    """Install (or update to) ``game``'s current build for ``platform``."""
    def work(handle):
        from .store_client import StoreClient, StoreError
        build = (game.get("builds") or {}).get(platform)
        if not build:
            raise JobError(f"{game.get('title')} has no approved {platform} build yet.", "no_build")
        if not build.get("launch") or not build.get("sha256"):
            raise JobError("The store's build record has no entry point or checksum.", "invalid_build")
        client = (client_factory or StoreClient)(api_base)
        slug, build_id = game["slug"], build["build_id"]
        folder = os.path.join(root, slug)
        staging = os.path.join(folder, f"{build_id}.staging")
        final = os.path.join(folder, build_id)
        downloads = os.path.join(root, library.DOWNLOADS_DIR)
        archive = os.path.join(downloads, f"{build_id}.zip.part")
        try:
            handle.progress(2.0, "Asking the store for the download", force=True)
            info = client.download_info(game["game_id"], build_id)
            if str(info.get("sha256") or "").lower() != build["sha256"]:
                raise JobError("The download does not match the store's library record.",
                               "sha256_mismatch")
            os.makedirs(downloads, exist_ok=True)
            client.fetch(info["url"], archive, build["sha256"], build["size_bytes"],
                         lambda f: handle.progress(5.0 + 70.0 * f, None), handle.cancel_event)
            handle.progress(76.0, "Unpacking", force=True)
            shutil.rmtree(staging, ignore_errors=True)
            os.makedirs(folder, exist_ok=True)
            safe_extract.extract(archive, staging, handle.cancel_event)
            program = executable_for(staging, build["launch"], platform)
            _mark_executables(staging, program, platform)
            shutil.rmtree(final, ignore_errors=True)
            os.replace(staging, final)
        except StoreError as exc:
            raise JobError(exc.message, exc.code) from exc
        except safe_extract.UnsafeArchive as exc:
            raise JobError(f"The build was refused: {exc}", "unsafe_archive") from exc
        except KeyError as exc:
            raise JobError("The store's download answer is incomplete.", "bad_response") from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            try:
                os.remove(archive)
            except OSError:
                pass
        handle.progress(85.0, "Testing the game", force=True)
        program = executable_for(final, build["launch"], platform)
        check = selftest(program, final)
        index = library.load_index(root)
        index[slug] = {"game_id": game["game_id"], "title": game.get("title") or slug,
                       "build_id": build_id, "version": build["version"], "platform": platform,
                       "launch": build["launch"], "sha256": build["sha256"],
                       "installed_at": time.time(), "selftest": check}
        library.save_index(root, index)
        library.prune(root)  # older builds of this game
        return {"slug": slug, "build_id": build_id, "version": build["version"],
                "platform": platform, "selftest": check}
    return work


def install_by_slug_work(root: str, api_base: str, slug: str, platform: str, client_factory=None):
    """Refresh the listing on the worker, then install ``slug``."""
    def work(handle):
        from .store_client import StoreClient, StoreError
        try:
            data = (client_factory or StoreClient)(api_base).library()
        except StoreError as exc:
            raise JobError(exc.message, exc.code) from exc
        games = library.normalize_listing(data)
        library.set_listing(games)
        game = next((g for g in games if g["slug"] == slug), None)
        if game is None:
            raise JobError("That game is not in your library. Get it on its store page first.",
                           "not_owned")
        return install_work(root, api_base, game, platform, client_factory)(handle)
    return work


def uninstall_work(root: str, slug: str):
    def work(handle):
        index = library.load_index(root)
        if slug not in index:
            raise JobError("That game is not installed.", "not_installed")
        index.pop(slug)
        library.save_index(root, index)
        shutil.rmtree(safe_extract.inside(root, slug), ignore_errors=True)
        return {"slug": slug, "uninstalled": True}
    return work


def launch_installed(root: str, slug: str, popen=subprocess.Popen) -> dict:
    """Start an installed game detached. Callers gate this on a user click."""
    from . import godot_runner
    record = (library.installed() or {}).get(slug)
    if record is None:
        return {"ok": False, "error_code": "not_installed", "error": "That game is not installed."}
    install_dir = os.path.join(root, slug, record["build_id"])
    try:
        program = executable_for(install_dir, record["launch"], record["platform"])
    except (JobError, safe_extract.UnsafeArchive) as exc:
        return {"ok": False, "error_code": "invalid_install", "error": str(exc)}
    if not godot_runner.launch(program, [], popen=popen):
        return {"ok": False, "error_code": "launch_failed", "error": "The game could not be started."}
    return {"ok": True, "slug": slug, "build_id": record["build_id"]}
