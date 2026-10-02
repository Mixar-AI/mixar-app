# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Machine-local mapping from opaque folder ids to absolute roots.

The ``.mixar`` file and every wire payload hold only the id; the root lives
here, in the per-user config directory, so a project opened on another
machine shows the folder as unavailable instead of resolving a stale path.
Read from RPC worker threads, written from operators: one lock guards both.
"""

import json
import os
import threading
import uuid
from pathlib import Path

from mixar.modules.common.i18n import n_

from .errors import ContextFolderError

_lock = threading.Lock()
_registry = None


def _default_path() -> Path:
    try:
        import bpy

        configured = bpy.utils.user_resource("CONFIG", path="mixar", create=True)
        if configured:
            return Path(configured) / "context_folders.json"
    except Exception:
        pass
    return Path.home() / ".mixar" / "context_folders.json"


class FolderRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._folders = None

    def _load(self) -> dict:
        if self._folders is None:
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                folders = payload.get("folders") if isinstance(payload, dict) else None
                self._folders = {
                    str(key): str(value["root"]) for key, value in (folders or {}).items()
                    if isinstance(value, dict) and value.get("root")
                }
            except (OSError, ValueError):
                self._folders = {}
        return self._folders

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A unique sibling, never tempfile.mkstemp (see CLAUDE.md, config
        # persistence): os.replace makes the swap atomic on every platform.
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}")
        payload = {"folders": {key: {"root": root} for key, root in self._load().items()}}
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(temporary, self.path)
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def register(self, root) -> str:
        """The id for ``root``: the existing one when it is already known."""
        resolved = str(Path(root).resolve(strict=True))
        with _lock:
            folders = self._load()
            for key, known in folders.items():
                if known == resolved:
                    return key
            key = str(uuid.uuid4())
            folders[key] = resolved
            try:
                self._save()
            except OSError as exc:
                del folders[key]
                raise ContextFolderError(
                    "registry_write_failed",
                    n_("Could not save the folder attachment. Check access to your Mixar settings and try again."),
                ) from exc
            return key

    def resolve(self, folder_id: str) -> Path:
        with _lock:
            root = self._load().get(str(folder_id or ""))
        if not root:
            raise ContextFolderError("folder_unknown", "This folder is not attached on this computer")
        path = Path(root)
        if not path.is_dir():
            raise ContextFolderError("folder_unavailable", "The attached folder is no longer available")
        return path.resolve(strict=True)

    def available(self, folder_id: str) -> bool:
        try:
            self.resolve(folder_id)
            return True
        except ContextFolderError:
            return False


def get_registry() -> FolderRegistry:
    global _registry
    with _lock:
        if _registry is None:
            _registry = FolderRegistry(_default_path())
        return _registry


def set_registry_for_tests(registry) -> None:
    global _registry
    with _lock:
        _registry = registry
