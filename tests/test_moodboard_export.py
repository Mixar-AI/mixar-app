# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""export_moodboard_images refuses what it cannot write, before touching disk.

The writing itself (real PNG / JPEG / WebP encodings of packed board images,
alpha kept, nothing leaked) was verified in the running app — a packed copy's
save() wrote PNG bytes under a .jpg name, which is why it encodes from pixels.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.moodboard.core import media_utils  # noqa: E402
from mixar.modules.space_mixie_chat.core import moodboard_export  # noqa: E402


def _scene(*items):
    return SimpleNamespace(mixie_moodboard_images=list(items))


def _item(name, still=True):
    return SimpleNamespace(image=SimpleNamespace(name=name, size=(64, 64), source="FILE"), still=still)


def test_requests_it_cannot_write_are_refused_with_a_reason(monkeypatch):
    monkeypatch.setattr(media_utils, "is_still_item", lambda item: item.still)
    scene = _scene(_item("dog_head"), _item("turntable.mp4", still=False))
    export = moodboard_export.export_moodboard_images
    assert "format" in export(["dog_head"], "gif", scene=scene)["error"]
    assert "destination" in export(["dog_head"], "png", "C:/Users", scene=scene)["error"]
    assert "1 to 50" in export([], scene=scene)["error"]
    assert "1 to 50" in export([f"i{n}" for n in range(51)], scene=scene)["error"]
    missing = export(["cat"], scene=scene)
    assert missing["success"] is False and "Not on this tab's moodboard: cat" in missing["error"]
    video = export(["turntable.mp4"], scene=scene)
    assert video["success"] is False and "videos: turntable.mp4" in video["error"]
