# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Platform Detection Utilities

Common helper functions for detecting the operating system and
providing platform-specific values, such as keyboard shortcut modifiers.
"""

import sys


def is_macos() -> bool:
    """Check if the current platform is macOS.

    Returns:
        bool: True if running on macOS, False otherwise.
    """
    return sys.platform == "darwin"


def is_windows() -> bool:
    """Check if the current platform is Windows.

    Returns:
        bool: True if running on Windows, False otherwise.
    """
    return sys.platform.startswith("win")


def is_linux() -> bool:
    """Check if the current platform is Linux.

    Returns:
        bool: True if running on Linux, False otherwise.
    """
    return sys.platform.startswith("linux")


def get_command_modifier() -> str:
    """Get the platform-specific command modifier key name.

    Returns:
        str: "Cmd" on macOS, "Ctrl" on Windows/Linux.
    """
    return "Cmd" if is_macos() else "Ctrl"


def get_keymap_modifier() -> dict:
    """Get the keymap modifier dict for platform-specific command shortcuts.

    On macOS, uses 'oskey' (Cmd key).
    On Windows/Linux, uses 'ctrl' (Ctrl key).

    Returns:
        dict: A dict with either {'oskey': True} or {'ctrl': True}.
    """
    if is_macos():
        return {'oskey': True, 'ctrl': False}
    else:
        return {'ctrl': True, 'oskey': False}


def format_shortcut(key: str, use_command: bool = True, shift: bool = False, alt: bool = False) -> str:
    """Format a keyboard shortcut string for display in UI.

    Args:
        key: The key (e.g., "P", "C", "V").
        use_command: Whether to include the command modifier (Cmd/Ctrl).
        shift: Whether to include Shift modifier.
        alt: Whether to include Alt/Option modifier.

    Returns:
        str: Formatted shortcut string (e.g., "Ctrl+Shift+P" or "Cmd+P").
    """
    parts = []
    if use_command:
        parts.append(get_command_modifier())
    if shift:
        parts.append("Shift")
    if alt:
        parts.append("Alt" if not is_macos() else "Option")
    parts.append(key)
    return "+".join(parts)


def trigger_ui_redraw() -> None:
    """Trigger a redraw of all Blender windows and areas.

    Safe to schedule from background threads via bpy.app.timers.register().
    Returns None so the timer does not repeat.
    """
    try:
        import bpy
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass
    return None


def pid_alive(pid) -> bool:
    """Whether a process with this PID is still running.

    ``os.kill(pid, 0)`` is the POSIX probe. On Windows it can report a live
    process as dead, so the Win32 exit-code query is used there. An access
    refusal (Windows error 5, POSIX ``PermissionError``) means a live process
    owned by someone else. An unset PID is treated as alive: the caller cannot
    prove otherwise and must not tear down state it does not own.
    """
    if not pid:
        return True
    if is_windows():
        return _pid_alive_windows(int(pid))
    import os
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _pid_alive_windows(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    kernel32.GetExitCodeProcess.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == 5
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
