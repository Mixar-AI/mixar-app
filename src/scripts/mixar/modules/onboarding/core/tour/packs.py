# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the on-disk language pack cache.

Layout (``cache_root()``: ``<user CONFIG>/mixar/tour/<pack_version>/``, or
``MIXAR_TOUR_PACK_DIR`` for QA)::

    manifest.json                  the CDN manifest as last fetched
    <code>/timing.json             the language's beat table
    <code>/part-<k>.mp4            the video parts
    <code>/<file>.ok               sidecar: sha256 the file was verified against

A pack is *installed* only when the manifest entry, ``timing.json`` and
every part are present with matching sidecars and the timing table's
``script_hash`` is the bundled script's. Anything less plays English. Files
are written by ``pack_fetch`` (download → sha256 verified → sidecar), so
this module only reads; it imports ``bpy`` solely to find the config dir.
"""

import json
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from mixar.config.logging_config import get_logger

from . import config

logger = get_logger(__name__)


@dataclass(frozen=True)
class PackInfo:
    code: str
    parts: Tuple[Tuple[int, int, str], ...]   # (start_ms, end_ms, path)
    timing: dict
    duration_ms: int
    root: str = ""
    shas: Tuple[str, ...] = ()                # sha256 per part, by k

    def ready(self, k: int) -> bool:
        """Part ``k`` verified on disk right now (it may be downloading)."""
        if k < 0 or k >= len(self.parts):
            return False
        if not self.shas:
            return True
        return part_ready(self.root, self.code, k, self.shas[k])


def cache_root(create: bool = False) -> str:
    override = os.environ.get(config.ENV_PACK_DIR)
    if override:
        return os.path.expanduser(override)
    try:
        import bpy
        base = bpy.utils.user_resource('CONFIG', path=config.PACK_CACHE_SUBDIR, create=create)
    except Exception as exc:  # noqa: BLE001
        logger.debug("tour packs: no user config dir: %s", exc)
        return ""
    if not isinstance(base, str) or not base:
        return ""
    return os.path.join(base, str(config.TOUR_PACK_VERSION))


def manifest_path(root: str) -> str:
    return os.path.join(root, "manifest.json")


def read_manifest(root: str) -> Optional[dict]:
    try:
        with open(manifest_path(root), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def manifest_entry(manifest: Optional[dict], code: str) -> Optional[dict]:
    if not manifest or manifest.get("pack_version") != config.TOUR_PACK_VERSION:
        return None
    entry = (manifest.get("languages") or {}).get(code)
    return entry if isinstance(entry, dict) else None


def sidecar_path(path: str) -> str:
    return path + ".ok"


def is_verified(path: str, sha256: str) -> bool:
    """File present and its sidecar records the expected digest.

    Under the QA override (``MIXAR_TOUR_PACK_DIR``, a folder copied straight
    from the pack build) there are no sidecars, so the file is hashed."""
    if not sha256 or not os.path.isfile(path):
        return False
    try:
        with open(sidecar_path(path), "r", encoding="utf-8") as fh:
            return fh.read().strip().lower() == sha256.lower()
    except OSError:
        if not os.environ.get(config.ENV_PACK_DIR):
            return False
    return _sha256_file(path) == sha256.lower()


def _sha256_file(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def mark_verified(path: str, sha256: str) -> None:
    with open(sidecar_path(path), "w", encoding="utf-8") as fh:
        fh.write(sha256.lower())


def part_path(root: str, code: str, k: int) -> str:
    return os.path.join(root, code, f"part-{k}.mp4")


def timing_path(root: str, code: str) -> str:
    return os.path.join(root, code, "timing.json")


def missing_files(root: str, entry: dict, code: str) -> List[Tuple[str, str, str]]:
    """``(url, path, sha256)`` of every file the entry lists that is not
    verified on disk, timing first then parts in order."""
    out = []
    timing = entry.get("timing") or {}
    if not is_verified(timing_path(root, code), timing.get("sha256", "")):
        out.append((timing.get("url", ""), timing_path(root, code), timing.get("sha256", "")))
    for p in sorted(entry.get("parts") or [], key=lambda p: int(p.get("k", 0))):
        path = part_path(root, code, int(p.get("k", 0)))
        if not is_verified(path, p.get("sha256", "")):
            out.append((p.get("url", ""), path, p.get("sha256", "")))
    return out


def installed(code: str, root: Optional[str] = None,
              expected_script_hash: Optional[str] = None) -> Optional[PackInfo]:
    """The complete, verified pack for ``code``, or None."""
    return _load(code, root, expected_script_hash, need_parts=None)


def partial(code: str, root: Optional[str] = None,
            expected_script_hash: Optional[str] = None,
            first_parts: int = 1) -> Optional[PackInfo]:
    """The pack for ``code`` once its timing table and the first
    ``first_parts`` parts are verified; the rest may still be downloading
    (``part_ready`` checks them live). None otherwise."""
    return _load(code, root, expected_script_hash, need_parts=first_parts)


def part_ready(root: str, code: str, k: int, sha256: str) -> bool:
    return is_verified(part_path(root, code, k), sha256)


def _load(code, root, expected_script_hash, need_parts) -> Optional[PackInfo]:
    root = cache_root() if root is None else root
    if not root or not code or code == "en":
        return None
    entry = manifest_entry(read_manifest(root), code)
    if entry is None:
        return None
    missing = missing_files(root, entry, code)
    if need_parts is None:
        if missing:
            return None
    else:
        need = {timing_path(root, code)} | {part_path(root, code, k) for k in range(need_parts)}
        if any(path in need for _u, path, _s in missing):
            return None
    try:
        with open(timing_path(root, code), "r", encoding="utf-8") as fh:
            timing = json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("tour packs: %s timing unreadable: %s", code, exc)
        return None
    if expected_script_hash is None:
        from . import timing as timing_mod
        from .beats import MIXAR_INTRO
        expected_script_hash = timing_mod.script_hash(MIXAR_INTRO)
    if timing.get("script_hash") != expected_script_hash:
        logger.info("tour packs: %s was built for another script; ignoring", code)
        return None
    parts = tuple(sorted(
        (int(p["start_ms"]), int(p["end_ms"]), part_path(root, code, int(p["k"])))
        for p in entry.get("parts") or []))
    if not parts:
        return None
    shas = tuple(p.get("sha256", "") for p in sorted(entry.get("parts") or [], key=lambda p: int(p["k"])))
    return PackInfo(code, parts, timing, int(entry.get("duration_ms") or parts[-1][1]),
                    root, shas)
