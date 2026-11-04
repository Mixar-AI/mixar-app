# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where a game project lives, for the Connect engine sheet (pure of bpy).

- ``default_location()``: the folder new games go in — the one the user
  last chose (``engine_projects_dir`` in the per-user config), else
  ``~/Documents/Mixar Games``.
- ``check_new(engine, location, name)``: may a NEW project of ``engine`` be
  made at ``<location>/<name>``? A missing or empty folder is free; a folder
  that already holds this engine's project is the same game (Connect opens
  it again); anything else — another engine's project, or any other files —
  is taken, so a Godot game and an Unreal game of the same name can never be
  written into one folder.
- ``check_existing(engine, folder)``: does ``folder`` hold a project of
  ``engine``?

Paths are shown on this machine only; nothing here is sent anywhere.
"""

from __future__ import annotations

import glob
import os

from mixar.modules.common.i18n import n_

CONFIG_KEY = "engine_projects_dir"
GAMES_FOLDER = "Mixar Games"
NAME_MAX = 60

# What marks a folder as each engine's project.
PROJECT_FILE = {"godot": "project.godot", "unreal": "*.uproject"}
ENGINE_LABEL = {"godot": "Godot", "unreal": "Unreal"}

# Outcomes of a check (``Check.status``).
# EMPTY: nothing typed yet (the sheet shows its hint quietly, not as an error).
FREE, SAME, TAKEN, INVALID, EMPTY = "free", "same", "taken", "invalid", "empty"


class Check:
    """A check's outcome: ``status``, the project ``folder`` it names and a
    ``message`` for the sheet — a translatable template (marked ``n_``) whose
    named placeholders are ``args``; ``text()`` fills it untranslated, the
    sheet with ``iface_(message).format(**args)``."""

    __slots__ = ("status", "folder", "message", "args")

    def __init__(self, status: str, folder: str = "", message: str = "", **args):
        self.status, self.folder, self.message, self.args = status, folder, message, args

    @property
    def ok(self) -> bool:
        return self.status in (FREE, SAME)

    def text(self) -> str:
        return self.message.format(**self.args) if self.message else ""

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Check({self.status!r}, {self.folder!r}, {self.text()!r})"


def safe_name(name: str) -> str:
    """A folder name made of ``name``'s letters, digits, spaces, _ and -."""
    keep = "".join(c if c.isalnum() or c in " _-" else " " for c in str(name or ""))
    return " ".join(keep.split())[:NAME_MAX]


def default_location() -> str:
    try:
        from mixar.config.config import get_config
        chosen = get_config().get(CONFIG_KEY, "")
        chosen = chosen.strip() if isinstance(chosen, str) else ""
    except Exception:  # noqa: BLE001 - no config (tests, early startup)
        chosen = ""
    if chosen and os.path.isdir(chosen):
        return chosen
    return os.path.join(os.path.expanduser("~"), "Documents", GAMES_FOLDER)


def remember_location(location: str) -> None:
    """The next new game starts in ``location`` (best effort)."""
    try:
        from mixar.config.config import add_config
        add_config(CONFIG_KEY, location)
    except Exception:  # noqa: BLE001 - the connect itself already started
        pass


def clean(path: str) -> str:
    """``path`` with ``~`` expanded and no trailing separator."""
    path = os.path.expanduser(str(path or "").strip().strip('"'))
    return os.path.normpath(path) if path else ""


def holds(folder: str, engine: str) -> bool:
    """True when ``folder`` holds a project of ``engine``."""
    pattern = PROJECT_FILE.get(engine)
    return bool(pattern and folder and glob.glob(os.path.join(glob.escape(folder), pattern)))


def _other_engine(folder: str, engine: str) -> str:
    return next((e for e in PROJECT_FILE if e != engine and holds(folder, e)), "")


def _empty(folder: str) -> bool:
    try:
        return not any(True for _ in os.scandir(folder))
    except OSError:
        return False


def check_new(engine: str, location: str, name: str) -> Check:
    label = ENGINE_LABEL.get(engine, engine)
    location, folder_name = clean(location), safe_name(name)
    if not str(name or "").strip():
        return Check(EMPTY, "", n_("Give the project a name."))
    if not folder_name:
        return Check(INVALID, "", n_("Use letters or digits in the name."))
    if not location:
        return Check(EMPTY, "", n_("Choose where the project goes."))
    if not os.path.isabs(location):
        return Check(INVALID, "", n_("The location must be a full folder path."))
    if os.path.exists(location) and not os.path.isdir(location):
        return Check(INVALID, "", n_("The location is a file, not a folder."))
    folder = os.path.join(location, folder_name)
    if not os.path.exists(folder):
        return Check(FREE, folder)
    if not os.path.isdir(folder):
        return Check(TAKEN, folder, n_("A file named “{name}” is already there. Pick another name."),
                     name=folder_name)
    other = _other_engine(folder, engine)
    if holds(folder, engine) and not other:
        return Check(SAME, folder, n_("This {engine} project already exists. Connect opens it."),
                     engine=label)
    if other:
        return Check(TAKEN, folder, n_("“{name}” already holds a {engine} project. "
                                       "Pick another name or location."),
                     name=folder_name, engine=ENGINE_LABEL[other])
    if not _empty(folder):
        return Check(TAKEN, folder, n_("A folder named “{name}” is already there and is not "
                                       "empty. Pick another name or location."), name=folder_name)
    return Check(FREE, folder)


def check_existing(engine: str, folder: str) -> Check:
    label = ENGINE_LABEL.get(engine, engine)
    folder = clean(folder)
    if not folder:
        return Check(EMPTY, "", n_("Choose the folder that holds your {engine} project."), engine=label)
    if not os.path.isdir(folder):
        return Check(INVALID, folder, n_("That folder does not exist."))
    if not holds(folder, engine):
        marker = PROJECT_FILE[engine].replace("*", "a ")
        return Check(INVALID, folder, n_("That folder is not a {engine} project (it has no {marker})."),
                     engine=label, marker=marker)
    other = _other_engine(folder, engine)
    if other:
        return Check(SAME, folder, n_("This folder also holds a {other} project; Mixar uses its {engine} "
                                      "project."), other=ENGINE_LABEL[other], engine=label)
    return Check(SAME, folder)


def unique_name(engine: str, location: str, name: str) -> str:
    """``name``, or ``name 2``, ``name 3``… — the first that ``check_new``
    accepts at ``location`` (the sheet's suggestion; never an existing
    project of another engine)."""
    base = safe_name(name) or "My Game"
    for n in range(1, 100):
        candidate = base if n == 1 else f"{base} {n}"[:NAME_MAX]
        if check_new(engine, location, candidate).status == FREE:
            return candidate
    return base
