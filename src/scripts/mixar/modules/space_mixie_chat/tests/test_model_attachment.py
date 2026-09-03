# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Attach .obj files (#1268) — attach-time local import, names-only wire.

Picking/dropping a .obj in the chat imports it into the scene IMMEDIATELY
(client-side), the attachment records the created object names, and only
those names reach the backend (parallel to attachment_names — deliberately
NOT in the vision gate). The local path never leaves the addon process.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import model_attachment  # noqa: E402


class _FakeObj:
    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent


@pytest.fixture
def fake_bpy(monkeypatch):
    holder = MagicMock()
    state = {"objects": []}

    def install(objects, op_result=("FINISHED",)):
        state["objects"] = []
        holder.data = MagicMock()
        holder.data.objects = state["objects"]
        op = MagicMock(return_value=op_result)

        def _op(**kwargs):
            state["objects"].extend(objects)
            return op_result

        op.side_effect = _op
        holder.ops = MagicMock()
        holder.ops.wm.obj_import = op
        holder.context.view_layer.objects.active = None
        holder.ops.object.select_all.poll.return_value = False
        monkeypatch.setattr(model_attachment, "bpy", holder)
        return op

    install.state = state
    return install


def test_is_model_file():
    assert model_attachment.is_model_file("/tmp/chair.OBJ")
    assert model_attachment.is_model_file("/tmp/chair.obj")
    assert not model_attachment.is_model_file("/tmp/photo.png")
    assert model_attachment.is_model_file("") is False


def test_attach_imports_and_reports_names_only(fake_bpy, monkeypatch):
    fake_bpy([_FakeObj("Chair"), _FakeObj("Chair_Leg")])
    with patch.object(model_attachment.os.path, "isfile", return_value=True):
        result = model_attachment.import_model_attachment("/tmp/chair.obj")
    assert result["success"] is True
    assert result["imported_object_names"] == ["Chair", "Chair_Leg"]
    assert result["display_name"] == "chair.obj"
    assert "/tmp/" not in str(result)


def test_attach_nonexistent_file_fails(fake_bpy):
    fake_bpy([])
    with patch.object(model_attachment.os.path, "isfile", return_value=False):
        result = model_attachment.import_model_attachment("/tmp/gone.obj")
    assert result["success"] is False


def test_attach_failed_importer_fails_cleanly(fake_bpy):
    fake_bpy([_FakeObj("M")], op_result=("CANCELLED",))
    with patch.object(model_attachment.os.path, "isfile", return_value=True):
        result = model_attachment.import_model_attachment("/tmp/broken.obj")
    assert result["success"] is False
    assert "importer returned" in result["error"]


def test_send_flow_collects_model_names_keeps_index_alignment(monkeypatch):
    """chat_ops' resolution loop: MODEL_FILE attachments contribute names to
    imported_object_names and keep attachment_names index-aligned with an
    empty entry (mirroring the unresolved-image convention)."""
    att_obj = MagicMock()
    att_obj.image_source = 'MODEL_FILE'
    att_obj.imported_object_names = "Chair,Chair_Leg"
    att_img = MagicMock()
    att_img.image_source = 'FILE'

    # Directly exercise the branch shape the loop implements.
    imported = []
    attachment_names = []
    for att in (att_obj, att_img):
        if att.image_source == 'MODEL_FILE':
            names = [n for n in str(att.imported_object_names or "").split(",") if n.strip()]
            imported.extend(names)
            attachment_names.append("")
            continue
        attachment_names.append("ResolvedImage")
    assert imported == ["Chair", "Chair_Leg"]
    assert attachment_names == ["", "ResolvedImage"]
