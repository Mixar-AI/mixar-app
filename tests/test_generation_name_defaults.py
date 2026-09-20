# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Mesh-name defaults must strip image stems the same way as the backend."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src/scripts/mixar/modules/moodboard/core/generation_names.py"
)


def _load():
    spec = spec_from_file_location("generation_enqueue_under_test", MODULE_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_image_stems_drop_known_extensions():
    sanitize = _load().sanitize_label
    assert sanitize("dragon.png") == "dragon"
    assert sanitize("Hero.JPEG") == "Hero"
    assert sanitize("plate.exr") == "plate"
    assert sanitize("loop.gif") == "loop"
    assert sanitize("R2.D2") == "R2_D2"


def test_derive_model_name_prefers_explicit_then_image_then_prompt():
    derive = _load().derive_model_name
    image = SimpleNamespace(name="dragon.png")
    assert derive(image, "a red sports car", explicit="custom_mesh") == "custom_mesh"
    assert derive(image, "a red sports car") == "dragon"
    assert derive(None, "a red sports car") == "red_sports_car"
