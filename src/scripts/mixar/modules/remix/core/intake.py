# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bring a remix source onto this machine — worker threads only, no ``bpy``.

``claim_work`` takes a waiting remix from the store, downloads its source
into a fresh folder under ``<config>/mixar/remixes`` and returns what the
main thread needs to open it (``opening.open_remix``).
"""

from __future__ import annotations

import os
import re
import uuid
import zipfile

from mixar.modules.game_studio.core import safe_extract
from mixar.modules.game_studio.core.jobs import JobError
from mixar.modules.game_studio.core.store_client import StoreError

from ..constants import FORMAT_GLB, FORMAT_MIXAR, FORMAT_PACKAGE, REMIXES_SUBDIR
from . import lineage
from .client import RemixClient

EXTENSIONS = {FORMAT_MIXAR: ".mixar", FORMAT_GLB: ".glb", FORMAT_PACKAGE: ".zip"}
PACKAGE_SCENE, PACKAGE_SPEC = "scene.glb", "game_spec.json"


def remix_root() -> str:
    import bpy
    return os.path.join(bpy.utils.user_resource('CONFIG'), *REMIXES_SUBDIR.split("/"))


def safe_stem(title: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "", str(title or "")).strip(" .")[:60]
    return stem or "remix"


def _find(folder: str, name: str) -> str:
    for base, _dirs, files in os.walk(folder):
        if name in files:
            return os.path.join(base, name)
    return ""


def fetch_package(client, package: dict, root: str, handle=None) -> dict:
    """Download ``package["source"]`` and return the opening plan:
    ``{format, path, project_path, origin, starter_prompts, spec_path}``."""
    origin = lineage.clean_origin(package.get("origin"))
    source = package.get("source") if isinstance(package.get("source"), dict) else {}
    fmt = str(source.get("format") or "")
    if origin is None or fmt not in EXTENSIONS or not source.get("url"):
        raise JobError("The store sent a remix this version of Mixar can't open.", "bad_response")
    folder = os.path.join(root, f"{safe_stem(origin['slug'] or origin['title'])}-{uuid.uuid4().hex[:8]}")
    os.makedirs(folder, exist_ok=True)
    stem = safe_stem(lineage.remix_title(origin["title"]))
    download = os.path.join(folder, "source" + EXTENSIONS[fmt])

    def report(fraction):
        if handle is not None:
            handle.progress(5.0 + 85.0 * fraction, "Downloading the project")

    try:
        client.fetch_source(str(source["url"]), download, int(source.get("size_bytes") or 0),
                            str(source.get("sha256") or ""), report,
                            handle.cancel_event if handle is not None else None)
    except StoreError as exc:
        raise JobError(exc.message, exc.code) from exc
    plan = {"format": fmt, "path": download, "origin": origin, "spec_path": "",
            "project_path": os.path.join(folder, stem + ".mixar"),
            "starter_prompts": [str(p) for p in package.get("starter_prompts") or ()][:5]}
    if fmt == FORMAT_PACKAGE:
        unpacked = os.path.join(folder, "package")
        try:
            safe_extract.extract(download, unpacked)
        except (safe_extract.UnsafeArchive, zipfile.BadZipFile, OSError) as exc:
            raise JobError("The remix package could not be unpacked safely.", "unsafe_archive") from exc
        scene = _find(unpacked, PACKAGE_SCENE)
        if not scene:
            raise JobError("The remix package has no scene.glb.", "bad_package")
        plan.update(path=scene, spec_path=_find(unpacked, PACKAGE_SPEC))
    return plan


def claim_work(root: str, api_base: str, intent_id: str, client_factory=None):
    def work(handle):
        client = (client_factory or RemixClient)(api_base)
        handle.progress(2.0, "Getting the remix", force=True)
        try:
            package = client.claim(intent_id)
        except StoreError as exc:
            raise JobError(exc.message, exc.code) from exc
        plan = fetch_package(client, package, root, handle)
        handle.progress(95.0, "Opening", force=True)
        return plan
    return work


def source_work(root: str, api_base: str, kind: str, ref: str, client_factory=None):
    """Remix by reference (no web hand-off): the agent or a link names it."""
    def work(handle):
        client = (client_factory or RemixClient)(api_base)
        handle.progress(2.0, "Getting the remix", force=True)
        try:
            package = client.source(kind, ref)
        except StoreError as exc:
            raise JobError(exc.message, exc.code) from exc
        plan = fetch_package(client, package, root, handle)
        handle.progress(95.0, "Opening", force=True)
        return plan
    return work
