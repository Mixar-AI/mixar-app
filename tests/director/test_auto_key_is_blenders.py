# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cinema Mode's Auto Key IS Blender's Auto Keying.

It was a Director-only flag, so the Timeline's record button and the Cinema
dock's chip were two switches for one idea. The property is now a proxy onto
`tool_settings.use_keyframe_insert_auto`, and every Director reader (the
recorder, the stillness debounce, the walk's exit capture) keeps asking
`state.auto_key`.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director.core.property_updates import _get_auto_key, _set_auto_key

ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
PROPERTIES = (DIRECTOR / "ui/properties/director_properties.py").read_text(encoding="utf-8")


def _state(value: bool = False):
    tool_settings = SimpleNamespace(use_keyframe_insert_auto=value)
    return SimpleNamespace(id_data=SimpleNamespace(tool_settings=tool_settings)), tool_settings


def test_reading_it_reads_blenders_switch():
    state, _tool_settings = _state(True)
    assert _get_auto_key(state) is True
    state, _tool_settings = _state(False)
    assert _get_auto_key(state) is False


def test_writing_it_flips_blenders_switch():
    state, tool_settings = _state(False)
    _set_auto_key(state, True)
    assert tool_settings.use_keyframe_insert_auto is True
    _set_auto_key(state, False)
    assert tool_settings.use_keyframe_insert_auto is False


def test_it_fails_closed_without_a_scene():
    """Property callbacks run during file load, before the data is reachable."""
    orphan = SimpleNamespace(id_data=None)
    assert _get_auto_key(orphan) is False
    _set_auto_key(orphan, True)  # must not raise


def test_the_property_has_no_storage_of_its_own():
    block = PROPERTIES[PROPERTIES.index("    auto_key: BoolProperty(") :]
    block = block[: block.index("    )\n") + 6]
    assert "get=_get_auto_key," in block
    assert "set=_set_auto_key," in block
    assert "default=" not in block
