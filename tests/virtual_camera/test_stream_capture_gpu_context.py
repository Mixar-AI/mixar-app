# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The virtual camera's GPU work belongs to a draw callback, never the timer.

A ``bpy.app.timers`` tick is not a guaranteed-GPU moment: on Windows no GL
context is current on the main thread outside the draw loop, so creating a
``GPUOffScreen`` or calling ``draw_view3d`` there dereferences a null context
and kills the process with an access violation (reported from a real build:
"EXCEPTION_ACCESS_VIOLATION ... as soon as I connect"). It is not a Python
exception the runtime's failure counter can absorb, so the split has to be
pinned structurally as well as behaviourally.
"""

import ast
import inspect
from pathlib import Path

import pytest

from mixar.modules.virtual_camera.core import runtime as runtime_mod
from mixar.modules.virtual_camera.core import stream_capture

SOURCE_ROOT = Path(runtime_mod.__file__).parent


class _SpyCapture:
    """Stands in for ViewportCapture; every method here is GPU-touching."""

    def __init__(self, result=(b"rgba", 4, 2), error=None):
        self.captures = []
        self.frees = 0
        self._result = result
        self._error = error

    def capture(self, camera, short_edge, space, region):
        self.captures.append((camera, short_edge, space, region))
        if self._error is not None:
            raise self._error
        return self._result

    def free(self):
        self.frees += 1


class _SpyEncoder:
    def __init__(self):
        self.frames = []

    def submit(self, raw, width, height, quality):
        self.frames.append((raw, width, height, quality))


class _FakeSession:
    def __init__(self, **settings):
        self._settings = {"stream_fps": 30.0, "stream_quality": 2}
        self._settings.update(settings)

    def snapshot_settings(self):
        return dict(self._settings)


@pytest.fixture
def rt(monkeypatch):
    """A Runtime with every GPU-side and bpy-side collaborator spied."""
    monkeypatch.setattr(runtime_mod, "find_view3d", lambda: None)
    instance = runtime_mod.Runtime()
    instance.capture = _SpyCapture()
    instance._encoder = _SpyEncoder()
    instance.driver.camera = lambda: "CAMERA"
    return instance


# ---- behaviour ------------------------------------------------------------


def test_pump_stream_parks_a_request_without_touching_the_gpu(rt):
    rt._pump_stream(_FakeSession(), now=1000.0)

    assert rt.capture.captures == [], "the timer must not reach the GPU"
    assert rt._frame_request is not None
    short_edge, quality = rt._frame_request
    assert quality == 2 and short_edge > 0


def test_pump_stream_honours_the_fps_budget(rt):
    rt._pump_stream(_FakeSession(), now=1000.0)
    rt._frame_request = None
    rt._pump_stream(_FakeSession(), now=1000.001)
    assert rt._frame_request is None

    rt._pump_stream(_FakeSession(), now=1000.5)
    assert rt._frame_request is not None


def test_pump_stream_is_off_when_the_phone_asks_for_no_stream(rt):
    rt._pump_stream(_FakeSession(stream_fps=0), now=1000.0)
    assert rt._frame_request is None


def test_draw_handler_does_the_capture_and_feeds_the_encoder(rt, monkeypatch):
    monkeypatch.setattr(runtime_mod.bpy.context, "space_data", "SPACE", raising=False)
    monkeypatch.setattr(runtime_mod.bpy.context, "region", "REGION", raising=False)
    rt._pump_stream(_FakeSession(), now=1000.0)
    short_edge, _ = rt._frame_request

    rt._service_capture()

    assert rt.capture.captures == [("CAMERA", short_edge, "SPACE", "REGION")]
    assert rt._encoder.frames == [(b"rgba", 4, 2, 2)]
    assert rt._frame_request is None, "a serviced request must not repeat"


def test_draw_handler_is_a_no_op_without_a_request(rt):
    rt._service_capture()
    assert rt.capture.captures == []
    assert rt._encoder.frames == []


def test_draw_handler_never_raises_into_the_viewport(rt, monkeypatch):
    monkeypatch.setattr(runtime_mod.bpy.context, "space_data", "SPACE", raising=False)
    monkeypatch.setattr(runtime_mod.bpy.context, "region", "REGION", raising=False)
    rt.capture = _SpyCapture(error=RuntimeError("no GPU context"))
    rt._pump_stream(_FakeSession(), now=1000.0)

    rt._service_capture()  # must not propagate

    assert rt._capture_failures == 1
    assert rt.capture_disabled is False


def test_repeated_capture_failure_disables_streaming_not_control(rt, monkeypatch):
    monkeypatch.setattr(runtime_mod.bpy.context, "space_data", "SPACE", raising=False)
    monkeypatch.setattr(runtime_mod.bpy.context, "region", "REGION", raising=False)
    rt.capture = _SpyCapture(error=RuntimeError("no GPU context"))
    rt.server.send_json = lambda payload: None

    for i in range(runtime_mod._CAPTURE_FAILURE_LIMIT):
        rt._last_capture = 0.0
        rt._pump_stream(_FakeSession(), now=1000.0 + i)
        rt._service_capture()

    assert rt.capture_disabled is True
    assert "camera control still active" in rt.last_error
    rt._pump_stream(_FakeSession(), now=2000.0)
    assert rt._frame_request is None


def test_stop_frees_the_offscreen_from_a_draw_not_the_timer(rt):
    rt._request_capture_release()
    assert rt.capture.frees == 0, "free() is a GPU call — not on the timer"
    assert rt._release_capture is True

    rt._service_capture()

    assert rt.capture.frees == 1
    assert rt._release_capture is False


def test_release_wins_over_a_pending_frame(rt):
    rt._pump_stream(_FakeSession(), now=1000.0)
    rt._request_capture_release()
    rt._service_capture()

    assert rt.capture.captures == []
    assert rt.capture.frees == 1


# ---- structure ------------------------------------------------------------


def _function_node(name: str) -> ast.AST:
    tree = ast.parse(Path(runtime_mod.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Runtime.{name} is gone — update this test")


def _touches_capture(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Attribute)
                and sub.value.attr == "capture"
                and isinstance(sub.value.value, ast.Name)
                and sub.value.value.id == "self"):
            return True
    return False


@pytest.mark.parametrize(
    "name", ["_tick", "_tick_inner", "_pump_stream", "start", "stop"]
)
def test_timer_and_lifecycle_paths_never_touch_the_gpu(name):
    assert not _touches_capture(_function_node(name)), (
        f"Runtime.{name} runs outside a draw callback — it must only set "
        "_frame_request / _release_capture, never call self.capture.*"
    )


def test_only_the_draw_service_touches_the_gpu():
    tree = ast.parse(Path(runtime_mod.__file__).read_text(encoding="utf-8"))
    owners = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _touches_capture(node)
    }
    assert owners == {"_service_capture_inner"}, owners


def test_the_handler_is_a_view3d_post_pixel_callback():
    source = inspect.getsource(runtime_mod.Runtime._ensure_draw_handler)
    assert "SpaceView3D.draw_handler_add" in source
    assert "'WINDOW'" in source and "'POST_PIXEL'" in source
    assert "self._service_capture" in source


def test_the_handler_never_removes_itself():
    for name in ("_service_capture", "_service_capture_inner"):
        assert "draw_handler_remove" not in inspect.getsource(
            getattr(runtime_mod.Runtime, name)
        ), "removing a draw handler from inside its own callback is a UAF"


def test_capture_restores_the_region_framebuffer_state():
    """CLAUDE.md: a DRW offscreen pass resets the region viewport/scissor, and
    this one runs while the region is mid-draw."""
    source = inspect.getsource(stream_capture.ViewportCapture.capture)
    assert "viewport_get" in source and "scissor_get" in source
    tail = source[source.index("finally:"):]
    assert "viewport_set" in tail and "scissor_set" in tail
