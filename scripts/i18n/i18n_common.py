# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared paths and the message model for the ``scripts/i18n`` tools.

The runtime package (``src/scripts/mixar/modules/common/i18n``) is loaded as
a standalone package named ``mixar_i18n`` so the tools never import
``mixar.modules`` (whose ``__init__`` imports ``bpy``).
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
I18N_PACKAGE_DIR = SRC_DIR / "scripts" / "mixar" / "modules" / "common" / "i18n"

# Catalogs that hold only the messages whose text differs from the English
# source, in template order. ``en_GB`` is the source respelled
# (``derive_catalogs.py``): a full catalog would be ~9,000 untranslated or
# identical entries around a few hundred real ones, and a missing entry falls
# back to the identical source anyway.
SPARSE_CATALOGS = frozenset({"en_GB"})


def load_runtime_package():
    """Import the runtime i18n package as ``mixar_i18n`` (no bpy needed)."""
    if "mixar_i18n" not in sys.modules:
        pkg = types.ModuleType("mixar_i18n")
        pkg.__path__ = [str(I18N_PACKAGE_DIR)]
        sys.modules["mixar_i18n"] = pkg
    constants = importlib.import_module("mixar_i18n.constants")
    po = importlib.import_module("mixar_i18n.core.po")
    return constants, po


def default_upstream_dir() -> Path | None:
    """The pinned Blender checkout overridden files are diffed against."""
    for cand in (os.environ.get("MIXAR_UPSTREAM_DIR"), REPO_ROOT / "upstream"):
        if cand and (Path(cand) / "source").is_dir():
            return Path(cand)
    return None


@dataclass
class Message:
    msgid: str
    msgctxt: str | None = None
    kinds: set[str] = field(default_factory=set)
    refs: list[str] = field(default_factory=list)

    @property
    def key(self):
        return (self.msgctxt, self.msgid)


class MessageSet:
    """Ordered, de-duplicated messages; first occurrence decides position."""

    def __init__(self):
        self._items: dict[tuple, Message] = {}

    def add(self, msgid: str, kind: str, ref: str, msgctxt: str | None = None) -> None:
        if not is_translatable(msgid):
            return
        if msgctxt in ("", "*"):
            msgctxt = None
        key = (msgctxt, msgid)
        msg = self._items.get(key)
        if msg is None:
            msg = self._items[key] = Message(msgid=msgid, msgctxt=msgctxt)
        msg.kinds.add(kind)
        if ref not in msg.refs:
            msg.refs.append(ref)

    def keys(self):
        return set(self._items)

    def discard(self, key) -> None:
        self._items.pop(key, None)

    def merge(self, other: "MessageSet") -> None:
        for msg in other:
            for ref in msg.refs:
                for kind in sorted(msg.kinds):
                    self.add(msg.msgid, kind, ref, msg.msgctxt)

    def __iter__(self):
        return iter(self._items.values())

    def __len__(self):
        return len(self._items)


def is_translatable(text) -> bool:
    """Worth a catalog entry: a real string with at least one letter."""
    if not isinstance(text, str) or not text.strip():
        return False
    return any(ch.isalpha() for ch in text)
