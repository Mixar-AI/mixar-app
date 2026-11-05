# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""``engine_projects`` and the Connect engine sheet: where a new game goes,
the user's own location, and a Godot and an Unreal game never sharing one
folder (no Godot, no Unreal, no Blender)."""

import os
import sys
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import engine_connect as ec  # noqa: E402
from mixar.modules.space_mixie_chat.core import engine_projects as ep  # noqa: E402

_OPS = os.path.join(_SRC_SCRIPTS, "mixar", "modules", "space_mixie_chat", "ui", "operators")


def _godot(folder):
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "project.godot"), "w").close()


def _unreal(folder, name="MyGame"):
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, f"{name}.uproject"), "w").close()


def test_a_missing_or_empty_folder_is_free(tmp_path):
    check = ep.check_new("godot", str(tmp_path), "My Game")
    assert check.status == ep.FREE and check.folder == str(tmp_path / "My Game") and check.ok
    (tmp_path / "Empty").mkdir()
    assert ep.check_new("unreal", str(tmp_path), "Empty").status == ep.FREE


def test_the_same_engines_project_is_opened_again(tmp_path):
    _godot(str(tmp_path / "My Game"))
    check = ep.check_new("godot", str(tmp_path), "My Game")
    assert check.status == ep.SAME and check.ok and "Connect opens it" in check.text()


@pytest.mark.parametrize("engine, other, make", [("unreal", "Godot", _godot), ("godot", "Unreal", _unreal)])
def test_another_engines_project_of_the_same_name_is_refused(tmp_path, engine, other, make):
    make(str(tmp_path / "My Game"))
    check = ep.check_new(engine, str(tmp_path), "My Game")
    assert check.status == ep.TAKEN and not check.ok
    assert f"already holds a {other} project" in check.text()


def test_a_folder_holding_both_engines_is_refused_for_a_new_project(tmp_path):
    _godot(str(tmp_path / "My Game"))
    _unreal(str(tmp_path / "My Game"))
    for engine in ("godot", "unreal"):
        assert ep.check_new(engine, str(tmp_path), "My Game").status == ep.TAKEN


def test_a_non_empty_folder_is_refused(tmp_path):
    (tmp_path / "Notes").mkdir()
    (tmp_path / "Notes" / "todo.txt").write_text("x")
    check = ep.check_new("godot", str(tmp_path), "Notes")
    assert check.status == ep.TAKEN and "not empty" in check.text()


def test_bad_names_and_locations_are_invalid(tmp_path):
    assert ep.check_new("godot", str(tmp_path), "  ?? ").status == ep.INVALID
    assert ep.check_new("godot", "", "Game").status == ep.EMPTY
    assert ep.check_new("godot", str(tmp_path), "  ").status == ep.EMPTY
    assert ep.check_new("godot", "relative/folder", "Game").status == ep.INVALID
    (tmp_path / "file").write_text("x")
    assert ep.check_new("godot", str(tmp_path / "file"), "Game").status == ep.INVALID


def test_the_name_becomes_a_safe_folder_name(tmp_path):
    check = ep.check_new("godot", str(tmp_path), 'My: "Game"/2')
    assert os.path.basename(check.folder) == "My Game 2"


def test_unique_name_skips_projects_of_any_engine(tmp_path):
    _godot(str(tmp_path / "My Game"))
    _unreal(str(tmp_path / "My Game 2"))
    assert ep.unique_name("unreal", str(tmp_path), "My Game") == "My Game 3"
    assert ep.unique_name("godot", str(tmp_path), "Fresh") == "Fresh"


def test_existing_projects_must_hold_the_engines_file(tmp_path):
    assert ep.check_existing("godot", "").status == ep.EMPTY and not ep.check_existing("godot", "").ok
    assert ep.check_existing("godot", str(tmp_path / "nope")).status == ep.INVALID
    _unreal(str(tmp_path / "U"))
    check = ep.check_existing("godot", str(tmp_path / "U"))
    assert check.status == ep.INVALID and "project.godot" in check.text()
    assert ep.check_existing("unreal", str(tmp_path / "U")).ok
    _godot(str(tmp_path / "G"))
    assert "a .uproject" in ep.check_existing("unreal", str(tmp_path / "G")).text()


def test_a_bracketed_folder_is_matched_literally(tmp_path):
    _unreal(str(tmp_path / "Game [v2]"))
    assert ep.check_existing("unreal", str(tmp_path / "Game [v2]")).ok


def test_the_default_location_is_the_users_choice_when_it_exists(tmp_path, monkeypatch):
    import mixar.config.config as config
    monkeypatch.setattr(config, "get_config", lambda: {ep.CONFIG_KEY: str(tmp_path)})
    assert ep.default_location() == str(tmp_path)
    monkeypatch.setattr(config, "get_config", lambda: {ep.CONFIG_KEY: str(tmp_path / "gone")})
    assert ep.default_location().endswith(os.path.join("Documents", "Mixar Games"))


@pytest.mark.parametrize("engine, make", [("unreal", _godot), ("godot", _unreal)])
def test_connect_refuses_a_new_project_in_another_engines_folder(tmp_path, monkeypatch, engine, make):
    """The core guard holds whatever the sheet did: nothing is downloaded,
    created or installed into the other engine's project."""
    folder = str(tmp_path / "My Game")
    make(folder)
    before = sorted(os.listdir(folder))
    touched = []
    for name in ("find_godot", "download_godot", "create_project", "install_addon", "_connect_unreal"):
        monkeypatch.setattr(ec, name, lambda *a, _n=name, **k: touched.append(_n))
    with pytest.raises(ValueError, match="already holds"):
        ec.connect(folder, engine=engine, new_name="My Game")
    assert touched == [] and sorted(os.listdir(folder)) == before


def test_connect_reopens_the_same_engines_project(tmp_path, monkeypatch):
    folder = str(tmp_path / "My Game")
    _unreal(folder)
    calls = []
    monkeypatch.setattr(ec, "_connect_unreal", lambda *a: calls.append(a) or {"ok": True})
    assert ec.connect(folder, engine="unreal", new_name="My Game") == {"ok": True}
    assert calls and calls[0][0] == folder


def test_the_sheet_is_the_kit_sheet_with_a_location_and_one_default():
    sheet = open(os.path.join(_OPS, "engine_sheet_ui.py"), encoding="utf-8").read()
    ops = open(os.path.join(_OPS, "engine_ops.py"), encoding="utf-8").read()
    assert "from mixar.modules.common.sheet import kit as S" in sheet
    assert "mixar_sheet_frame(header=S.HEADER, sidebar=S.SIDEBAR)" in sheet
    # The user picks where a new project goes: a Browse pill docked in the field
    # opens the folder browser (no stock Blender path icon in the sheet).
    assert "'mixar_engine_dialog_location', browse='location'" in sheet
    assert 'bl_idname = "mixar.engine_browse_folder"' in ops and "fileselect_add(self)" in ops
    assert "Documents/Mixar Games" not in sheet and "GAMES_DIR" not in ops
    # Exactly one active default: Connect, a confirm button that closes the sheet.
    assert sheet.count("default=True") == 1 and "S.confirm(slot, OP_START" in sheet
    assert 'bl_idname = "mixar.engine_connect_start"' in ops
    # Connect is refused unless the field check passes, and the location is remembered.
    assert "self.check.ok" in ops and "engine_projects.remember_location(" in ops
    props = open(os.path.join(_SRC_SCRIPTS, "mixar", "modules", "space_mixie_chat", "ui", "properties",
                              "engine_dialog_props.py"), encoding="utf-8").read()
    assert "subtype='DIR_PATH'" not in props and "options={'SKIP_SAVE'}" in props
    assert props.count("update=_repaint_sheet") == 2


def test_the_engine_rows_lead_with_the_real_logos():
    from mixar.modules.space_mixie_chat.core import engine_logos
    for key in engine_logos.KEYS:
        assert os.path.isfile(os.path.join(engine_logos.ASSETS, f"{key}.png")), key
    sheet = open(os.path.join(_OPS, "engine_sheet_ui.py"), encoding="utf-8").read()
    assert "icon_value=engine_logos.icon_id(logo)" in sheet
    # Logos load once when the sheet opens, never inside a draw.
    ops = open(os.path.join(_OPS, "engine_ops.py"), encoding="utf-8").read()
    invoke = ops[ops.index("from ...core import engine_logos, engine_projects"):]
    assert "engine_logos.load()" in invoke[:300] and "engine_logos.load()" not in sheet
    painter = open(os.path.join(_SRC_SCRIPTS, "..", "source", "blender", "editors", "interface",
                                "interface_mixar_sheet_controls.cc"), encoding="utf-8").read()
    assert "icon_draw_preview(x, BLI_rctf_cent_y(&pill)" in painter
    assert engine_logos.icon_id("godot") == 0  # nothing loaded outside Blender: the name alone
