# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Virtual Camera's UI is Cinema Mode's phone hand-off, not an N-panel.

The pairing surface is custom-drawn C++ (`view3d_director_cinema_phone.cc`)
that can only see Python through two contracts: the `mixar.virtual_camera_*`
operator ids it invokes, and the `wm.mixar_virtual_camera_*` mirror it reads.
Neither end can be type-checked by a compiler, and a mismatch is a button
that silently does nothing — exactly what this surface replaced. So both
are pinned here, from the C++ source itself.
"""

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.virtual_camera.constants import QR_MATRIX_MAXLEN
from mixar.modules.virtual_camera.core import qr_encoder, wm_mirror
from mixar.modules.virtual_camera.core import runtime as runtime_mod

REPO = Path(__file__).resolve().parents[2]
MODULE = REPO / "src/scripts/mixar/modules/virtual_camera"
CINEMA = REPO / "src/source/blender/editors/space_view3d"
PHONE_CC = CINEMA / "view3d_director_cinema_phone.cc"
PROPS_PY = MODULE / "ui/properties/virtual_camera_props.py"
OPS_PY = MODULE / "ui/operators/server_ops.py"


def _phone_source() -> str:
    return PHONE_CC.read_text(encoding="utf-8")


# ---- operator contract ----------------------------------------------------


def _python_operator_ids() -> set[str]:
    """`MIXAR_OT_...` names as the C++ side spells them."""
    tree = ast.parse(OPS_PY.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name.startswith("MIXAR_OT_")
    }


def test_every_operator_the_card_invokes_exists():
    invoked = set(re.findall(r'"(MIXAR_OT_virtual_camera_\w+)"', _phone_source()))
    assert invoked, "the phone surface stopped invoking any operator"
    missing = invoked - _python_operator_ids()
    assert not missing, f"the Cinema surface invokes operators that do not exist: {missing}"


def test_the_strip_button_drives_the_toggle():
    source = _phone_source()
    body = source[source.index("void cinema_draw_phone_button"):]
    body = body[: body.index("\nvoid cinema_draw_phone_card")]
    assert '"MIXAR_OT_virtual_camera_toggle"' in body
    # It is a button, not paint: the INERT chrome it replaced is the bug.
    assert "cinema_op_button(" in body
    assert "cinema_qa_record(" in body, "new custom-drawn UI must export QA targets"


def test_the_card_offers_copy_repair_and_stop():
    source = _phone_source()
    for operator_id in (
        "MIXAR_OT_virtual_camera_copy_url",
        "MIXAR_OT_virtual_camera_new_pairing",
        "MIXAR_OT_virtual_camera_stop",
    ):
        assert f'"{operator_id}"' in source


def test_the_n_panel_is_gone():
    panels = list(MODULE.glob("ui/panels/*.py"))
    assert not panels, f"the sidebar panel came back: {panels}"
    assert "bl_category" not in OPS_PY.read_text(encoding="utf-8")


# ---- mirror contract ------------------------------------------------------


def _registered_property_names() -> set[str]:
    return set(re.findall(r"wm\.(mixar_virtual_camera_\w+)\s*=", PROPS_PY.read_text(encoding="utf-8")))


def test_every_mirror_property_the_surface_reads_is_registered():
    read = set(re.findall(r'"(mixar_virtual_camera_\w+)"', _phone_source()))
    assert read, "the phone surface stopped reading the mirror"
    missing = read - _registered_property_names()
    assert not missing, f"the Cinema surface reads unregistered properties: {missing}"


def test_the_property_module_lists_what_it_registers():
    source = PROPS_PY.read_text(encoding="utf-8")
    listed = set(re.findall(r'"(mixar_virtual_camera_\w+)",', source))
    assert _registered_property_names() <= listed, "unregister would leak a property"


def test_the_surface_only_reads_the_mirror():
    """A draw callback must never write RNA."""
    assert "RNA_property_boolean_set" not in _phone_source()
    assert "RNA_property_string_set" not in _phone_source()
    assert "RNA_property_int_set" not in _phone_source()


# ---- QR serialization -----------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_encoder_cache():
    wm_mirror._encoded_url = None
    wm_mirror._encoded_matrix = ("", 0)
    yield


def test_qr_modules_serializes_the_encoder_matrix():
    url = "https://192.168.1.42:8143/?t=abcdef0123456789"
    flat, size = wm_mirror.qr_modules(url)
    matrix = qr_encoder.encode(url)

    assert size == len(matrix)
    assert len(flat) == size * size
    assert set(flat) <= {"0", "1"}
    for row in range(size):
        assert flat[row * size:(row + 1) * size] == "".join(
            "1" if cell else "0" for cell in matrix[row]
        )


def test_qr_modules_fits_the_mirror_property():
    flat, _ = wm_mirror.qr_modules("https://192.168.1.42:8143/?t=abcdef0123456789")
    assert len(flat) <= QR_MATRIX_MAXLEN


def test_qr_modules_encodes_once_per_url(monkeypatch):
    calls = []
    real = qr_encoder.encode
    monkeypatch.setattr(
        qr_encoder, "encode", lambda url: (calls.append(url), real(url))[1]
    )
    for _ in range(5):
        wm_mirror.qr_modules("https://10.0.0.5:8143/?t=deadbeef")
    assert calls == ["https://10.0.0.5:8143/?t=deadbeef"]


def test_an_empty_url_clears_the_code():
    assert wm_mirror.qr_modules("") == ("", 0)


def test_an_unencodable_url_degrades_to_the_link(monkeypatch):
    def _boom(url):
        raise ValueError("too long for any version")

    monkeypatch.setattr(qr_encoder, "encode", _boom)
    assert wm_mirror.qr_modules("https://example.invalid/") == ("", 0)


# ---- mirror writes --------------------------------------------------------


class _FakeWM:
    def __init__(self):
        self.mixar_virtual_camera_running = False
        self.mixar_virtual_camera_connected = False
        self.mixar_virtual_camera_tls = False
        self.mixar_virtual_camera_url = ""
        self.mixar_virtual_camera_notice = ""
        self.mixar_virtual_camera_qr = ""
        self.mixar_virtual_camera_qr_size = 0


def _fake_runtime(**state):
    values = {
        "running": True,
        "tls": True,
        "phone_connected": False,
        "last_error": "",
        "url": "https://192.168.1.42:8143/?t=abcdef0123456789",
    }
    values.update(state)
    url = values.pop("url")
    server_state = SimpleNamespace(**values)
    server_state.url = url
    return SimpleNamespace(
        server=SimpleNamespace(state=server_state), last_error=""
    )


@pytest.fixture
def wm(monkeypatch):
    fake = _FakeWM()
    monkeypatch.setattr(
        wm_mirror.bpy, "context", SimpleNamespace(window_manager=fake), raising=False
    )
    return fake


def test_sync_publishes_the_pairing_state(wm):
    assert wm_mirror.sync(_fake_runtime()) is True

    assert wm.mixar_virtual_camera_running is True
    assert wm.mixar_virtual_camera_connected is False
    assert wm.mixar_virtual_camera_tls is True
    assert wm.mixar_virtual_camera_url.startswith("https://192.168.1.42")
    assert wm.mixar_virtual_camera_qr_size > 0
    assert len(wm.mixar_virtual_camera_qr) == wm.mixar_virtual_camera_qr_size ** 2


def test_sync_is_quiet_when_nothing_moved(wm):
    runtime = _fake_runtime()
    assert wm_mirror.sync(runtime) is True
    assert wm_mirror.sync(runtime) is False, "a 60 Hz pump must not redraw every tick"


def test_a_paired_phone_drops_the_code(wm):
    wm_mirror.sync(_fake_runtime())
    assert wm_mirror.sync(_fake_runtime(phone_connected=True)) is True

    assert wm.mixar_virtual_camera_connected is True
    assert wm.mixar_virtual_camera_qr == ""
    assert wm.mixar_virtual_camera_qr_size == 0


def test_a_stopped_server_publishes_no_url(wm):
    wm_mirror.sync(_fake_runtime())
    wm_mirror.sync(_fake_runtime(running=False))
    assert wm.mixar_virtual_camera_url == ""
    assert wm.mixar_virtual_camera_qr == ""


def test_the_notice_prefers_the_server_error(wm):
    runtime = _fake_runtime(last_error="Port 8143 is busy")
    runtime.last_error = "Viewport streaming unavailable"
    wm_mirror.sync(runtime)
    assert wm.mixar_virtual_camera_notice == "Port 8143 is busy"

    runtime = _fake_runtime()
    runtime.last_error = "Viewport streaming unavailable"
    wm_mirror.sync(runtime)
    assert wm.mixar_virtual_camera_notice == "Viewport streaming unavailable"


def test_clear_blanks_every_mirrored_value(wm):
    wm_mirror.sync(_fake_runtime())
    wm_mirror.clear()

    assert wm.mixar_virtual_camera_running is False
    assert wm.mixar_virtual_camera_connected is False
    assert wm.mixar_virtual_camera_url == ""
    assert wm.mixar_virtual_camera_qr == ""
    assert wm.mixar_virtual_camera_qr_size == 0


def test_sync_survives_unregistered_properties(monkeypatch):
    monkeypatch.setattr(
        wm_mirror.bpy, "context", SimpleNamespace(window_manager=object()), raising=False
    )
    assert wm_mirror.sync(_fake_runtime()) is False
    wm_mirror.clear()  # must not raise either


# ---- the mirror is timer-side, never draw-side ----------------------------


def _function_node(name: str) -> ast.AST:
    tree = ast.parse(Path(runtime_mod.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Runtime.{name} is gone — update this test")


@pytest.mark.parametrize("name", ["_service_capture", "_service_capture_inner"])
def test_the_draw_handler_never_writes_the_mirror(name):
    source = ast.unparse(_function_node(name))
    assert "wm_mirror" not in source, (
        "the capture handler runs inside a draw — an RNA write there is the "
        "handler-pattern violation CLAUDE.md bans"
    )
