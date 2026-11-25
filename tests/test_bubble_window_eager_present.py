# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins the Windows-only skip of the eager first present for agent bubble windows
(#2158) in `src/source/blender/windowmanager/intern/wm_window.cc`.

`wm_window_ghostwindow_add` clears and presents every new window once before its
screens draw. Under NVIDIA's "Prefer layered on DXGI swapchain" Vulkan present
(Optimus laptops) that first present of the owned island/pill popup crashed
nvoglv64.dll. On Windows the island and pill skip it, still set the DPI, end the
GPU render and return; their first real draw presents. Other windows and other
platforms keep the upstream clear."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WM_WINDOW = ROOT / "src/source/blender/windowmanager/intern/wm_window.cc"


def _ghostwindow_add() -> str:
    text = WM_WINDOW.read_text(encoding="utf-8")
    start = text.index("static void wm_window_ghostwindow_add(")
    return text[start:text.index("\n}\n", start) + 3]


def _code(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _win32_skip_block(body: str) -> str:
    match = re.search(
        r"#ifdef _WIN32\n(?P<block>\s*if \(Mixar_window_has_agent_bubble\(win\)\) \{.*?)#endif",
        _code(body),
        re.S,
    )
    assert match, "the bubble skip must be guarded by #ifdef _WIN32 only"
    return match.group("block")


def test_bubble_skip_is_windows_only_and_returns_before_the_eager_present():
    body = _ghostwindow_add()
    block = _win32_skip_block(body)
    assert re.search(
        r"WM_window_dpi_set_userdef\(win\);\s*GPU_render_end\(\);\s*return;", block
    ), "the skip must still set the DPI and end the GPU render before returning"

    code = _code(body)
    skip = code.index("Mixar_window_has_agent_bubble(win)")
    acquire = code.index("wm_window_swap_buffer_acquire(win)")
    assert skip < acquire, "the skip must precede the eager acquire/clear/release"
    assert code.count("wm_window_swap_buffer_acquire(win)") == 1
    assert code.count("wm_window_swap_buffer_release(win)") == 1


def test_non_bubble_windows_keep_the_upstream_clear_and_dpi():
    code = _code(_ghostwindow_add())
    tail = code[code.index("wm_window_swap_buffer_acquire(win)"):]
    assert re.search(
        r"wm_window_swap_buffer_acquire\(win\);\s*GPU_clear_color\(.*?\);\s*"
        r"WM_window_dpi_set_userdef\(win\);",
        tail,
        re.S,
    ), "the eager clear path (and its DPI call) must stay as upstream"
    assert "wm_window_swap_buffer_release(win)" in tail


def test_skip_is_not_on_other_platforms():
    code = _code(_ghostwindow_add())
    assert code.count("Mixar_window_has_agent_bubble(") == 1
    for guard in ("#ifdef __APPLE__", "#ifdef __linux__", "#ifndef _WIN32", "#else"):
        for match in re.finditer(re.escape(guard), code):
            following = code[match.end():match.end() + 400].split("#endif")[0]
            assert "Mixar_window_has_agent_bubble" not in following, guard
