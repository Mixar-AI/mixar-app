# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""``export_package._save_textures`` leaves no copy behind when a save fails:
an in-process export runs on the user's own document (mixar-backend#2020).
Kept out of ``test_export_verify.py``, which is at the 500-line limit."""

from unittest.mock import MagicMock

import pytest

from mixar.modules.space_mixie_chat.core import export_package


def test_a_failed_texture_save_frees_every_copy_made_so_far(tmp_path, monkeypatch):
    bpy = export_package.bpy  # the module's own binding, whatever the session swapped in

    class Image:
        def __init__(self, name, save_error=None):
            self.name, self.size = name, (4, 4)
            self.filepath_raw = self.file_format = None
            self.save_error = save_error

        def save(self):
            if self.save_error:
                raise self.save_error

    saved, failing = Image("saved"), Image("failing", OSError("disk full"))
    copies = iter([saved, failing])  # a third copy would mean the loop went on
    monkeypatch.setattr(export_package, "_pixel_copy", lambda img, name: next(copies))
    monkeypatch.setattr(bpy.data.images, "remove", removed := MagicMock())
    images = [Image("Wood"), Image("Stone"), Image("Iron")]
    with pytest.raises(OSError, match="disk full"):
        export_package._save_textures(images, str(tmp_path / "textures"))
    freed = [call.args[0] for call in removed.call_args_list]
    assert len(freed) == 2 and saved in freed and failing in freed
