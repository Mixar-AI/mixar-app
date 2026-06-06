# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for Phase 1 generation-loop-closure enumeration helpers.

Covers:
- list_moodboard_images() filtering and ordering
- add_image_to_moodboard() stamping mixar_created_at_iso
- _get_moodboard_image_info() exposing mixar_created_at_iso
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


def _make_image(name, width=512, height=512):
    """Build a mock bpy.types.Image-shaped object."""
    img = MagicMock()
    img.name = name
    img.size = [width, height]
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


def _make_moodboard_item(
    image_name,
    *,
    selected=False,
    generation_prompt="",
    created_at_iso="",
    z_order=0,
    group_index=-1,
):
    """Build a mock MixieMoodboardImage PropertyGroup item."""
    item = MagicMock()
    item.image = _make_image(image_name)
    item.selected = selected
    item.generation_prompt = generation_prompt
    item.mixar_created_at_iso = created_at_iso
    item.position_x = 0.0
    item.position_y = 0.0
    item.scale = 1.0
    item.rotation = 0.0
    item.flip_horizontal = False
    item.flip_vertical = False
    item.z_order = z_order
    item.group_index = group_index
    item.segments = []
    return item


def _make_context(items):
    """Build a mock bpy.types.Context with a moodboard collection."""
    scene = MagicMock()
    scene.mixie_moodboard_images = items
    ctx = MagicMock()
    ctx.scene = scene
    return ctx


class TestListMoodboardImages(unittest.TestCase):
    """list_moodboard_images() should enumerate all images regardless of selection."""

    def test_returns_all_images_regardless_of_selection(self):
        from mixar.modules.moodboard.core.moodboard_utils import list_moodboard_images
        items = [
            _make_moodboard_item("a.png", selected=True),
            _make_moodboard_item("b.png", selected=False),
            _make_moodboard_item("c.png", selected=False),
        ]
        ctx = _make_context(items)
        result = list_moodboard_images(ctx)
        self.assertEqual(result["count"], 3)
        names = [img["image_name"] for img in result["images"]]
        self.assertEqual(sorted(names), ["a.png", "b.png", "c.png"])

    def test_each_entry_includes_mixar_created_at_iso(self):
        from mixar.modules.moodboard.core.moodboard_utils import list_moodboard_images
        items = [_make_moodboard_item("a.png", created_at_iso="2026-05-08T10:00:00+00:00")]
        ctx = _make_context(items)
        result = list_moodboard_images(ctx)
        self.assertEqual(result["images"][0]["mixar_created_at_iso"], "2026-05-08T10:00:00+00:00")

    def test_filters_by_name_glob(self):
        from mixar.modules.moodboard.core.moodboard_utils import list_moodboard_images
        items = [
            _make_moodboard_item("agent_imagegen_001.png"),
            _make_moodboard_item("user_upload.jpg"),
            _make_moodboard_item("agent_imagegen_002.png"),
        ]
        ctx = _make_context(items)
        result = list_moodboard_images(ctx, name_glob="agent_imagegen_*")
        self.assertEqual(result["count"], 2)

    def test_filters_by_generation_prompt_substring(self):
        from mixar.modules.moodboard.core.moodboard_utils import list_moodboard_images
        items = [
            _make_moodboard_item("a.png", generation_prompt="a wooden barrel, photorealistic"),
            _make_moodboard_item("b.png", generation_prompt="anime cat"),
            _make_moodboard_item("c.png", generation_prompt="oak wood texture"),
        ]
        ctx = _make_context(items)
        result = list_moodboard_images(ctx, generation_prompt_contains="wood")
        self.assertEqual(result["count"], 2)

    def test_since_image_name_returns_only_newer(self):
        from mixar.modules.moodboard.core.moodboard_utils import list_moodboard_images
        items = [
            _make_moodboard_item("a.png", created_at_iso="2026-05-08T10:00:00+00:00"),
            _make_moodboard_item("b.png", created_at_iso="2026-05-08T10:05:00+00:00"),
            _make_moodboard_item("c.png", created_at_iso="2026-05-08T10:10:00+00:00"),
        ]
        ctx = _make_context(items)
        result = list_moodboard_images(ctx, since_image_name="b.png")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["images"][0]["image_name"], "c.png")

    def test_since_image_name_unknown_falls_back_to_all(self):
        from mixar.modules.moodboard.core.moodboard_utils import list_moodboard_images
        items = [
            _make_moodboard_item("a.png", created_at_iso="2026-05-08T10:00:00+00:00"),
            _make_moodboard_item("b.png", created_at_iso="2026-05-08T10:05:00+00:00"),
        ]
        ctx = _make_context(items)
        result = list_moodboard_images(ctx, since_image_name="nonexistent.png")
        self.assertEqual(result["count"], 2)

    def test_limit_caps_results(self):
        from mixar.modules.moodboard.core.moodboard_utils import list_moodboard_images
        items = [_make_moodboard_item(f"img_{i}.png") for i in range(10)]
        ctx = _make_context(items)
        result = list_moodboard_images(ctx, limit=3)
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["images"]), 3)

    def test_no_moodboard_collection_returns_empty(self):
        from mixar.modules.moodboard.core.moodboard_utils import list_moodboard_images
        scene = MagicMock(spec=[])  # no mixie_moodboard_images attr
        ctx = MagicMock()
        ctx.scene = scene
        result = list_moodboard_images(ctx)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["images"], [])


class TestGetMoodboardImageInfoIncludesTimestamp(unittest.TestCase):
    """The shared formatter must surface mixar_created_at_iso."""

    def test_get_selected_moodboard_images_returns_created_at_iso(self):
        from mixar.modules.moodboard.core.moodboard_utils import get_selected_moodboard_images
        items = [
            _make_moodboard_item("a.png", selected=True, created_at_iso="2026-05-08T10:00:00+00:00"),
        ]
        ctx = _make_context(items)
        result = get_selected_moodboard_images(ctx)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["images"][0]["mixar_created_at_iso"], "2026-05-08T10:00:00+00:00")


class TestAddImageToMoodboardStampsTimestamp(unittest.TestCase):
    """add_image_to_moodboard must stamp mixar_created_at_iso on insertion."""

    def test_stamps_iso_timestamp(self):
        from mixar.modules.common.utils import image_utils

        added_item = MagicMock()
        added_item.mixar_created_at_iso = ""
        scene = MagicMock()
        scene.mixie_moodboard_images = MagicMock()
        scene.mixie_moodboard_images.add.return_value = added_item
        scene.mixie_moodboard_images.__len__.return_value = 1

        with patch.object(image_utils, "bpy") as mock_bpy:
            mock_bpy.context.scene = scene
            mock_bpy.context.screen.areas = []
            image_utils.add_image_to_moodboard(_make_image("x.png"), prompt="hi", position_x=0.0, position_y=0.0)

        self.assertNotEqual(added_item.mixar_created_at_iso, "")
        # Loose ISO-8601 sniff: "YYYY-MM-DD" prefix
        self.assertRegex(added_item.mixar_created_at_iso, r"^\d{4}-\d{2}-\d{2}T")


if __name__ == "__main__":
    unittest.main()
