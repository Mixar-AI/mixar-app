# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Machine-local mapping from opaque ids to absolute roots and files.

The ``.mixar`` file and every wire payload hold only the id; the root lives
here, in the per-user config directory, so a project opened on another
machine shows the folder as unavailable instead of resolving a stale path.
Single attached files are persisted the same way (``files``), and a scene's
current selection of them is published in memory as a ``FileSet`` under its
own synthetic folder id, which ``resolve`` serves like a root.
Read from RPC worker threads, written from operators: one lock guards all.
"""

import json
import os
import threading
import uuid
from pathlib import Path

from mixar.modules.common.i18n import n_

from .errors import ContextFolderError
from .file_set import FileSet

_lock = threading.Lock()
_registry = None

_WRITE_FAILED = n_("Could not save the folder attachment. Check access to your Mixar settings and try again.")


def _default_path() -> Path:
    try:
        import bpy

        configured = bpy.utils.user_resource("CONFIG", path="mixar", create=True)
        if configured:
            return Path(configured) / "context_folders.json"
    except Exception:
        pass
    return Path.home() / ".mixar" / "context_folders.json"


def _entries(payload, key: str, field: str) -> dict:
    section = payload.get(key) if isinstance(payload, dict) else None
    return {
        str(entry_id): str(value[field]) for entry_id, value in (section or {}).items()
        if isinstance(value, dict) and value.get(field)
    }


class FolderRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._folders = None
        self._files = None
        self._sets = {}  # set_id -> ((name, file_id), ...), never persisted

    def _load(self) -> dict:
        """Folder id -> root. Loads the file once; unknown keys are ignored so
        an older build's file (folders only) and a newer one both load."""
        if self._folders is None:
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                payload = {}
            self._folders = _entries(payload, "folders", "root")
            self._files = _entries(payload, "files", "file")
        return self._folders

    def _load_files(self) -> dict:
        self._load()
        return self._files

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A unique sibling, never tempfile.mkstemp (see CLAUDE.md, config
        # persistence): os.replace makes the swap atomic on every platform.
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}")
        payload = {
            "folders": {key: {"root": root} for key, root in self._load().items()},
            "files": {key: {"file": file} for key, file in self._load_files().items()},
        }
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

    def _register(self, table: dict, resolved: str) -> str:
        """Under the lock: the existing id for ``resolved`` or a new, saved one."""
        for key, known in table.items():
            if known == resolved:
                return key
        key = str(uuid.uuid4())
        table[key] = resolved
        try:
            self._save()
        except OSError as exc:
            del table[key]
            raise ContextFolderError("registry_write_failed", _WRITE_FAILED) from exc
        return key

    def register(self, root) -> str:
        """The id for ``root``: the existing one when it is already known."""
        resolved = str(Path(root).resolve(strict=True))
        with _lock:
            return self._register(self._load(), resolved)

    def register_file(self, path) -> str:
        """The id for one regular file: the existing one for the same resolved path."""
        resolved = Path(path).resolve(strict=True)
        if not resolved.is_file():
            raise ContextFolderError("not_a_file", n_("Choose a file to attach"))
        with _lock:
            return self._register(self._load_files(), str(resolved))

    def resolve_file(self, file_id: str) -> Path:
        with _lock:
            file = self._load_files().get(str(file_id or ""))
        if not file:
            raise ContextFolderError("file_unknown", "This file is not attached on this computer")
        path = Path(file)
        if not path.is_file():
            raise ContextFolderError("file_unavailable", "The attached file is no longer available")
        return path.resolve(strict=True)

    def publish_file_set(self, set_id: str, members) -> None:
        """Replace the membership of a scene's set: ``[(name, file_id)]``."""
        with _lock:
            self._sets[str(set_id)] = tuple((str(name), str(file_id)) for name, file_id in members)

    def resolve(self, folder_id: str):
        """A directory ``Path`` for a folder id, or a ``FileSet`` for a published set id."""
        folder_id = str(folder_id or "")
        with _lock:
            members = self._sets.get(folder_id)
            if members is not None:
                files = self._load_files()
                return FileSet(folder_id, tuple((name, files[file_id]) for name, file_id in members
                                                if file_id in files))
            root = self._load().get(folder_id)
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
