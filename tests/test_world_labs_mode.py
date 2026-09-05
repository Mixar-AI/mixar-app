# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""World Labs mode must follow inputs, not a stale catalog default."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src/scripts/mixar/modules/moodboard/core/world_labs_mode.py"
)


def _load():
    spec = spec_from_file_location("world_labs_queue_under_test", MODULE_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_explicit_text_mode_is_honored_even_when_an_image_is_present():
    resolve = _load().resolve_world_labs_mode
    assert resolve("text", has_image=True, has_prompt=True) == "text"


def test_prompt_only_does_not_keep_the_image_catalog_default():
    resolve = _load().resolve_world_labs_mode
    assert resolve("image", has_image=False, has_prompt=True) == "text"


def test_image_input_keeps_image_mode():
    resolve = _load().resolve_world_labs_mode
    assert resolve("image", has_image=True, has_prompt=False) == "image"
    assert resolve("", has_image=True, has_prompt=True) == "image"
