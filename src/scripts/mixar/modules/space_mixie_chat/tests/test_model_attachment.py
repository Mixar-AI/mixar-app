# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Attach model files — attach-time local import, names-only wire.

Picking/dropping a model in the chat imports it into the scene IMMEDIATELY
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

    def install(objects, op_result=("FINISHED",), extension=".obj"):
        state["objects"] = []
        holder.data = MagicMock()
        holder.data.objects = state["objects"]
        op = MagicMock(return_value=op_result)

        def _op(**kwargs):
            state["objects"].extend(objects)
            return op_result

        op.side_effect = _op
        holder.ops = MagicMock()
        submodule, name = model_attachment._IMPORTERS[extension]
        setattr(getattr(holder.ops, submodule), name, op)
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


@pytest.mark.parametrize("extension", model_attachment.IMPORTABLE_EXTENSIONS)
def test_all_supported_formats_dispatch_and_report_names(extension, fake_bpy):
    op = fake_bpy([_FakeObj("Root"), _FakeObj("Child", parent="Root")], extension=extension)
    path = "/tmp/asset" + extension.upper()
    assert model_attachment.is_model_file(path)
    with patch.object(model_attachment.os.path, "isfile", return_value=True):
        result = model_attachment.import_model_attachment(path)
    op.assert_called_once_with(filepath=path)
    assert result == {"success": True, "imported_object_names": ["Root"],
                      "object_count": 1, "display_name": "asset" + extension.upper()}


@pytest.mark.parametrize("extension", [".blend", ".exe", ".mp4", ".stl"])
def test_unsupported_formats_are_not_models(extension):
    assert not model_attachment.is_model_file("asset" + extension)
    assert not model_attachment.import_model_attachment("asset" + extension)["success"]


# --- Send path: each name rides with its own image (BE-B2) ------------------

from concurrent.futures import TimeoutError as FuturesTimeoutError  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from mixar.modules.space_mixie_chat.core import (  # noqa: E402
    attachment_encoding,
    attachment_names as attachment_names_mod,
)
from mixar.modules.space_mixie_chat.core.attachment_pairing import (  # noqa: E402
    legacy_attachment_names,
    pair_names_with_images,
)
from mixar.modules.space_mixie_chat.core.chat_payloads import build_chat_payload  # noqa: E402


def _att(path, source="FILE", imported=""):
    return SimpleNamespace(image_path=path, image_source=source,
                           imported_object_names=imported)


class _Future:
    def __init__(self, value):
        self._value = value

    def result(self, timeout=None):
        if isinstance(self._value, BaseException):
            raise self._value
        return self._value


class _Executor:
    """Runs FILE encodes inline; the encode fn decides each outcome."""

    def submit(self, fn, *args):
        try:
            return _Future(fn(*args))
        except BaseException as exc:  # surfaced through result()
            return _Future(exc)


def _encode_with(monkeypatch, outcomes):
    """``outcomes[path]`` is the encoder's return value or an exception."""
    def fake(path, source):
        out = outcomes[path]
        if isinstance(out, BaseException):
            raise out
        return out
    monkeypatch.setattr(attachment_encoding, "encode_attachment_for_upload", fake)


def _payload(images):
    return build_chat_payload(
        message="hi", instance_id="i", session_id="s", plan_required=False,
        execution_required=True, approval_required=True, image_attachments=images)


def _image_blocks(payload):
    return [b for b in payload["content"] if b["type"] == "image_url"]


def _send(monkeypatch, attachments, outcomes, names):
    _encode_with(monkeypatch, outcomes)
    reports = []
    encoded = attachment_encoding.encode_outgoing_attachments(
        attachments, _Executor(), lambda level, text: reports.append(text))
    assert len(encoded) == len(attachments)  # one slot per attachment
    images = pair_names_with_images(encoded, names)
    return images, _payload(images), reports


def test_encode_failure_at_index_zero_keeps_later_labels(monkeypatch):
    atts = [_att("/a.png"), _att("/b.png"), _att("/c.png")]
    images, payload, reports = _send(
        monkeypatch, atts,
        {"/a.png": RuntimeError("bad png"), "/b.png": ("B64", "image/jpeg"),
         "/c.png": ("C64", "image/jpeg")},
        ["a.png", "b.png", "c.png"])
    blocks = _image_blocks(payload)
    assert [b["name"] for b in blocks] == ["b.png", "c.png"]
    assert blocks[0]["image_url"]["url"].endswith("B64")
    assert "name" not in blocks[0]["image_url"]  # a sibling, never inside
    assert payload["attachment_names"] == ["b.png", "c.png"]
    assert "attachment_names_aligned" not in payload
    assert reports == ["Image encoding failed: bad png"]


def test_timeout_drops_the_image_and_its_name(monkeypatch):
    atts = [_att("/a.png"), _att("/slow.png"), _att("/c.png")]
    images, payload, _ = _send(
        monkeypatch, atts,
        {"/a.png": ("A64", "image/jpeg"), "/slow.png": FuturesTimeoutError(),
         "/c.png": ("C64", "image/jpeg")},
        ["a.png", "slow.png", "c.png"])
    assert [b["name"] for b in _image_blocks(payload)] == ["a.png", "c.png"]
    assert payload["attachment_names"] == ["a.png", "c.png"]


def test_video_then_image_labels_the_image_with_its_own_name(monkeypatch):
    # bpy.data.images.load resolves a name for a movie, but the encoder
    # refuses it: the photo used to be labelled "clip.mp4".
    atts = [_att("/clip.mp4"), _att("/photo.png")]
    images, payload, _ = _send(
        monkeypatch, atts,
        {"/clip.mp4": None, "/photo.png": ("P64", "image/jpeg")},
        ["clip.mp4", "photo.png"])
    blocks = _image_blocks(payload)
    assert len(blocks) == 1 and blocks[0]["name"] == "photo.png"
    assert blocks[0]["image_url"]["url"].endswith("P64")
    assert payload["attachment_names"] == ["photo.png"]


def test_unresolved_file_image_is_sent_without_a_name(monkeypatch):
    loaded = MagicMock()
    loaded.name = "kept.png"
    fake_bpy = MagicMock()
    fake_bpy.data.images.__iter__ = lambda self: iter(())  # none loaded yet
    fake_bpy.data.images.load.return_value = loaded
    monkeypatch.setattr(attachment_names_mod, "bpy", fake_bpy)
    # /gone.png no longer exists on disk: it still encodes from an earlier
    # read but resolves to no bpy.data.images name.
    monkeypatch.setattr(attachment_names_mod.os.path, "isfile",
                        lambda path: path != "/gone.png")
    atts = [_att("/gone.png"), _att("/kept.png")]
    names, _ = attachment_names_mod.resolve_attachment_names(atts)
    assert names == ["", "kept.png"]
    images, payload, _ = _send(
        monkeypatch, atts,
        {"/gone.png": ("G64", "image/jpeg"), "/kept.png": ("K64", "image/jpeg")},
        names)
    blocks = _image_blocks(payload)
    assert "name" not in blocks[0] and blocks[0]["image_url"]["url"].endswith("G64")
    assert blocks[1]["name"] == "kept.png"
    assert payload["attachment_names"] == ["kept.png"]


def test_model_file_contributes_neither_image_nor_label(monkeypatch):
    atts = [_att("/chair.obj", "MODEL_FILE", "Chair,Chair_Leg"), _att("/p.png")]
    monkeypatch.setattr(attachment_names_mod, "bpy", MagicMock())
    _encode_with(monkeypatch, {"/p.png": ("P64", "image/jpeg")})
    encoded = attachment_encoding.encode_outgoing_attachments(atts, _Executor())
    assert encoded == [None, ("P64", "image/jpeg")]
    images = pair_names_with_images(encoded, ["", "p.png"])
    assert images == [{"base64": "P64", "mime_type": "image/jpeg", "name": "p.png"}]
    assert legacy_attachment_names(images) == ["p.png"]


def test_payload_without_any_named_image_omits_the_legacy_list():
    payload = _payload([{"base64": "X", "mime_type": "image/png"}])
    assert "attachment_names" not in payload
    assert "name" not in _image_blocks(payload)[0]


def test_interjection_and_input_paths_carry_the_pairs():
    """OutgoingMessage carries the paired dicts; the input path builds its
    blocks with the same block helper, so names survive both."""
    root = os.path.join(_SRC_SCRIPTS, "mixar", "modules", "space_mixie_chat")
    composer = open(os.path.join(root, "core", "composer_send.py"), encoding="utf-8").read()
    assert "attachments=[image_block(img) for img in (msg.image_attachments or [])]" in composer
    chat_ops = open(os.path.join(root, "ui", "operators", "chat_ops.py"), encoding="utf-8").read()
    assert "encoded_attachments = pair_names_with_images(encoded, names)" in chat_ops
    assert "attachment_names = legacy_attachment_names(encoded_attachments)" in chat_ops
