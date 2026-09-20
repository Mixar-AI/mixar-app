# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-user enrollment of which asset libraries feed training/search.

With many registered libraries (vendor caches like BlenderKit, plus the
user's own), training every one is slow and pollutes search with assets the
user doesn't consider theirs. Enrollment is an explicit opt-in set —
DEFAULT OFF for every library — persisted per user (not per .blend), keyed
by library NAME (what the asset browser shows).

The training scan (``render_session.build_render_plan``) and the prepare/status
scan (``asset_search_ops._scan_asset_library_metadata``) filter to the enrolled
set, so downstream search / inventory / reuse are auto-scoped: only enrolled
libraries are ever embedded, and de-enrolling one makes its assets show up as
"removed" in the next prepare diff (the incremental flow purges them).
"""

import json
import os

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_FILENAME = "asset_train_libraries.json"
_cache: set | None = None  # names, or None when not yet loaded
_SYNCING = False           # suppress write-back while the UI list rebuilds


def _config_path() -> str:
    try:
        base = bpy.utils.user_resource("CONFIG", path="mixar", create=True)
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".mixar")
        os.makedirs(base, exist_ok=True)
    return os.path.join(base, _FILENAME)


def enrolled_names() -> set:
    """The set of enrolled library names (cached; empty when none/absent)."""
    global _cache
    if _cache is not None:
        return _cache
    names: set = set()
    path = _config_path()
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            names = {str(n) for n in data.get("enrolled", []) if n}
    except Exception:
        logger.opt(exception=True).warning("[Enrollment] Could not read %s", path)
    _cache = names
    return names


def is_enrolled(name: str) -> bool:
    return name in enrolled_names()


def set_enrolled(name: str, enabled: bool) -> None:
    """Add/remove a library from the enrolled set and persist atomically."""
    if _SYNCING:
        return
    names = set(enrolled_names())
    if enabled:
        names.add(name)
    else:
        names.discard(name)
    _write(names)


def _write(names: set) -> None:
    global _cache
    path = _config_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"enrolled": sorted(names)}, fh, indent=2)
        os.replace(tmp, path)
        _cache = set(names)
    except Exception:
        logger.opt(exception=True).warning("[Enrollment] Could not write %s", path)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def invalidate_cache() -> None:
    global _cache
    _cache = None


def enrolled_libraries(context):
    """Registered asset libraries that are enrolled for training/search."""
    names = enrolled_names()
    return [
        lib for lib in context.preferences.filepaths.asset_libraries
        if lib.name in names
    ]
