# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pasting an image works on every island tab, not only Agent.

``mixie_chat.paste_image`` (the inline text-edit hook and the Ctrl/Cmd+V
keymap both reach it) used to add every pasted image to the Agent
composer's pending attachments — invisible and unused on the 3D, Image,
Video and Gaussian Splat tabs. It now routes by ``mixar_bubble_tab`` through
``agent_bubble/core/pane_references.py``, the table the viewport capture
also uses, so a paste lands where that pane's own upload puts it.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.agent_bubble.core import pane_references  # noqa: E402
from mixar.modules.space_mixie_chat.ui.operators import clipboard_ops  # noqa: E402


def _context(area_type, tab):
    area = SimpleNamespace(type=area_type) if area_type else None
    return SimpleNamespace(area=area,
                           window_manager=SimpleNamespace(mixar_bubble_tab=tab))


class TestActivePaneTab:
    @pytest.mark.parametrize("tab", ["THREE_D", "IMAGE", "VIDEO", "SPLAT"])
    def test_generation_tabs_route_to_their_pane(self, tab):
        assert clipboard_ops.active_pane_tab(_context('AGENT_BUBBLE', tab)) == tab

    @pytest.mark.parametrize("tab", ["AGENT", "GENERATIONS", "QUEUE"])
    def test_other_tabs_keep_the_agent_attachment(self, tab):
        assert clipboard_ops.active_pane_tab(_context('AGENT_BUBBLE', tab)) is None

    @pytest.mark.parametrize("area_type", [None, 'VIEW_3D', 'MIXIE'])
    def test_only_a_paste_inside_the_island_follows_its_tab(self, area_type):
        assert clipboard_ops.active_pane_tab(_context(area_type, 'IMAGE')) is None

    def test_literal_tab_set_matches_the_routing_table(self):
        assert clipboard_ops._PANE_TABS == pane_references.PANE_TABS

    def test_paste_image_routes_before_the_agent_attachment_limit(self):
        source = Path(clipboard_ops.__file__).read_text(encoding="utf-8")
        route = source.index("pane = active_pane_tab(context)")
        assert route < source.index("MAX_ATTACHMENTS_PER_MESSAGE:")
        assert route < source.index("attachments.add()")


def _scene():
    tab3d = SimpleNamespace(reference_image=None, use_selected_image=True)
    splat = SimpleNamespace(reference_image=None, use_selected_image=True)
    sidebar = SimpleNamespace(tab_image_to_3d=tab3d, tab_world_labs=splat,
                              tab_imagegen=SimpleNamespace())
    return SimpleNamespace(mixie_moodboard_sidebar=sidebar)


class TestAttachFileToPane:
    @pytest.fixture
    def image(self, monkeypatch):
        img = SimpleNamespace(name="Pasted Image")
        monkeypatch.setattr(pane_references, "_load_packed", lambda path, name: img)
        return img

    @pytest.mark.parametrize("tab,owner", [("THREE_D", "tab_image_to_3d"),
                                           ("SPLAT", "tab_world_labs")])
    def test_single_reference_panes(self, image, tab, owner):
        scene = _scene()
        pane_references.attach_file_to_pane(scene, tab, "/tmp/p.png", "Pasted Image")
        target = getattr(scene.mixie_moodboard_sidebar, owner)
        assert target.reference_image is image
        assert target.use_selected_image is False

    def test_image_pane_uses_the_upload_reference_add(self, image, monkeypatch):
        calls = []
        monkeypatch.setattr(pane_references, "attach_to_imagegen",
                            lambda scene, img, path: calls.append((img, path)))
        pane_references.attach_file_to_pane(_scene(), "IMAGE", "/tmp/p.png")
        assert calls == [(image, "/tmp/p.png")]

    def test_video_pane_boards_the_file_selected(self, monkeypatch):
        loaded = MagicMock()
        monkeypatch.setattr(pane_references, "attach_to_board_selected",
                            lambda scene, path: loaded)
        monkeypatch.setattr(pane_references, "_load_packed",
                            MagicMock(side_effect=AssertionError("not loaded")))
        pane_references.attach_file_to_pane(_scene(), "VIDEO", "/tmp/p.png")

    def test_video_board_failure_raises(self, monkeypatch):
        monkeypatch.setattr(pane_references, "attach_to_board_selected",
                            lambda scene, path: None)
        with pytest.raises(RuntimeError):
            pane_references.attach_file_to_pane(_scene(), "VIDEO", "/tmp/p.png")

    def test_non_pane_tab_is_refused(self):
        with pytest.raises(ValueError):
            pane_references.attach_file_to_pane(_scene(), "AGENT", "/tmp/p.png")
