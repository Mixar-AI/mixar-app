# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parsers for Blender's crash.txt (macOS, Windows, Linux) and macOS .ips reports."""

import textwrap

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


def test_render_worker_ips_is_a_worker_crash(fixture_text):
    # QA build: the background render worker (Mixar --background, parent Mixar)
    # died on EXC_BAD_ACCESS in a ctypes call.
    parsed = parse_ips(fixture_text("macos_worker_bad_access.ips.json"))
    assert parsed["kind"] == "worker_crash"
    assert parsed["frames"][0]["function"] == "_platform_strlen"


def test_app_ips_stays_an_app_crash(fixture_text):
    assert parse_ips(fixture_text("macos_abort.ips.json"))["kind"] == "native"


# -- Windows crash log: frame names -----------------------------------------


SYMBOLICATION = textwrap.dedent("""\
    # mixar symbolication v1
    mixar_version 4.3.9
    git_sha 0123456789abcdef0123456789abcdef01234567
    arch x86_64
    image base=0x7ff6c4000000 vmaddr=0x140000000 size=0x9000000 id=3f2504e04f8911d39a0c0305e82c33011 name=mixar.exe
    image base=0x7fff11910000 vmaddr=0x180000000 size=0x40000 id=- name=_ctypes.pyd
    image base=0x7fff01800000 vmaddr=0x180000000 size=0x400000 id=- name=python313.dll
    frame 0 0x00007fff1191ca80
    frame 1 0x00007fff018d57d0
    frame 2 0x00007ff6c512772a
    frame 3 0x00007fff018d4de0
    frame 4 0x00007fff019fc5a0
    frame 5 0x00007fff019fc330
    frame 6 0x00007ff6c4a00a44
    """)


def test_windows_frames_keep_the_names_the_crash_log_gives(fixture_text):
    parsed = parse_crash_txt(fixture_text("windows_ctypes_access_violation.crashlog"))
    assert parsed["crash_type"] == "EXCEPTION_ACCESS_VIOLATION"
    assert parsed["crash_module"] == "_ctypes.pyd"
    assert [(f["module"], f["function"]) for f in parsed["frames"]] == [
        ("_ctypes.pyd", "DllCanUnloadNow"),
        ("python313.dll", "PyObject_GenericGetAttrWithDict"),
        ("mixar.exe", ""),  # "Symbols not available" is no name
        ("python313.dll", "PyObject_GetAttr"),
        ("python313.dll", "PyEval_EvalFrameDefault"),
        ("python313.dll", "PyEval_EvalCode"),
    ]
    assert parsed["frames"][0]["offset"] == 0x7FFF1191CA80 - 0x7FFF11910000
    assert all("_address" not in frame for frame in parsed["frames"])


def test_windows_frames_rebuilt_from_the_symbolication_block_keep_their_names(fixture_text):
    text = fixture_text("windows_ctypes_access_violation.crashlog")
    parsed = parse_crash_txt(text.replace("# Python backtrace", SYMBOLICATION + "\n# Python backtrace"))
    functions = [frame["function"] for frame in parsed["frames"]]
    # The block's walk is longer than Blender's: its extra frame has no name.
    assert functions == ["DllCanUnloadNow", "PyObject_GenericGetAttrWithDict", "", "PyObject_GetAttr",
                         "PyEval_EvalFrameDefault", "PyEval_EvalCode", ""]
    assert parsed["frames"][0] == {"module": "_ctypes.pyd", "function": "DllCanUnloadNow",
                                   "offset": 0xCA80, "address": 0x7FFF1191CA80}
    assert parsed["frames"][-1]["module"] == "mixar.exe"


MAC_CHAINED = textwrap.dedent("""\
    # Blender 5.2.0, Commit date: 2026-07-13 15:20, Hash fbe6228777e7

    # backtrace
    0   Mixar                               0x0000000102a52578 _ZN7blender33BLI_system_backtrace_with_os_infoEP7__sFILEPKv + 56
    1   Mixar                               0x00000001021374b8 _ZN7blenderL19sig_handle_crash_fnEi + 368
    2   libsystem_platform.dylib            0x000000019bc1f744 _sigtramp + 56
    3   libsystem_pthread.dylib             0x000000019bc15888 pthread_kill + 296
    4   libsystem_c.dylib                   0x000000019bae2d30 raise + 32
    5   Mixar                               0x0000000103e00010 faulthandler_fatal_error + 400
    6   libsystem_platform.dylib            0x000000019bc1f744 _sigtramp + 56
    7   _ctypes.cpython-313-darwin.so       0x0000000105000100 _ctypes_string_at + 12
    8   Mixar                               0x0000000103f00200 _PyEval_EvalFrameDefault + 4000
    9   Mixar                               0x0000000102131b18 main + 920

    # mixar symbolication v1
    mixar_version 4.3.9
    git_sha 0123456789abcdef0123456789abcdef01234567
    arch arm64
    image base=0x102000000 vmaddr=0x100000000 size=0x7a1c000 id=8061b8de1ba9340fa6af312e3b71dbc5 name=Mixar
    frame 0 0x00000001021374b8
    frame 1 0x000000019bc1f744
    frame 2 0x000000019bc15888
    frame 3 0x000000019bae2d30
    frame 4 0x0000000103e00010
    frame 5 0x000000019bc1f744
    frame 6 0x0000000105000100
    frame 7 0x0000000103f00200
    frame 8 0x0000000102131b18

    # Python backtrace
    """)


def test_the_faulthandler_reraise_is_dropped_from_a_posix_stack():
    parsed = parse_crash_txt(MAC_CHAINED)
    functions = [frame["function"].split(" ")[0] for frame in parsed["frames"]]
    # As without faulthandler: Blender's handler, one trampoline, the fault.
    assert functions[:4] == ["_ZN7blender33BLI_system_backtrace_with_os_infoEP7__sFILEPKv",
                             "_ZN7blenderL19sig_handle_crash_fnEi", "_sigtramp", "_ctypes_string_at"]
    assert "faulthandler_fatal_error" not in functions and "raise" not in functions
    assert parsed["platform"] == "darwin" and parsed["is_mixar"]


def test_one_trampoline_or_no_reraise_keeps_the_stack(fixture_text):
    before = parse_crash_txt(fixture_text("macos_render.crashlog"))["frames"]
    assert [f["function"] for f in before][2] == "_sigtramp"
    # Two trampolines without a raise between them (a crash inside a signal
    # handler) is not faulthandler: nothing is dropped.
    text = MAC_CHAINED.replace("pthread_kill + 296", "some_handler + 296").replace("raise + 32", "other + 32")
    assert len(parse_crash_txt(text)["frames"]) == 10


def test_windows_block_frames_keep_the_walks_names(fixture_text):
    # Real Windows log (Mixar 5.2, ctypes access violation): Blender's walk prints
    # each named frame at its SYMBOL's start, the block every return address.
    parsed = parse_crash_txt(fixture_text("windows_ctypes_v1_named.crashlog"))
    names = [(frame["module"], frame["function"]) for frame in parsed["frames"][:4]]
    assert names == [("_ctypes.pyd", "DllCanUnloadNow"),
                     ("python313.dll", "PyObject_GenericGetAttrWithDict"),
                     ("python313.dll", "PyObject_GetAttr"),
                     ("python313.dll", "PyEval_EvalFrameDefault")]
    # The first nameless line ends Blender's walk; frames past it stay unnamed.
    assert parsed["frames"][14]["module"] == "mixar.exe" and parsed["frames"][14]["function"] == ""
    assert all(frame["function"] == "" for frame in parsed["frames"][15:])
