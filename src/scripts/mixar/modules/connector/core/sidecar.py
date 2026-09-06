# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Loopback HTTP sidecar so the hub can drive Mixar without going through bpy UI."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from mixar.config.logging_config import get_logger

from .constants import DEFAULT_SIDECAR_PORT
from .protocol import parse_export_body

logger = get_logger(__name__)

_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None
_port = DEFAULT_SIDECAR_PORT


def _run_on_main(fn):
    from mixar.modules.space_mixie_chat.core.main_thread_executor import run_on_main_thread

    event = threading.Event()
    box: dict[str, Any] = {}

    def _job():
        try:
            box["value"] = fn()
            box["ok"] = True
        except Exception as exc:
            box["error"] = str(exc)
            box["ok"] = False
        event.set()

    run_on_main_thread(_job)
    if not event.wait(timeout=90):
        raise TimeoutError("Mixar main thread timed out")
    if not box.get("ok"):
        raise RuntimeError(box.get("error") or "Mixar operator failed")
    return box.get("value")


def _instance() -> tuple[str, bool]:
    """Instance id + connection state, read on the MAIN thread.

    ``manager.instance_id`` reads ``bpy.context.window_manager`` and, on first
    access, WRITES ``wm.mixie_instance_id``; this runs on an HTTP handler
    thread, so it goes through ``_run_on_main`` like every other bpy touch in
    the sidecar.
    """
    instance_id = ""
    connected = False

    def _read():
        from mixar.modules.space_mixie_chat.core.connection_manager import (
            get_connection_manager,
        )

        manager = get_connection_manager()
        return manager.instance_id or "", bool(manager.is_connected)

    try:
        instance_id, connected = _run_on_main(_read)
    except Exception as exc:
        logger.debug("connector sidecar instance: %s", exc)
    return instance_id, connected


def _health() -> dict[str, Any]:
    instance_id, connected = _instance()

    def _lite():
        import bpy

        scene = bpy.context.scene
        return {"scene_name": scene.name, "object_count": len(scene.objects)}

    scene = _run_on_main(_lite)
    return {
        "ok": True,
        "app": "mixar",
        "sidecar": "connector",
        "port": _port,
        "instance_id": instance_id,
        "agent_connected": connected,
        "scene": scene,
        "scene_name": scene.get("scene_name", ""),
        "object_count": scene.get("object_count", 0),
    }


def _moodboard() -> dict[str, Any]:
    from . import scene_snapshot

    return _run_on_main(scene_snapshot.moodboard_snapshot)


def _scene() -> dict[str, Any]:
    from . import scene_snapshot

    return _run_on_main(scene_snapshot.scene_snapshot)


def _export(payload: dict[str, Any]) -> dict[str, Any]:
    from .unreal_export import export_scene_for_unreal

    result = _run_on_main(
        lambda: export_scene_for_unreal(
            payload["format"], payload.get("object_names") or None
        )
    )
    instance_id, _connected = _instance()
    result["instance_id"] = instance_id
    return result


def _prompt(payload: dict[str, Any]) -> dict[str, Any]:
    message = str(payload.get("prompt") or payload.get("message") or "").strip()
    if not message:
        raise ValueError("prompt is required")

    def _queue():
        import bpy

        scene = bpy.context.scene
        if hasattr(scene, "mixie_chat_input"):
            scene.mixie_chat_input = message
        try:
            if hasattr(bpy.ops, "mixie_chat") and hasattr(bpy.ops.mixie_chat, "send_message"):
                bpy.ops.mixie_chat.send_message()
                return {"queued": True, "via": "mixie_chat.send_message"}
        except Exception as exc:
            return {"queued": False, "error": str(exc), "prompt": message}
        return {"queued": False, "prompt": message, "note": "paste into Mixie chat"}

    return _run_on_main(_queue)


def _moodboard_preview(index: int) -> bytes:
    from . import scene_snapshot

    return _run_on_main(lambda: scene_snapshot.capture_moodboard_preview(index))


def _viewport() -> bytes:
    from . import scene_snapshot

    return _run_on_main(scene_snapshot.capture_viewport_png)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.debug("connector sidecar: " + format, *args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _json(self, status: int, payload: dict[str, Any]):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, status: int, payload: bytes, content_type: str):
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/health":
                return self._json(200, _health())
            if path == "/scene":
                return self._json(200, {"ok": True, **_scene()})
            if path == "/moodboard":
                return self._json(200, {"ok": True, **_moodboard()})
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "moodboard" and parts[2] == "preview":
                return self._bytes(200, _moodboard_preview(int(parts[1])), "image/png")
            if path in {"/viewport.jpg", "/viewport.png"}:
                return self._bytes(200, _viewport(), "image/png")
            return self._json(404, {"ok": False, "error": f"unknown path {path}"})
        except Exception as exc:
            logger.exception("connector GET %s failed", path)
            return self._json(500, {"ok": False, "error": str(exc)})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/export":
                spec = parse_export_body(json.dumps(payload))
                result = _export(spec)
                return self._json(200, result)
            if path == "/prompt":
                return self._json(200, _prompt(payload))
            if path == "/heartbeat":
                return self._json(200, {"ok": True})
            return self._json(404, {"ok": False, "error": f"unknown path {path}"})
        except Exception as exc:
            logger.exception("connector POST %s failed", path)
            return self._json(400, {"ok": False, "error": str(exc)})


def start_sidecar(port: int = DEFAULT_SIDECAR_PORT) -> int:
    global _server, _thread, _port
    if _server is not None:
        return _port
    _port = port
    _server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    _thread = threading.Thread(target=_server.serve_forever, name="mixar-connector-sidecar", daemon=True)
    _thread.start()
    logger.info("Mixar connector sidecar listening on http://127.0.0.1:%s", port)
    return port


def stop_sidecar() -> None:
    global _server, _thread
    if _server is None:
        return
    _server.shutdown()
    _server.server_close()
    _server = None
    _thread = None
    logger.info("Mixar connector sidecar stopped")


def sidecar_port() -> int:
    return _port
