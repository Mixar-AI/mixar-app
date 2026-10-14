# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Privacy: Mixar's registered properties never leave in glTF ``extras``
(``export_extras_filter``), pinned on hand-built GLB / glTF files."""

import json
import struct

from test_agent_export_workflow import (  # noqa: F401 — fake_scene is a fixture
    agent_export,
    export_destination,
    fake_scene,
)

from mixar.modules.space_mixie_chat.core import export_extras_filter as ef

REGISTERED = {"Scene": {"mixie_chat_input", "mixie_chat_messages", "td", "name"},
              "Object": {"mixar_director_shot", "name"}, "Light": {"energy"}}
BIN = bytes(range(256)) * 9  # 2304 bytes, distinctive


def _doc():
    return {
        "asset": {"version": "2.0"},
        "scenes": [{"nodes": [0], "extras": {
            "mixie_chat_input": "QA-SECRET-DRAFT",
            "mixie_chat_messages": [{"text": "secret transcript"}],
            "td": {"density": 1}, "studio_note": "keep me",
            "_mixar_file_version": [1, 0]}}],
        "nodes": [{"name": "Body", "extras": {"part": "torso"}},
                  {"name": "ShotCam", "extras": {"mixar_active_camera": True,
                                                  "mixar_director_shot": 3}},
                  {"name": "Ghost", "extras": {"mixie_session_id": "s-1", "_RNA_UI": {}}}],
        "materials": [{"name": "M", "extras": {"mixar_paint_state": "x"}}],
        "extensions": {"KHR_lights_punctual": {"lights": [
            {"type": "point", "extras": {"energy": 1000, "rig": "key"}}]}},
    }


def _glb(doc, blob=BIN):
    payload = json.dumps(doc).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    body = (struct.pack("<II", len(payload), 0x4E4F534A) + payload
            + struct.pack("<II", len(blob), 0x004E4942) + blob)
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def _check_clean(doc):
    blob = json.dumps(doc)
    assert "QA-SECRET-DRAFT" not in blob and "secret transcript" not in blob
    assert "mixie_" not in blob and "_RNA_UI" not in blob
    assert doc["scenes"][0]["extras"] == {"studio_note": "keep me"}
    assert doc["nodes"][0]["extras"] == {"part": "torso"}
    assert doc["nodes"][1]["extras"] == {"mixar_active_camera": True}
    assert "extras" not in doc["nodes"][2] and "extras" not in doc["materials"][0]
    assert doc["extensions"]["KHR_lights_punctual"]["lights"][0]["extras"] == {"rig": "key"}


def test_glb_is_rewritten_without_secrets_and_with_the_bin_chunk_intact(tmp_path):
    path = tmp_path / "scene.glb"
    path.write_bytes(_glb(_doc()))
    assert ef.strip_private_extras(str(path), "glb", REGISTERED) == 9
    data = path.read_bytes()
    magic, version, total = struct.unpack_from("<4sII", data, 0)
    assert (magic, version, total) == (b"glTF", 2, len(data))
    json_len, json_type = struct.unpack_from("<II", data, 12)
    assert json_type == 0x4E4F534A and json_len % 4 == 0
    _check_clean(json.loads(data[20:20 + json_len].decode("utf-8")))
    bin_len, bin_type = struct.unpack_from("<II", data, 20 + json_len)
    assert bin_type == 0x004E4942 and bin_len == len(BIN)
    assert data[28 + json_len:] == BIN  # byte-identical
    # The shared read-back still parses it.
    from mixar.modules.space_mixie_chat.core.export_verify import read_glb_json
    assert read_glb_json(str(path))["nodes"][0]["name"] == "Body"


def test_clean_glb_is_left_untouched(tmp_path):
    path = tmp_path / "clean.glb"
    original = _glb({"asset": {"version": "2.0"}, "nodes": [{"extras": {"part": "arm"}}]})
    path.write_bytes(original)
    assert ef.strip_private_extras(str(path), "glb", REGISTERED) == 0
    assert path.read_bytes() == original


def test_gltf_json_is_rewritten(tmp_path):
    path = tmp_path / "scene.gltf"
    path.write_text(json.dumps(_doc()), encoding="utf-8")
    assert ef.strip_private_extras(str(path), "gltf", REGISTERED) == 9
    _check_clean(json.loads(path.read_text(encoding="utf-8")))
    assert ef.strip_private_extras(str(path), "fbx", REGISTERED) == 0


def test_prefix_rule_holds_without_rna(tmp_path):
    doc = _doc()
    stripped = ef.strip_document(doc, {})
    assert "QA-SECRET-DRAFT" not in json.dumps(doc)
    assert doc["nodes"][1]["extras"] == {"mixar_active_camera": True}
    assert doc["scenes"][0]["extras"]["td"] == {"density": 1}  # only RNA knows `td`
    assert stripped == 7


def _secret_exporter(fake_scene, monkeypatch):
    def exporter(filepath, **kwargs):
        fake_scene.calls["exporter"].append(kwargs)
        with open(filepath, "wb") as handle:
            handle.write(_glb({**_doc(), "meshes": [{"primitives": []}] * 2}))
        return {"FINISHED"}

    monkeypatch.setattr(agent_export, "_exporter", lambda fmt: exporter)
    monkeypatch.setattr(ef, "registered_properties", lambda: REGISTERED)


def test_export_to_path_strips_for_the_web_preset(fake_scene, monkeypatch):
    _secret_exporter(fake_scene, monkeypatch)
    dest = str(fake_scene.tmp / "scene.glb")
    result = agent_export.export_to_path(dest, {"format": "glb", "target_scope": "scene",
                                                "use_case": "web", "animations": []})
    assert result["success"] is True, result
    assert result["extras_stripped"] == 9
    with open(dest, "rb") as handle:
        assert b"QA-SECRET-DRAFT" not in handle.read()


def test_presets_without_export_extras_are_not_rewritten(fake_scene, monkeypatch):
    _secret_exporter(fake_scene, monkeypatch)
    calls = []
    monkeypatch.setattr(agent_export, "strip_private_extras",
                        lambda *a, **k: calls.append(a) or 0)
    dest = str(fake_scene.tmp / "hero.glb")
    result = agent_export.export_to_path(dest, {"format": "glb", "target_scope": "scene",
                                                "use_case": "godot", "animations": []})
    assert result["success"] is True and result["extras_stripped"] == 0 and calls == []
    export_destination.set_destination("sess", str(fake_scene.tmp / "room.glb"))
    agent_export.run_export("sess", {"format": "glb", "use_case": "web", "animations": []})
    assert len(calls) == 1  # the agent's export_scene web path is covered too
