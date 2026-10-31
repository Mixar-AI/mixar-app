# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parsers for Blender's crash.txt (macOS, Windows, Linux) and macOS .ips reports."""

from mixar.modules.common.crash_reports.core.parse_crash_txt import parse_crash_txt
from mixar.modules.common.crash_reports.core.parse_ips import parse_ips


def test_macos_render_crash(fixture_text):
    parsed = parse_crash_txt(fixture_text("macos_render.crashlog"))
    assert parsed["is_mixar"] and parsed["platform"] == "darwin"
    assert parsed["blender_version"] == "5.2.0" and parsed["build_hash"] == "fbe6228777e7"
    assert parsed["crash_type"] == "SIGSEGV"
    assert parsed["thread"] == "job"
    functions = [frame["function"] for frame in parsed["frames"]]
    assert functions[3] == "_ZN7blender22DEG_id_type_any_existsEPKNS_9DepsgraphEs"
    assert parsed["frames"][3] == {
        "module": "Mixar", "function": "_ZN7blender22DEG_id_type_any_existsEPKNS_9DepsgraphEs", "offset": 24,
        "address": 0x000000010568127C,
    }
    # An old log has no symbolication block: nothing invented.
    assert parsed["images"] == [] and parsed["app_version"] is None and parsed["git_sha"] is None
    assert parsed["frames"][2]["module"] == "libsystem_platform.dylib"
    assert parsed["operators"][-1] == "bpy.ops.mixie.imagegen_generate"
    assert "bpy.ops.mixie_chat.send_message" in parsed["operators"]
    # Python frames: innermost first, in-app path only.
    assert parsed["python_frames"][0] == {
        "file": "mixar/modules/space_mixie_chat/core/preview_render.py", "function": "render_preview", "line": 212,
    }


def test_operators_carry_no_arguments(fixture_text):
    parsed = parse_crash_txt(fixture_text("macos_render.crashlog"))
    assert all("(" not in name and "/" not in name for name in parsed["operators"])


def test_vanilla_blender_crash_is_not_mixars(fixture_text):
    parsed = parse_crash_txt(fixture_text("upstream_blender.crashlog"))
    assert parsed is not None and parsed["is_mixar"] is False
    assert parsed["blender_version"] == "5.1.0"


def test_windows_access_violation(fixture_text):
    parsed = parse_crash_txt(fixture_text("windows_access_violation.crashlog"))
    assert parsed["is_mixar"] and parsed["platform"] == "windows"
    assert parsed["crash_type"] == "EXCEPTION_ACCESS_VIOLATION"
    assert parsed["crash_module"] == "Mixar.exe"
    # Symbols not available: the frame is the module plus its offset (RVA).
    assert parsed["frames"] == [{"module": "Mixar.exe", "function": "", "offset": 0x1D2C3D4}]
    assert parsed["operators"] == [
        "bpy.ops.wm.open_mainfile", "bpy.ops.mixie_chat.send_message", "bpy.ops.mixie_chat.agent_preview_render",
    ]
    assert [f["file"] for f in parsed["python_frames"]] == [
        "mixar/modules/space_mixie_chat/core/preview_render.py",
        "mixar/modules/space_mixie_chat/core/executor.py",
    ]


def test_linux_segv(fixture_text):
    parsed = parse_crash_txt(fixture_text("linux_segv.crashlog"))
    assert parsed["is_mixar"] and parsed["platform"] == "linux"
    assert parsed["frames"][1] == {"module": "Mixar", "function": "", "offset": 0x1D3E0F1, "address": 0x5631A3A3E0F1}
    assert parsed["frames"][3]["function"] == "_ZN7blender3bke17mesh_calc_normalsEPNS_4MeshE"
    assert parsed["frames"][2]["module"] == "libc.so.6"
    assert parsed["thread"] == "main"
    assert all("/" not in frame["module"] for frame in parsed["frames"])


def test_text_without_a_backtrace_is_not_a_crash_log():
    assert parse_crash_txt("") is None
    assert parse_crash_txt("hello\nworld") is None


def test_macos_abort_report(fixture_text):
    parsed = parse_ips(fixture_text("macos_abort.ips.json"))
    assert parsed["crash_type"] == "SIGABRT"
    assert parsed["app_version"] == "4.3.5" and parsed["os_version"].startswith("macOS")
    assert parsed["thread"] == "main"
    functions = [frame["function"] for frame in parsed["frames"]]
    assert "aud::FFMPEGReader::~FFMPEGReader()" in functions
    assert parsed["frames"][0]["module"] == "libsystem_kernel.dylib"
    assert parsed["crashed_at"].startswith("2026-10-23T15:24:01")
    assert parsed["report_key"]


def test_macos_segv_report_is_skipped_because_crash_txt_has_it(fixture_text):
    assert parse_ips(fixture_text("macos_segv_handled.ips.json")) is None


def test_ips_from_another_app_or_garbage_is_skipped():
    assert parse_ips('{"app_name": "Blender"}\n{}') is None
    assert parse_ips("not json") is None


def test_symbolication_block_on_macos(fixture_text):
    parsed = parse_crash_txt(fixture_text("macos_render_v1.crashlog"))
    assert parsed["app_version"] == "4.3.8" and parsed["git_sha"] == "0123456789abcdef0123456789abcdef01234567"
    assert parsed["arch"] == "arm64"
    assert parsed["images"][0] == {
        "name": "Mixar", "id": "8061b8de1ba9340fa6af312e3b71dbc5",
        "base": 0x104A4C000, "vmaddr": 0x100000000, "size": 0x7A1C000,
    }
    # macOS keeps the named frames; each carries its absolute address.
    assert parsed["frames"][3]["function"].startswith("_ZN7blender22DEG_id_type_any_exists")
    assert parsed["frames"][3]["address"] == 0x000000010568127C


def test_symbolication_block_rebuilds_windows_frames(fixture_text):
    parsed = parse_crash_txt(fixture_text("windows_access_violation_v1.crashlog"))
    assert parsed["app_version"] == "4.3.8"
    assert [frame["module"] for frame in parsed["frames"]] == ["Mixar.exe", "Mixar.exe", "nvoglv64.dll", "Mixar.exe"]
    assert parsed["frames"][0] == {"module": "Mixar.exe", "function": "", "offset": 0x1D2C3D4, "address": 0x7FF6A1D2C3D4}
    assert parsed["images"][0]["id"] == "3f2504e04f8911d39a0c0305e82c33011"
    assert all("/" not in image["name"] and "\\" not in image["name"] for image in parsed["images"])
