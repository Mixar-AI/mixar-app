# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for moodboard system clipboard export helpers."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    ROOT
    / "src/scripts/mixar/modules/moodboard/core/system_clipboard.py"
)


def _load_module():
    spec = spec_from_file_location("moodboard_system_clipboard", MODULE_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_macos_path_is_an_argv_value_not_applescript_source(monkeypatch):
    module = _load_module()
    calls = []
    dangerous_path = '/tmp/image" & display dialog "oops.png'

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    module._copy_png_to_clipboard_macos(dangerous_path)

    argv, kwargs = calls[0]
    assert argv == [
        'osascript',
        '-e',
        module._MACOS_CLIPBOARD_SCRIPT,
        dangerous_path,
    ]
    assert dangerous_path not in module._MACOS_CLIPBOARD_SCRIPT
    assert kwargs == {"check": True, "capture_output": True}


@pytest.mark.parametrize("channels, expected_mode", [(4, 'RGBA'), (3, 'RGB')])
def test_blender_png_export_uses_explicit_scene_and_restores_settings(
    channels,
    expected_mode,
):
    module = _load_module()
    settings = SimpleNamespace(file_format='JPEG', color_mode='BW')
    scene = SimpleNamespace(
        render=SimpleNamespace(image_settings=settings),
    )
    calls = []
    image = SimpleNamespace(
        channels=channels,
        save_render=lambda path, **kwargs: calls.append(
            (path, kwargs, settings.file_format, settings.color_mode)
        ),
    )

    module.save_blender_image_to_png(image, "/tmp/output.png", scene)

    assert calls == [
        ("/tmp/output.png", {"scene": scene}, 'PNG', expected_mode),
    ]
    assert settings.file_format == 'JPEG'
    assert settings.color_mode == 'BW'


def test_blender_png_export_restores_settings_after_failure():
    module = _load_module()
    settings = SimpleNamespace(file_format='OPEN_EXR', color_mode='RGB')
    scene = SimpleNamespace(
        render=SimpleNamespace(image_settings=settings),
    )

    def fail(*_args, **_kwargs):
        assert settings.file_format == 'PNG'
        assert settings.color_mode == 'RGBA'
        raise RuntimeError("save failed")

    image = SimpleNamespace(channels=4, save_render=fail)

    with pytest.raises(RuntimeError, match="save failed"):
        module.save_blender_image_to_png(image, "/tmp/output.png", scene)

    assert settings.file_format == 'OPEN_EXR'
    assert settings.color_mode == 'RGB'


def test_temporary_png_is_removed_after_clipboard_copy(monkeypatch, tmp_path):
    module = _load_module()
    temp_path = tmp_path / "clipboard.png"
    copied = []
    scene = object()
    image = object()

    class _TemporaryFile:
        name = str(temp_path)

        def __enter__(self):
            temp_path.write_bytes(b"")
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        module.tempfile,
        "NamedTemporaryFile",
        lambda **_kwargs: _TemporaryFile(),
    )
    monkeypatch.setattr(
        module,
        "save_blender_image_to_png",
        lambda actual_image, path, actual_scene: temp_path.write_bytes(b"png"),
    )
    monkeypatch.setattr(
        module,
        "copy_png_to_system_clipboard",
        lambda path: copied.append((path, Path(path).read_bytes())),
    )

    module.copy_blender_image_to_system_clipboard(image, scene)

    assert copied == [(str(temp_path), b"png")]
    assert not temp_path.exists()
