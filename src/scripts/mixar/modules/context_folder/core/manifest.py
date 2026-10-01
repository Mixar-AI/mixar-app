# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The path-free ``folder_context`` a chat turn carries.

Built on the main thread at Send from the scene's attached folders: per
folder its opaque id, a display name the agent uses as a path prefix, counts
by kind, a bounded listing of folder-relative paths, and short excerpts of
the notes a person leaves to explain a folder (README, brief, notes). No
absolute path, user name or volume name is ever part of it.
"""

from pathlib import PurePosixPath

from ..constants import (
    KIND_AUDIO,
    KIND_DOCUMENT,
    KIND_IMAGE,
    KIND_MODEL,
    KIND_OTHER,
    KIND_TEXT,
    KIND_VIDEO,
    MAX_FOLDERS,
    MAX_MANIFEST_FILES,
    MAX_MANIFEST_NOTES,
    NOTE_EXCERPT_CHARS,
    NOTE_MAX_BYTES,
    NOTE_STEMS,
    PROTOCOL_VERSION,
)
from .errors import ContextFolderError
from .indexer import index_folder
from .paths import existing_file
from .registry import get_registry

# Which files earn a manifest line first when a folder is larger than the
# listing: the material a brief is made of before the rest.
_KIND_RANK = {KIND_TEXT: 0, KIND_IMAGE: 1, KIND_MODEL: 2, KIND_DOCUMENT: 3,
              KIND_VIDEO: 4, KIND_AUDIO: 5, KIND_OTHER: 6}


def attached_folders(scene) -> list:
    """``[(folder_id, name)]`` attached to this scene's chat, in order."""
    items = getattr(scene, "mixie_context_folders", None) or ()
    return [(item.folder_id, item.name) for item in items if getattr(item, "folder_id", "")][:MAX_FOLDERS]


def unique_labels(names) -> list:
    """Display names made unique ("refs", "refs (2)"): each is the prefix the
    agent writes before a folder-relative path."""
    used, labels = set(), []
    for name in names:
        base = (str(name or "").replace("/", "_").strip() or "folder")[:96]
        label, count = base, 1
        while label in used:
            count += 1
            label = f"{base} ({count})"
        used.add(label)
        labels.append(label)
    return labels


def _note_rank(entry: dict):
    path = PurePosixPath(entry["path"])
    stem = path.stem.lower()
    named = next((i for i, note in enumerate(NOTE_STEMS) if stem.startswith(note)), None)
    return (named is None, len(path.parts), named or 0, entry["path"])


def _notes(root, files: list) -> list:
    candidates = [entry for entry in files if entry["kind"] == KIND_TEXT
                  and entry["size"] <= NOTE_MAX_BYTES
                  and PurePosixPath(entry["path"]).suffix.lower() in (".md", ".markdown", ".txt", ".rst")]
    candidates = [entry for entry in sorted(candidates, key=_note_rank)
                  if _note_rank(entry)[0] is False or len(PurePosixPath(entry["path"]).parts) == 1]
    notes = []
    for entry in candidates[:MAX_MANIFEST_NOTES]:
        try:
            with existing_file(root, entry["path"]).open("r", encoding="utf-8", errors="replace") as handle:
                excerpt = handle.read(NOTE_EXCERPT_CHARS + 1)
        except (OSError, ContextFolderError):
            continue
        truncated = len(excerpt) > NOTE_EXCERPT_CHARS
        notes.append({"path": entry["path"], "excerpt": excerpt[:NOTE_EXCERPT_CHARS].strip(),
                      "truncated": truncated})
    return notes


def _listing(files: list) -> list:
    ranked = sorted(files, key=lambda e: (e["path"].count("/"), _KIND_RANK[e["kind"]], e["path"]))
    chosen = sorted(ranked[:MAX_MANIFEST_FILES], key=lambda e: e["path"])
    return [{"path": e["path"], "kind": e["kind"], "size": e["size"]} for e in chosen]


def describe_folder(folder_id: str, label: str) -> dict:
    """One folder's manifest entry; ``available`` False when this machine
    cannot reach it (deleted, unmounted, project opened elsewhere)."""
    try:
        root = get_registry().resolve(folder_id)
        index = index_folder(root)
    except (ContextFolderError, OSError):
        return {"folder_id": folder_id, "name": label, "available": False}
    return {
        "folder_id": folder_id,
        "name": label,
        "available": True,
        "file_count": len(index.files),
        "total_bytes": index.total_bytes,
        "truncated": index.truncated,
        "kinds": index.counts(),
        "files": _listing(index.files),
        "notes": _notes(root, index.files),
    }


def build_folder_context(scene) -> dict:
    """The turn's ``folder_context``. Always a complete snapshot: an empty
    ``folders`` list tells the backend the user removed every folder."""
    entries = attached_folders(scene)
    labels = unique_labels(name for _, name in entries)
    return {
        "version": PROTOCOL_VERSION,
        "folders": [describe_folder(folder_id, label) for (folder_id, _), label in zip(entries, labels)],
    }
