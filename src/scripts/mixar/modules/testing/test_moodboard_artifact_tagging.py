# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for Phase 2 generation-loop-closure artifact tagging.

Covers:
- add_image_to_moodboard() accepts a job_handle kwarg and stamps mixar_job_handle.
- _get_moodboard_image_info() exposes mixar_job_handle in its output dict.
- list_moodboard_images() surfaces mixar_job_handle for each item.
"""

import sys, os
_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
try:
    import bpy  # noqa: F401
except ImportError:
    import importlib.util
    _mock_spec = importlib.util.spec_from_file_location(
        "mock_bpy", os.path.join(_test_dir, "mock_bpy.py"))
    _mock_mod = importlib.util.module_from_spec(_mock_spec)
    _mock_spec.loader.exec_module(_mock_mod)

import unittest
from unittest.mock import MagicMock, patch


def _make_image(name):
    img = MagicMock()
    img.name = name
    img.size = [512, 512]
    img.channels = 4
    img.has_data = True
    img.packed_file = None
    img.is_dirty = False
    img.file_format = "PNG"
    img.filepath = ""
    cs = MagicMock()
    cs.name = "sRGB"
    img.colorspace_settings = cs
    return img


def _make_item(image_name, *, job_handle="", created_at_iso=""):
    item = MagicMock()
    item.image = _make_image(image_name)
    item.selected = False
    item.generation_prompt = ""
    item.mixar_created_at_iso = created_at_iso
    item.mixar_job_handle = job_handle
    item.position_x = 0.0
    item.position_y = 0.0
    item.scale = 1.0
    item.rotation = 0.0
    item.flip_horizontal = False
    item.flip_vertical = False
    item.z_order = 0
    item.group_index = -1
    item.segments = []
    return item


class TestAddImageToMoodboardJobHandle(unittest.TestCase):

    def test_job_handle_kwarg_stamped(self):
        from mixar.modules.common.utils import image_utils

        added = MagicMock()
        added.mixar_job_handle = ""
        added.mixar_created_at_iso = ""
        scene = MagicMock()
        scene.mixie_moodboard_images = MagicMock()
        scene.mixie_moodboard_images.add.return_value = added
        scene.mixie_moodboard_images.__len__.return_value = 1

        with patch.object(image_utils, "bpy") as mock_bpy:
            mock_bpy.context.scene = scene
            mock_bpy.context.screen.areas = []
            image_utils.add_image_to_moodboard(
                _make_image("x.png"),
                prompt="hi",
                position_x=0.0,
                position_y=0.0,
                job_handle="req-abc-123",
            )

        self.assertEqual(added.mixar_job_handle, "req-abc-123")

    def test_job_handle_default_empty(self):
        """When omitted, mixar_job_handle should not be set to anything."""
        from mixar.modules.common.utils import image_utils

        added = MagicMock()
        added.mixar_job_handle = ""
        added.mixar_created_at_iso = ""
        scene = MagicMock()
        scene.mixie_moodboard_images = MagicMock()
        scene.mixie_moodboard_images.add.return_value = added
        scene.mixie_moodboard_images.__len__.return_value = 1

        with patch.object(image_utils, "bpy") as mock_bpy:
            mock_bpy.context.scene = scene
            mock_bpy.context.screen.areas = []
            image_utils.add_image_to_moodboard(
                _make_image("x.png"),
                prompt="hi",
                position_x=0.0,
                position_y=0.0,
            )

        # Default behaviour should leave it as "" (no implicit handle).
        self.assertEqual(added.mixar_job_handle, "")


class TestImageInfoExposesJobHandle(unittest.TestCase):

    def test_get_selected_includes_mixar_job_handle(self):
        from mixar.modules.moodboard.core.moodboard_utils import get_selected_moodboard_images
        items = [_make_item("a.png", job_handle="req-1")]
        items[0].selected = True
        scene = MagicMock()
        scene.mixie_moodboard_images = items
        ctx = MagicMock()
        ctx.scene = scene

        result = get_selected_moodboard_images(ctx)
        self.assertEqual(result["images"][0]["mixar_job_handle"], "req-1")

    def test_list_includes_mixar_job_handle(self):
        from mixar.modules.moodboard.core.moodboard_utils import list_moodboard_images
        items = [
            _make_item("a.png", job_handle="req-1"),
            _make_item("b.png", job_handle=""),
        ]
        scene = MagicMock()
        scene.mixie_moodboard_images = items
        ctx = MagicMock()
        ctx.scene = scene

        result = list_moodboard_images(ctx)
        handles = {img["image_name"]: img["mixar_job_handle"] for img in result["images"]}
        self.assertEqual(handles["a.png"], "req-1")
        self.assertEqual(handles["b.png"], "")


if __name__ == "__main__":
    unittest.main()
