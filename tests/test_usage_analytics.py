# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from types import SimpleNamespace
from unittest.mock import patch
import sys
from types import ModuleType

from mixar.modules.common.analytics import instrument_operator_classes
from mixar.modules.common.analytics.capture import capture
from mixar.modules.common.analytics.export_events import capture_export, normalized_settings
from mixar.modules.common.analytics import bubble_events


# Queue imports reach the auth module; the standalone stubbed-bpy environment
# intentionally does not install the platform keyring dependency.
if "keyring" not in sys.modules:
    sys.modules["keyring"] = ModuleType("keyring")


def _analytics_module():
    handlers = ModuleType("bpy.app.handlers")
    handlers.persistent = lambda fn: fn
    with patch.dict(sys.modules, {"bpy.app.handlers": handlers}):
        sys.modules.pop("mixar.bootstrap.analytics_module", None)
        from mixar.bootstrap import analytics_module
    return analytics_module


def test_operator_wrapper_records_identity_not_arguments() -> None:
    class DemoOperator:
        bl_idname = "mixar.demo"

        def execute(self, context):
            self.prompt = "must-not-be-captured"
            return {"FINISHED"}

    with patch("mixar.modules.common.analytics.capture.capture") as emit:
        instrument_operator_classes((DemoOperator,))
        result = DemoOperator().execute(SimpleNamespace())

    assert result == {"FINISHED"}
    properties = emit.call_args.args[1]
    assert properties == {"operator": "mixar.demo", "success": True}


def test_operator_wrapper_skips_ignored_operator_and_wraps_normal_one() -> None:
    class IgnoredOperator:
        bl_idname = "notification.toast_hover"

        def execute(self, context):
            return {"FINISHED"}

    class NormalOperator:
        bl_idname = "mixar.normal_action"

        def execute(self, context):
            return {"FINISHED"}

    ignored_execute = IgnoredOperator.execute
    normal_execute = NormalOperator.execute
    instrument_operator_classes((IgnoredOperator, NormalOperator))

    assert IgnoredOperator.execute is ignored_execute
    assert not hasattr(IgnoredOperator, "__mixar_analytics_wrapped__")
    assert NormalOperator.execute is not normal_execute
    assert NormalOperator.__mixar_analytics_wrapped__ is True


def test_wrapped_methods_keep_exact_rna_signatures() -> None:
    """register_class validates each method's positional-argument count.

    Regression: a ``*args`` shim (2 positional args) registered fine for
    ``execute`` but was rejected for ``invoke`` (expects 3), which silently
    unregistered every invoke-only modal operator — Director's Navigate and
    Explore drew as disabled buttons.
    """
    import inspect

    class ModalOperator:
        bl_idname = "mixar.modal_action"

        def invoke(self, context, event):
            return {"RUNNING_MODAL"}

    class SimpleOperator:
        bl_idname = "mixar.simple_action"

        def execute(self, context):
            return {"FINISHED"}

    instrument_operator_classes((ModalOperator, SimpleOperator))

    varargs = inspect.CO_VARARGS | inspect.CO_VARKEYWORDS
    assert ModalOperator.invoke.__code__.co_argcount == 3
    assert not ModalOperator.invoke.__code__.co_flags & varargs
    assert SimpleOperator.execute.__code__.co_argcount == 2
    assert not SimpleOperator.execute.__code__.co_flags & varargs

    with patch("mixar.modules.common.analytics.capture.capture") as emit:
        result = ModalOperator().invoke(SimpleNamespace(), SimpleNamespace())
    assert result == {"RUNNING_MODAL"}
    assert emit.call_args.args[1] == {
        "operator": "mixar.modal_action",
        "success": True,
    }


def test_native_export_wrapper_captures_initiated_without_filepath() -> None:
    from mixar.modules.common.ui.operators import native_export_ops
    from mixar.modules.common.analytics import export_events

    delegated = {"RUNNING_MODAL"}
    invoked = []

    def _fake_exporter(*args, **kwargs):
        invoked.append(args)
        return delegated

    # Patch the resolver, not bpy.ops: bpy.ops.wm is a dynamic submodule that
    # ignores attribute patching, so patching it reaches the REAL exporter
    # under a real Blender and only appears to pass against a mocked bpy.
    with (
        patch.object(export_events, "capture") as emit,
        patch.object(native_export_ops, "_resolve_operator", return_value=_fake_exporter),
    ):
        result = native_export_ops._execute_export(SimpleNamespace(
            export_format="OBJ", operator_namespace="wm", operator_name="obj_export"),
            SimpleNamespace())

    assert result == delegated
    emit.assert_called_once()
    assert emit.call_args.args[:2] == (
        "export.initiated", {"format": "OBJ", "via": "file_menu"})
    assert "filepath" not in emit.call_args.args[1]
    assert invoked == [('INVOKE_DEFAULT',)]


def test_native_export_wrapper_delegates_when_telemetry_raises() -> None:
    from mixar.modules.common.ui.operators import native_export_ops

    delegated = {"RUNNING_MODAL"}
    with (
        patch.object(native_export_ops, "capture_export_initiated", side_effect=RuntimeError("boom")),
        patch.object(native_export_ops, "_resolve_operator",
                     return_value=lambda *a, **k: delegated),
    ):
        result = native_export_ops._execute_export(SimpleNamespace(
            export_format="OBJ", operator_namespace="wm", operator_name="obj_export"),
            SimpleNamespace())

    assert result == delegated


def test_background_runs_are_suppressed() -> None:
    """Mixar spawns --background children (create_model sandboxes) that
    authenticate from the same keyring. Without suppression each one reports a
    zero-duration session and corrupts production session metrics."""
    import importlib

    # The package re-exports the capture *function*, so import the module.
    capture_module = importlib.import_module("mixar.modules.common.analytics.capture")

    original = capture_module._suppressed
    try:
        capture_module.suppress()
        with (
            patch.object(capture_module, "is_enabled", return_value=True),
            patch.object(capture_module, "_has_auth_token", return_value=True),
            patch.object(capture_module._events, "put_nowait") as enqueue,
        ):
            capture_module.capture("app.session_ended", {"reason": "quit"})
        enqueue.assert_not_called()
    finally:
        capture_module._suppressed = original


def test_capture_drops_events_without_authentication() -> None:
    with (
        patch("mixar.modules.common.analytics.capture.is_enabled", return_value=True),
        patch("mixar.modules.common.analytics.capture._has_auth_token", return_value=False),
        patch("mixar.modules.common.analytics.capture._events.put_nowait") as enqueue,
    ):
        capture("product.operator", {"operator": "mixar.demo"})
    enqueue.assert_not_called()


def test_export_normalization_and_path_privacy() -> None:
    gltf = SimpleNamespace(use_selection=True, export_apply=False,
        export_materials="EXPORT", export_animations=True,
        export_image_format="WEBP", export_draco_mesh_compression_enable=True)
    obj = SimpleNamespace(export_selected_objects=False, apply_modifiers=True,
        export_materials=False, export_animation=False, global_scale=2.0,
        forward_axis="NEGATIVE_Z", up_axis="Y", path_mode="COPY")
    fbx = SimpleNamespace(use_selection=True, use_mesh_modifiers=True,
        bake_anim=False, embed_textures=True, global_scale=1.0,
        axis_forward="-Z", axis_up="Y", path_mode="AUTO")
    assert normalized_settings("GLTF", gltf)["include_materials"] is True
    assert normalized_settings("GLTF", gltf)["include_textures"] is True
    assert normalized_settings("OBJ", obj)["include_materials"] is False
    assert normalized_settings("FBX", fbx)["forward_axis"] == "-Z"
    with patch("mixar.modules.common.analytics.export_events.capture") as emit:
        capture_export(SimpleNamespace(), export_format="GLTF", success=True,
            filepath="/private/user/Secret Asset.GLB",
            extra=normalized_settings("GLTF", gltf))
    properties = emit.call_args.args[1]
    assert properties["extension"] == "glb"
    assert "filepath" not in properties
    assert "Secret Asset" not in repr(properties)


def test_panel_poll_seeds_switches_and_suppresses_programmatic_changes() -> None:
    analytics_module = _analytics_module()
    region = SimpleNamespace(type="UI", active_panel_category="Image Gen", as_pointer=lambda: 7)
    space = SimpleNamespace(mixie_mode="MOODBOARD", show_region_ui=True)
    area = SimpleNamespace(type="MIXIE", spaces=SimpleNamespace(active=space), regions=[region])
    context = SimpleNamespace(window_manager=SimpleNamespace(
        windows=[SimpleNamespace(screen=SimpleNamespace(areas=[area]))]))
    analytics_module._last_panels.clear()
    analytics_module._last_sidebars.clear()
    analytics_module._suppressed_panels.clear()
    # patch.object on analytics_module.time patches the SHARED stdlib time
    # module, so draft_events' panel-entry bookkeeping consumes values too:
    # scan(now, entered), scan(now, entered), note_programmatic, scan(now, entered).
    with (patch.object(analytics_module.bpy, "context", context),
          patch.object(analytics_module, "capture") as emit,
          patch.object(analytics_module.time, "monotonic",
                       side_effect=[10.0, 10.0, 12.34, 12.34, 14.0, 14.0, 14.0])):
        analytics_module._scan_panels()
        emit.assert_not_called()
        region.active_panel_category = "Model Gen"
        analytics_module._scan_panels()
        assert emit.call_args.args[1] == {"panel": "Model Gen",
            "previous_panel": "Image Gen", "previous_duration_seconds": 2.3}
        emit.reset_mock()
        analytics_module.note_programmatic_panel_change(region, "Queue")
        region.active_panel_category = "Queue"
        analytics_module._scan_panels()
        emit.assert_not_called()


def test_session_ended_emits_once_with_duration() -> None:
    analytics_module = _analytics_module()
    analytics_module._session_started = 10.0
    analytics_module._session_ended = False
    with (patch.object(analytics_module.time, "monotonic", return_value=15.9),
          patch.object(analytics_module, "capture") as emit,
          patch.object(analytics_module, "events_dropped", return_value=3),
          patch.object(analytics_module, "cached_context_properties", return_value={})):
        analytics_module.capture_session_ended("quit")
        analytics_module.capture_session_ended("atexit")
    emit.assert_called_once()
    assert emit.call_args.args[1]["session_duration_seconds"] == 5
    assert emit.call_args.args[1]["reason"] == "quit"


def test_bubble_state_deduplicates_consecutive_state() -> None:
    bubble_events.reset_bubble_state()
    with patch.object(bubble_events, "capture") as emit:
        bubble_events.capture_bubble_state("minimized")
        bubble_events.capture_bubble_state("minimized")
        bubble_events.capture_bubble_state("maximized")
    assert [call.args[1]["state"] for call in emit.call_args_list] == [
        "minimized", "maximized"]


def test_programmatic_bubble_change_does_not_swallow_next_user_event() -> None:
    """A product-driven restore must not make the user's next minimise look
    like a repeat of the state we last reported."""
    bubble_events.reset_bubble_state()
    with patch.object(bubble_events, "capture") as emit:
        bubble_events.capture_bubble_state("minimized")
        # Splash / pre-focus restore: real state changes, nothing is reported.
        bubble_events.note_programmatic_bubble_state("maximized")
        assert [c.args[1]["state"] for c in emit.call_args_list] == ["minimized"]
        # The user now minimises again — that is a genuine event.
        bubble_events.capture_bubble_state("minimized")
    assert [c.args[1]["state"] for c in emit.call_args_list] == [
        "minimized", "minimized"]


def test_privacy_panel_lives_in_preferences_system_section() -> None:
    """Consent must stay where users conventionally look to opt out.

    Source-level on purpose: with the stubbed bpy, Panel subclasses are
    MagicMocks, so class attributes cannot be asserted through import.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src/scripts/mixar/modules/common/ui/panels/privacy_panel.py"
    ).read_text(encoding="utf-8")
    assert "bl_space_type = 'PREFERENCES'" in source
    assert "bl_region_type = 'WINDOW'" in source
    assert 'bl_context = "system"' in source
    assert "mixar_share_usage_data" in source
    assert "https://www.mixar.app/legal/privacy-policy" in source


def test_modal_operator_start_counts_as_success() -> None:
    """Modal operators are wrapped on invoke and legitimately return
    RUNNING_MODAL; reporting them as failures poisons success rates."""
    from mixar.modules.common.analytics.capture import _successful

    assert _successful({"FINISHED"}) is True
    assert _successful({"RUNNING_MODAL"}) is True
    assert _successful({"CANCELLED"}) is False
    assert _successful("FINISHED") is False
