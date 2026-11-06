# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the card writes, and the logos every tile and engine chip needs."""

import os
from pathlib import Path

import pytest

from mixar.modules.export_card import constants as C
from mixar.modules.export_card.core import destination, logos, targets

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("raw, ext, expected", [
    ("chair", ".glb", "chair"), ("chair.glb", ".glb", "chair"), ("a/b:c*d", "", "a_b_c_d"),
    ("  ", "", "export"), ("..hidden..", "", "hidden"),
])
def test_clean_stem(raw, ext, expected):
    assert destination.clean_stem(raw, ext) == expected


def test_defaults_follow_the_open_project(tmp_path):
    blend = str(tmp_path / "Nook.mixar")
    assert destination.default_stem(blend, "Scene") == "Nook"
    assert destination.default_folder(blend, "D:/dl") == str(tmp_path / "exports")
    assert destination.default_stem("", "Scene 2") == "Scene 2"
    assert destination.default_folder("", "D:/dl") == "D:/dl"


def test_problems_are_named(tmp_path):
    assert destination.problem("", "x")
    assert destination.problem("relative/folder", "x")
    assert destination.problem(str(tmp_path), "  ")
    assert destination.problem(str(tmp_path), "CON")
    assert destination.problem(str(tmp_path), "chair") == ""
    # A folder that does not exist yet is fine: it is created on export.
    assert destination.problem(str(tmp_path / "new" / "deeper"), "chair") == ""


def test_full_path_and_exists(tmp_path):
    path = destination.full_path(str(tmp_path), "chair.glb", ".glb")
    assert path == os.path.join(str(tmp_path), "chair.glb")
    assert not destination.exists(str(tmp_path), "chair", ".glb")
    Path(path).write_bytes(b"x")
    assert destination.exists(str(tmp_path), "chair", ".glb")


def test_every_target_has_a_group_and_an_extension():
    assert {t.id for t in targets.TARGETS} == set(
        C.PROJECT_TARGETS + C.MODEL_TARGETS + C.RENDER_TARGETS + (C.WEB,))
    for target in targets.TARGETS:
        assert target.group in targets.GROUPS
        assert bool(targets.extension(target.id)) == (target.id != C.WEB)
    assert targets.extension(C.IMAGE, render_format='OPEN_EXR') == ".exr"


def test_every_logo_ships():
    keys = {t.logo for t in targets.TARGETS} | {logo for _k, _l, logo in targets.ENGINE_CHIPS
                                               if logo}
    assert keys <= set(logos.KEYS) | set(logos.ENGINE_KEYS)
    for key in keys:
        assert os.path.isfile(logos._path(key)), key


def test_third_party_marks_are_credited():
    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    for owner in ("Blender Foundation", "Khronos", "OpenUSD", "Autodesk", "three.js", "Unity",
                  "Apple", "Simple Icons"):
        assert owner in notice, owner
