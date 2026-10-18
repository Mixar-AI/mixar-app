# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixar Library state (contract v1.1): the owned-games listing and the
local install index.

Installs live under ``<user data>/mixar/library/<slug>/<build_id>/`` (never
in the .blend). ``installed.json`` in the root indexes them. Workers own the
disk: they load the index, refresh the listing from ``/me/library`` and
prune leftovers; the main thread reads only the in-memory snapshot below.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time

INDEX_FILE = "installed.json"
DOWNLOADS_DIR = ".downloads"
LIBRARY_SUBDIR = "mixar/library"
LISTING_STALE_S = 60.0

_lock = threading.Lock()
_state = {"index": None, "listing": None, "listed_at": 0.0, "error": None}


def host_platform(platform: str = "") -> str:
    platform = platform or sys.platform
    if platform == "darwin":
        return "macos"
    if platform.startswith("win"):
        return "windows"
    return "linux"


def library_root() -> str:
    """``<user data>/mixar/library`` (created). Main thread only."""
    import bpy
    root = bpy.utils.user_resource('DATAFILES', path=LIBRARY_SUBDIR, create=True)
    if not isinstance(root, str) or not root:
        raise OSError("user data directory unavailable")
    return root


# --- the store listing ------------------------------------------------------------

def _build_record(raw: dict, platform: str = "") -> dict | None:
    if not isinstance(raw, dict):
        return None
    record = {"build_id": str(raw.get("build_id") or raw.get("id") or ""),
              "platform": str(raw.get("platform") or platform or ""),
              "version": str(raw.get("version") or ""),
              "sha256": str(raw.get("sha256") or "").lower(),
              "size_bytes": int(raw.get("size_bytes") or 0),
              "launch": str(raw.get("launch") or "")}
    return record if record["build_id"] and record["platform"] else None


def normalize_listing(data) -> list[dict]:
    """``/me/library`` data → ``[{game_id, slug, title, builds: {platform: build}}]``.
    Tolerates ``{"items"|"games": [...]}`` or a bare list, game fields inline
    or under ``game``, and builds as a list or a ``{platform: build}`` map."""
    if isinstance(data, dict):
        data = data.get("items") or data.get("games") or data.get("library") or []
    games = []
    for item in data if isinstance(data, list) else ():
        if not isinstance(item, dict):
            continue
        game = item.get("game") if isinstance(item.get("game"), dict) else item
        raw_builds = item.get("builds") or game.get("builds") or []
        builds = {}
        if isinstance(raw_builds, dict):
            pairs = raw_builds.items()
        else:
            pairs = ((None, b) for b in raw_builds)
        for platform, raw in pairs:
            record = _build_record(raw, platform or "")
            if record is not None:
                builds[record["platform"]] = record
        game_id = str(game.get("game_id") or game.get("id") or "")
        slug = str(game.get("slug") or "")
        if game_id and slug:
            games.append({"game_id": game_id, "slug": slug,
                          "title": str(game.get("title") or slug), "builds": builds})
    return games


def set_listing(games: list[dict] | None, error: str | None = None) -> None:
    with _lock:
        if games is not None:
            _state["listing"] = list(games)
            _state["listed_at"] = time.monotonic()
        _state["error"] = error


def listing() -> tuple[list[dict] | None, float, str | None]:
    """``(games or None before the first refresh, age_s, last_error)``."""
    with _lock:
        games = _state["listing"]
        age = time.monotonic() - _state["listed_at"] if games is not None else float("inf")
        return (list(games) if games is not None else None), age, _state["error"]


def find_game(slug: str) -> dict | None:
    games, _age, _error = listing()
    return next((g for g in games or () if g["slug"] == slug), None)


# --- the install index (workers write; snapshot read anywhere) ---------------------

def load_index(root: str) -> dict:
    try:
        with open(os.path.join(root, INDEX_FILE), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    index = data if isinstance(data, dict) else {}
    with _lock:
        _state["index"] = dict(index)
    return index


def save_index(root: str, index: dict) -> None:
    path = os.path.join(root, INDEX_FILE)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=2, sort_keys=True)
    os.replace(temp, path)
    with _lock:
        _state["index"] = dict(index)


def installed() -> dict | None:
    """The index snapshot, or None before a worker loaded it."""
    with _lock:
        return dict(_state["index"]) if _state["index"] is not None else None


def prune(root: str) -> list[str]:
    """Remove partial downloads, staging folders and builds the index no
    longer names. Worker threads only. Returns what was removed."""
    index = load_index(root)
    removed = []
    downloads = os.path.join(root, DOWNLOADS_DIR)
    if os.path.isdir(downloads):
        shutil.rmtree(downloads, ignore_errors=True)
        removed.append(DOWNLOADS_DIR)
    for slug in os.listdir(root) if os.path.isdir(root) else ():
        folder = os.path.join(root, slug)
        if slug.startswith(".") or not os.path.isdir(folder):
            continue
        keep = (index.get(slug) or {}).get("build_id")
        for build in os.listdir(folder):
            if build != keep:
                shutil.rmtree(os.path.join(folder, build), ignore_errors=True)
                removed.append(f"{slug}/{build}")
        if not keep:
            shutil.rmtree(folder, ignore_errors=True)
    return removed


def reset_for_tests() -> None:
    with _lock:
        _state.update(index=None, listing=None, listed_at=0.0, error=None)
