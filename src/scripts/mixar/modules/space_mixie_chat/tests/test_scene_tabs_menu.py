# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Island header scene-tab switcher label (parallel scene tabs)."""

from types import SimpleNamespace

from _open_run_support import live_bpy  # noqa: F401

from mixar.modules.agent_bubble.ui.menus import scene_tabs_menu as menu


def test_label_is_the_tab_name_with_an_attention_dot():
    scene = SimpleNamespace(name="Kitchen")
    assert menu.tab_label(scene, SimpleNamespace(mixar_scene_tabs_attention=False)) == "Kitchen"
    assert menu.tab_label(scene, SimpleNamespace(mixar_scene_tabs_attention=True)) == "● Kitchen"


def test_long_names_are_elided():
    scene = SimpleNamespace(name="A" * 40)
    label = menu.tab_label(scene, None)
    assert len(label) == menu._LABEL_MAX and label.endswith("…")
