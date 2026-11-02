# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The context attached to a crash report: content-free, primitive values only.

``snapshot()`` runs on the main thread (it reads ``bpy``) and is cheap: a few
property reads, no I/O. It is taken by the heartbeat and written to the session
breadcrumb, so a crash found on the next launch carries the state of the session
that crashed (versions, GPU and driver, Cycles device, open tabs, the last agent
session / run id) rather than the state of the session that found it.
"""

from __future__ import annotations

import os
import platform

from ..constants import MAX_CONTEXT_STRING


def _short(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:MAX_CONTEXT_STRING] or None


def platform_name() -> str:
    system = platform.system().lower()
    return {"darwin": "darwin", "windows": "windows"}.get(system, "linux" if system == "linux" else system)


def os_version() -> str:
    system = platform.system()
    if system == "Darwin":
        return f"macOS {platform.mac_ver()[0]}".strip()
    if system == "Windows":
        return f"Windows {platform.release()} {platform.version()}".strip()
    return f"Linux {platform.release()}".strip()


def ram_gb() -> int | None:
    try:
        if hasattr(os, "sysconf"):
            return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3))
    except (ValueError, OSError, AttributeError):
        pass
    try:
        import ctypes

        class _Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = _Status()
        status.dwLength = ctypes.sizeof(_Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys / (1024 ** 3))
    except Exception:  # noqa: BLE001 - RAM is optional context
        pass
    return None


def static_context() -> dict:
    """Machine facts that never change in a session (no bpy)."""
    return {
        "platform": platform_name(),
        "os_version": os_version(),
        "cpu_arch": platform.machine() or None,
        "cpu_count": os.cpu_count(),
        "ram_gb": ram_gb(),
    }


def _gpu() -> dict:
    try:
        import gpu

        return {
            "gpu_vendor": _short(gpu.platform.vendor_get()),
            "gpu_renderer": _short(gpu.platform.renderer_get()),
            "gpu_driver": _short(gpu.platform.version_get()),
            "gpu_backend": _short(gpu.platform.backend_type_get()),
        }
    except Exception:  # noqa: BLE001 - no GPU context in background / early start-up
        return {}


def _cycles(context) -> dict:
    out = {}
    try:
        addon = context.preferences.addons.get("cycles")
        if addon is not None:
            out["cycles_device"] = _short(addon.preferences.compute_device_type)
    except Exception:  # noqa: BLE001
        pass
    try:
        scene = context.scene
        out["render_engine"] = _short(scene.render.engine)
        if getattr(scene, "cycles", None) is not None:
            out["cycles_scene_device"] = _short(scene.cycles.device)
    except Exception:  # noqa: BLE001
        pass
    return out


def _tabs_and_agent(context) -> dict:
    out = {}
    try:
        import bpy

        from ...render_coordinator.constants import is_internal_scene

        out["open_tabs"] = sum(1 for scene in bpy.data.scenes if not is_internal_scene(scene))
    except Exception:  # noqa: BLE001
        pass
    try:
        scene = context.scene
        out["agent_session_id"] = _short(getattr(scene, "mixie_session_id", "") or None)
        out["agent_run_id"] = _short(getattr(scene, "mixie_run_id", "") or None)
    except Exception:  # noqa: BLE001
        pass
    return out


def app_versions() -> dict:
    out = {}
    try:
        from mixar.config.config import get_config

        out["app_version"] = _short(get_config().get("app_info", {}).get("version"))
    except Exception:  # noqa: BLE001
        pass
    try:
        import bpy

        out["blender_version"] = ".".join(str(part) for part in bpy.app.version[:3])
    except Exception:  # noqa: BLE001
        pass
    try:
        from ...analytics import capture

        out["app_session_id"] = capture._app_session_id
    except Exception:  # noqa: BLE001
        pass
    return out


def snapshot(context) -> dict:
    """Live session context. Main thread only."""
    data = {}
    data.update(app_versions())
    data.update(_gpu())
    data.update(_cycles(context))
    data.update(_tabs_and_agent(context))
    return {key: value for key, value in data.items() if value is not None}
