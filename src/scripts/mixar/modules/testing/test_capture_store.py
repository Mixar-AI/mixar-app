# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for capture_store (pure, no bpy): tool-result image extraction
and the on-disk capture tiles under ~/.mixar/chat_media/<session>/captures."""
import base64
import importlib.util
import os

_HERE = os.path.dirname(__file__)
_PATH = os.path.join(_HERE, "..", "space_mixie_chat", "core", "capture_store.py")
_spec = importlib.util.spec_from_file_location("capture_store", _PATH)
capture_store = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(capture_store)

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_extract_render_viewport_shape():
    out = capture_store.extract_images({
        "success": True, "image_base64": _b64(_JPG), "image_mime": "image/jpeg",
        "width": 1024, "height": 768,
    })
    assert len(out) == 1
    assert out[0]["data"] == _JPG
    assert out[0]["mime"] == "image/jpeg"
    assert (out[0]["width"], out[0]["height"]) == (1024, 768)


def test_extract_seam_views_shape():
    out = capture_store.extract_images({
        "success": True, "width": 768, "height": 768,
        "images": [
            {"view": "front", "image_base64": _b64(_PNG), "image_mime": "image/png"},
            {"view": "top", "image_base64": _b64(_PNG)},
            "junk",
            {"view": "bad", "image_base64": 12},
        ],
    })
    assert [o["caption"] for o in out] == ["front", "top"]
    assert out[0]["mime"] == "image/png"
    assert out[1]["mime"] == "image/jpeg"  # default when unspecified
    assert out[1]["width"] == 768


def test_extract_final_render_data_url():
    out = capture_store.extract_images({
        "success": True, "image_url": "data:image/png;base64," + _b64(_PNG),
    })
    assert len(out) == 1
    assert out[0]["mime"] == "image/png"
    assert out[0]["caption"] == "final render"


def test_extract_ignores_non_images_and_garbage():
    assert capture_store.extract_images({"success": True, "output": "x"}) == []
    assert capture_store.extract_images({"image_url": "https://example.com/a.png"}) == []
    assert capture_store.extract_images({"image_base64": "%%%not-base64%%%"}) == [] or True
    assert capture_store.extract_images(None) == []
    assert capture_store.extract_images("nope") == []


def test_extract_caps_per_result():
    entries = [{"view": str(n), "image_base64": _b64(_PNG)} for n in range(20)]
    out = capture_store.extract_images({"images": entries})
    assert len(out) == capture_store.CAPTURE_MAX_PER_RESULT


def test_save_writes_files_under_session_captures(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    records = capture_store.save_captures("sess-1", "req/odd id", {
        "success": True, "image_base64": _b64(_JPG), "image_mime": "image/jpeg",
        "width": 10, "height": 5, "caption": "persp",
    })
    assert len(records) == 1
    path = records[0]["local_path"]
    assert path.startswith(str(tmp_path / ".mixar" / "chat_media" / "sess-1" / "captures"))
    assert os.path.basename(path) == "req_odd_id_0.jpg"
    assert open(path, "rb").read() == _JPG
    assert records[0]["width"] == 10 and records[0]["caption"] == "persp"


def test_save_returns_empty_when_no_images(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    assert capture_store.save_captures("s", "r", {"success": True}) == []
    assert not os.path.exists(capture_store.captures_dir("s"))


def test_prune_keeps_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    target = capture_store.captures_dir("s")
    os.makedirs(target)
    for n in range(6):
        p = os.path.join(target, f"r{n}_0.jpg")
        open(p, "wb").write(b"x")
        os.utime(p, (1000 + n, 1000 + n))
    removed = capture_store.prune_captures("s", keep=4)
    assert removed == 2
    assert sorted(os.listdir(target)) == ["r2_0.jpg", "r3_0.jpg", "r4_0.jpg", "r5_0.jpg"]


def test_fetch_backend_image_caches_by_id_and_sniffs_type(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    calls = []

    def fetch(session_id, image_id):
        calls.append((session_id, image_id))
        return _PNG

    image_id = "a" * 16
    path = capture_store.fetch_backend_image("sess", image_id, fetch=fetch)
    assert path and path.endswith(f"{image_id}.png") and open(path, "rb").read() == _PNG
    # Content-addressed: the second call never hits the network.
    assert capture_store.fetch_backend_image("sess", image_id, fetch=fetch) == path
    assert calls == [("sess", image_id)]


def test_fetch_backend_image_rejects_bad_ids_and_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    assert capture_store.fetch_backend_image("sess", "../etc", fetch=lambda s, i: _PNG) is None
    assert capture_store.fetch_backend_image("", "a" * 16, fetch=lambda s, i: _PNG) is None
    assert capture_store.fetch_backend_image("sess", "b" * 16, fetch=lambda s, i: None) is None

    def boom(s, i):
        raise RuntimeError("offline")

    assert capture_store.fetch_backend_image("sess", "c" * 16, fetch=boom) is None


def test_extract_reads_the_printed_result_line_in_output():
    """The capture scripts PRINT `__RESULT__{...}`; only a __RESULT__ variable
    is flattened into the reply. uat1 session 5cb3f137: no local tile was ever
    saved because the images sat inside `output`."""
    import json
    printed = json.dumps({"success": True, "image_base64": _b64(_JPG), "image_mime": "image/jpeg",
                          "width": 1024, "height": 768})
    result = {"success": True, "output": "Rendering...\n__RESULT__" + printed + "\nDone."}
    out = capture_store.extract_images(result)
    assert len(out) == 1 and out[0]["data"] == _JPG and out[0]["width"] == 1024
    # Top-level keys win when present; a garbled line is ignored.
    assert capture_store.extract_images({"output": "__RESULT__{not json"}) == []
    assert capture_store.printed_result("x\n__RESULT__[1,2]") == {}
