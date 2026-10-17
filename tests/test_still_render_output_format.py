# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Still renders of the user's scene must arm `media_type` before `file_format`.

On Blender 5 a scene whose output is video (FFMPEG) rejects JPEG/PNG until
`media_type` is IMAGE -- the state Director's guide render or a user's own
video setup leaves behind. The agent preview render, the asset-search
thumbnail render, the search image-bytes fallback, Moodboard's copy to the
system clipboard and the Moodboard depth render all write the user's scene, so each must switch the media type first
and restore it BEFORE file_format (FFMPEG is refused while media_type is
IMAGE). The depth render's "no visible meshes" exit used to return with the
engine, view transform and output format still overridden.

The modules are loaded from their files so the test does not pull in the
package `__init__` chains (job queue -> API client -> keyring).
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock

import pytest

_MODULES = Path(__file__).parents[1] / "src/scripts/mixar/modules"
_FORMATS = {"IMAGE": {"PNG", "JPEG", "OPEN_EXR"}, "VIDEO": {"FFMPEG"}}


def _load(relative, name):
    spec = importlib.util.spec_from_file_location(name, _MODULES / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def thumbnails():
    return _load("asset_search/utils/preview_render.py", "asset_preview_render_under_test")


@pytest.fixture(scope="module")
def lookdev():
    return _load("moodboard/core/lookdev_utils.py", "lookdev_utils_under_test")


@pytest.fixture
def agent_preview(monkeypatch):
    # A synthetic parent package satisfies `from . import render_device,
    # render_scene` without importing space_mixie_chat's package chain.
    package = ModuleType("_still_render_chat_core")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package.__name__, package)
    for sibling in ("render_device", "render_scene"):
        stub = MagicMock(name=sibling)
        setattr(package, sibling, stub)
        monkeypatch.setitem(sys.modules, f"{package.__name__}.{sibling}", stub)
    return _load("space_mixie_chat/core/preview_render.py", package.__name__ + ".preview_render")


class _ImageSettings:
    """Mimics Blender 5: file_format is filtered by media_type."""

    def __init__(self):
        self.__dict__.update(media_type="VIDEO", _file_format="FFMPEG", quality=90,
                             color_mode="RGB", color_depth="8", compression=50)

    @property
    def file_format(self):
        return self._file_format

    @file_format.setter
    def file_format(self, value):
        if value not in _FORMATS[self.media_type]:
            raise TypeError(f"enum {value!r} not found for media_type {self.media_type}")
        self._file_format = value

    def snapshot(self):
        return (self.media_type, self.file_format, self.quality,
                self.color_mode, self.color_depth, self.compression)


@pytest.fixture
def video_settings():
    return _ImageSettings()


def test_thumbnail_render_switches_and_restores_a_video_scene(thumbnails, video_settings, tmp_path):
    scene = SimpleNamespace(render=SimpleNamespace(image_settings=video_settings))
    before = video_settings.snapshot()
    seen = []
    result = mock.Mock()
    result.save_render.side_effect = lambda **_: seen.append(
        (video_settings.media_type, video_settings.file_format))
    with mock.patch.object(thumbnails, "bpy") as bpy:
        bpy.data.images.get.return_value = result
        assert thumbnails._render_to_jpeg(scene, str(tmp_path / "t.jpg")) is True
    assert seen == [("IMAGE", "JPEG")]
    assert video_settings.snapshot() == before


def test_search_bytes_fallback_arms_media_type_first():
    body = (_MODULES / "asset_search/ui/operators/asset_search_ops.py").read_text(encoding="utf-8")
    start = body.index("settings = bpy.context.scene.render.image_settings")
    block = body[start:body.index("with open(tmp_path", start)]
    assert block.index("settings.media_type = 'IMAGE'") < block.index("settings.file_format = 'JPEG'")
    finally_block = block[block.index("finally:"):]
    assert finally_block.index("media_type = orig_media_type") < finally_block.index(
        "file_format = orig_format")


def test_agent_preview_switches_and_restores_a_video_scene(agent_preview, video_settings):
    render = SimpleNamespace(engine="BLENDER_EEVEE", resolution_x=1920, resolution_y=1080,
                             resolution_percentage=50, image_settings=video_settings)
    scene = SimpleNamespace(render=render,
                            eevee=SimpleNamespace(taa_render_samples=64))
    before = (video_settings.snapshot(), render.resolution_percentage)
    settings = []

    def set_value(owner, name, value):
        settings.append((owner, name, getattr(owner, name), value))
        setattr(owner, name, value)

    with mock.patch.object(agent_preview, "_downgrade_over_budget", return_value=None), \
            mock.patch.object(agent_preview, "bpy"):
        agent_preview._apply_settings(scene, set_value)
        assert (video_settings.media_type, video_settings.file_format) == ("IMAGE", "PNG")
        agent_preview._restore({"settings": settings})
    assert (video_settings.snapshot(), render.resolution_percentage) == before


def test_clipboard_png_switches_and_restores_a_video_scene(video_settings, tmp_path):
    clipboard = _load("moodboard/core/system_clipboard.py", "system_clipboard_under_test")
    scene = SimpleNamespace(render=SimpleNamespace(image_settings=video_settings))
    before = video_settings.snapshot()
    seen = []
    image = mock.Mock(channels=4)
    image.save_render.side_effect = lambda *_a, **_k: seen.append(
        (video_settings.media_type, video_settings.file_format))
    clipboard.save_blender_image_to_png(image, str(tmp_path / "c.png"), scene)
    assert seen == [("IMAGE", "PNG")]
    assert video_settings.snapshot() == before


def _depth_scene(settings, objects):
    render = SimpleNamespace(engine="CYCLES", film_transparent=False, use_compositing=False,
                             resolution_x=1920, resolution_y=1080, resolution_percentage=100,
                             filepath="//out/", image_settings=settings)
    return SimpleNamespace(
        render=render, camera=object(), objects=objects, use_nodes=False,
        view_settings=SimpleNamespace(view_transform="AgX", look="None"),
        eevee=SimpleNamespace(taa_render_samples=64, use_taa_reprojection=False),
    )


def test_depth_render_without_meshes_restores_the_scene(lookdev, video_settings):
    scene = _depth_scene(video_settings, objects=[])
    before = (scene.render.engine, scene.view_settings.view_transform,
              scene.render.film_transparent, scene.eevee.taa_render_samples)
    image_before = video_settings.snapshot()
    with mock.patch.object(lookdev, "bpy") as bpy:
        bpy.context.scene = scene
        assert lookdev.prepare_depth_render() == (None, False)
    assert (scene.render.engine, scene.view_settings.view_transform,
            scene.render.film_transparent, scene.eevee.taa_render_samples) == before
    assert video_settings.snapshot() == image_before


def test_depth_render_restores_a_video_output_format(lookdev, video_settings):
    """Restore writes media_type before file_format, or VIDEO/FFMPEG is refused."""
    scene = _depth_scene(video_settings, objects=[])
    snapshot = {name: getattr(video_settings, name) for name in lookdev._IMAGE_SETTING_NAMES}
    video_settings.media_type = "IMAGE"
    video_settings.file_format = "PNG"
    video_settings.color_depth = "16"
    with mock.patch.object(lookdev, "bpy"):
        lookdev._restore_render_settings(
            scene, "CYCLES", "AgX", "None", False, False, False, 1920, 1080, 100,
            "//out/", 64, False, snapshot)
    assert (video_settings.media_type, video_settings.file_format,
            video_settings.color_depth) == ("VIDEO", "FFMPEG", "8")


def test_depth_render_arms_media_type_before_png(lookdev):
    src = Path(lookdev.__file__).read_text(encoding="utf-8")
    assert src.index("image_settings.media_type = 'IMAGE'") < src.index(
        "image_settings.file_format = 'PNG'")
