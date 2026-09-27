# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export telemetry audit (export contract §6): the File-menu completion
watcher, the initiated event's ``via``/``tool``, and every
``capture_export`` caller staying content-free and honest about success."""

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
MODULES = ROOT / "src/scripts/mixar/modules"


class _Fake:
    """Hashable attribute bag (real bpy IDs are set members in scene_counts)."""

    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def _events_module():
    from mixar.modules.common.analytics import export_events
    return export_events


def test_initiated_carries_via_and_tool():
    events = _events_module()
    with patch.object(events, "capture") as emit:
        events.capture_export_initiated(SimpleNamespace(), "glb", via="agent", tool="export_asset")
        events.capture_export_initiated(SimpleNamespace(), "OBJ")
    assert emit.call_args_list[0].args[:2] == (
        "export.initiated", {"format": "glb", "via": "agent", "tool": "export_asset"})
    assert emit.call_args_list[1].args[:2] == ("export.initiated", {"format": "OBJ", "via": "file_menu"})


def test_capture_export_extension_keyword_never_needs_a_path():
    events = _events_module()
    with patch.object(events, "capture") as emit:
        events.capture_export(SimpleNamespace(), export_format="fbx", success=False, extension=".FBX")
    assert emit.call_args.args[1] == {"format": "fbx", "success": False, "extension": "fbx"}


def test_find_completed_operator_scans_past_the_baseline():
    events = _events_module()
    old = SimpleNamespace(bl_idname="WM_OT_obj_export", use_selection=False)
    new = SimpleNamespace(bl_idname="WM_OT_obj_export", export_selected_objects=True)
    other = SimpleNamespace(bl_idname="OBJECT_OT_delete")
    assert events.find_completed_operator([old], "WM_OT_obj_export", 1) is None
    assert events.find_completed_operator([old, other, new], "WM_OT_obj_export", 1) is new
    # A trimmed list (wm.operators is bounded) falls back to a full scan.
    assert events.find_completed_operator([new], "WM_OT_obj_export", 5) is new
    assert events.registered_operator_idname("export_scene", "gltf") == "EXPORT_SCENE_OT_gltf"


def test_watch_native_completion_reports_settings_and_counts_once():
    events = _events_module()
    bpy = sys.modules["bpy"]
    registered = {}
    operators = [SimpleNamespace(bl_idname="WM_OT_obj_export")]
    material = _Fake(node_tree=SimpleNamespace(nodes=[SimpleNamespace(image=object())]))
    obj = _Fake(material_slots=[SimpleNamespace(material=material)], visible_get=lambda: True)
    context = SimpleNamespace(
        window_manager=SimpleNamespace(operators=operators),
        scene=SimpleNamespace(objects=[obj, obj]), selected_objects=[obj],
    )
    with (
        patch.object(bpy, "context", context),
        patch.object(bpy.app.timers, "register", lambda fn, first_interval=0: registered.setdefault("tick", fn)),
        patch.object(events, "capture") as emit,
    ):
        events.watch_native_completion("OBJ", "WM_OT_obj_export", via="file_menu")
        tick = registered["tick"]
        assert tick() == events.COMPLETION_POLL_SECONDS  # nothing new yet
        emit.assert_not_called()
        operators.append(SimpleNamespace(
            bl_idname="WM_OT_obj_export", export_selected_objects=True, apply_modifiers=True,
            export_materials=True, filepath="/Users/someone/Secret.obj"))
        assert tick() is None  # reported, timer stops
    event, properties = emit.call_args.args[:2]
    assert event == "export.completed"
    assert properties["format"] == "OBJ" and properties["success"] is True
    assert properties["via"] == "file_menu" and properties["export_selected_only"] is True
    assert properties["include_materials"] is True
    assert properties["object_count"] == 1 and properties["material_count"] == 1
    assert properties["texture_count"] == 1
    assert "filepath" not in properties and "Secret" not in repr(properties)


def test_watch_native_completion_gives_up_quietly():
    events = _events_module()
    bpy = sys.modules["bpy"]
    registered = {}
    context = SimpleNamespace(window_manager=SimpleNamespace(operators=[]))
    with (
        patch.object(bpy, "context", context),
        patch.object(bpy.app.timers, "register", lambda fn, first_interval=0: registered.setdefault("tick", fn)),
        patch.object(events, "capture") as emit,
        patch.object(events, "COMPLETION_GIVE_UP_SECONDS", -1.0),
    ):
        events.watch_native_completion("OBJ", "WM_OT_obj_export")
        assert registered["tick"]() is None
    emit.assert_not_called()


def test_file_menu_wrapper_arms_the_completion_watcher():
    from mixar.modules.common.ui.operators import native_export_ops
    calls = []
    with (
        patch.object(native_export_ops, "capture_export_initiated"),
        patch.object(native_export_ops, "watch_native_completion", lambda *a, **k: calls.append((a, k))),
        patch.object(native_export_ops, "_resolve_operator", return_value=lambda *a, **k: {"RUNNING_MODAL"}),
    ):
        native_export_ops._execute_export(SimpleNamespace(
            export_format="FBX", operator_namespace="export_scene", operator_name="fbx"), SimpleNamespace())
    assert calls == [(("FBX", "EXPORT_SCENE_OT_fbx"), {"via": "file_menu"})]
    calls.clear()
    with (
        patch.object(native_export_ops, "capture_export_initiated"),
        patch.object(native_export_ops, "watch_native_completion", lambda *a, **k: calls.append((a, k))),
        patch.object(native_export_ops, "_resolve_operator", return_value=lambda *a, **k: {"CANCELLED"}),
    ):
        native_export_ops._execute_export(SimpleNamespace(
            export_format="FBX", operator_namespace="export_scene", operator_name="fbx"), SimpleNamespace())
    assert calls == []


def test_normalized_settings_and_scene_counts_have_callers():
    # Both helpers were dead on develop; the File-menu watcher, the paint
    # exporters and the UV layout button now use them.
    users = [
        path for path in MODULES.rglob("*.py")
        if "analytics/export_events.py" not in str(path)
        and ("normalized_settings(" in path.read_text(encoding="utf-8")
             or "scene_counts(" in path.read_text(encoding="utf-8"))
    ]
    assert users, "normalized_settings / scene_counts have no caller"
    assert any("asset_export" in str(p) for p in users)
    watcher = (MODULES / "common/analytics/export_events.py").read_text(encoding="utf-8")
    body = watcher[watcher.index("def watch_native_completion"):]
    assert "normalized_settings(" in body and "scene_counts(" in body


def test_uv_layout_export_no_longer_claims_success_before_the_browser_closes():
    src = (MODULES / "uv_editor/ui/export/operators.py").read_text(encoding="utf-8")
    assert "success=True" not in src
    assert 'capture_export_initiated(context, "UV_LAYOUT", via="uv_editor")' in src
    assert 'watch_native_completion("UV_LAYOUT", "UV_OT_export_layout"' in src


def test_bake_export_events_drop_the_user_authored_channel_name():
    src = (MODULES / "paint/ui/bake/operators/bake_export_operators.py").read_text(encoding="utf-8")
    assert "channel_name=self.channel_name" not in src
    assert re.search(r"_capture_export\(context, \"BAKED_CHANNEL\", True, file_format=", src)


def test_paint_asset_exporters_treat_a_cancelled_operator_as_failure():
    for name in ("gltf", "fbx", "obj"):
        src = (MODULES / f"paint/ui/asset_export/{name}_export_operator.py").read_text(encoding="utf-8")
        assert "if 'FINISHED' not in status:" in src, name
        assert len(re.findall(rf"_capture_{name}_export\(context, \w+, (?:True|False)", src)) == 2, name


def _call_text(src: str, start: int) -> str:
    depth = 0
    for index in range(start, len(src)):
        if src[index] == "(":
            depth += 1
        elif src[index] == ")":
            depth -= 1
            if depth == 0:
                return src[start:index + 1]
    return src[start:]


def test_every_capture_export_caller_passes_success_explicitly():
    seen = 0
    for path in MODULES.rglob("*.py"):
        if "analytics/export_events.py" in str(path) or "/tests/" in str(path):
            continue
        src = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?<![\w.])capture_export\(", src):
            call = _call_text(src, match.start())
            seen += 1
            assert "success=" in call, f"{path}: {call}"
            # Names never ride along: only counts, settings and the extension.
            assert "name=" not in call and "names=" not in call, f"{path}: {call}"
    assert seen >= 5
