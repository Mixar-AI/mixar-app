# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local (this computer) provider — byok-side logic.

Owns the data behind the Local branch of the AI Provider dialog:

- the managed-model dropdown items (built from the local_models catalog,
  cached module-level because EnumProperty items callbacks run on every
  draw and the catalog probe touches RAM/manifest);
- the "Detected local apps" mirror (populated by a worker-thread probe of
  known Ollama/LM Studio/oMLX/llama.cpp ports, marshalled to the main
  thread — never probed from a draw);
- the two save paths: managed (requires the supervised server healthy,
  registers base_url + manifest api-token with the backend) and custom
  (worker-thread reachability ping of ``<base>/v1/models`` first).

Both saves go through the ordinary ``PUT /agent/byok``
(`byok_client.save_credentials`) with the extended ``base_url`` /
``supports_vision`` fields, and on success snapshot the registration into
the local_models manifest + refresh the relay's approved bases.
"""

import threading
import urllib.request
from typing import Callable, List, Optional, Tuple

from mixar.config.logging_config import get_logger

from ..constants import LOCAL_PROVIDER_ID

logger = get_logger(__name__)

# EnumProperty items must keep a stable Python reference (GC contract).
_model_items_cache: Optional[List[Tuple[str, str, str]]] = None
_LOADING_ITEM = ('NONE', "Loading…", "Reading the local model catalog")

# Detected-servers mirror: written on the main thread only.
_detected: List[dict] = []
_detected_items_cache: List[Tuple[str, str, str]] = []
_DETECT_NONE_ITEM = (
    'NONE', "Choose a detected app…",
    "Local OpenAI-compatible servers found on this computer",
)
_probe_running = False

_PING_TIMEOUT_S = 3.0


# ---------------------------------------------------------------------------
# Managed model dropdown
# ---------------------------------------------------------------------------

def build_model_items(rows) -> List[Tuple[str, str, str]]:
    """Pure: catalog rows (from ``catalog.list_models()``) → enum items.

    Suffix rules: downloaded state and RAM fit are appended to the label so
    the dropdown itself tells the user what a choice implies.
    """
    items = []
    for row in rows:
        label = row["label"]
        if row.get("recommended"):
            label += " (recommended)"
        if row.get("fit") == "too_big":
            label += " — too large for this machine"
        elif not row.get("downloaded"):
            label += " — not downloaded"
        gigabytes = row.get("total_bytes", 0) / (1024 ** 3)
        description = f"{row.get('description', '')} (~{gigabytes:.1f} GB)"
        items.append((row["id"], label, description))
    return items


def refresh_model_items() -> None:
    """(Re)build the dropdown cache from live catalog state. Main thread
    (RAM probe + manifest read — cheap, but never do it per-draw)."""
    global _model_items_cache
    try:
        from mixar.modules.local_models.core import catalog
        _model_items_cache = build_model_items(catalog.list_models())
    except Exception as exc:
        logger.warning("Local model items refresh failed: %s", exc)
        _model_items_cache = None


def get_model_items() -> List[Tuple[str, str, str]]:
    """EnumProperty items callback data — cache or a loading sentinel."""
    if _model_items_cache:
        return _model_items_cache
    return [_LOADING_ITEM]


def model_row(model_id: str) -> Optional[dict]:
    try:
        from mixar.modules.local_models.core import catalog
        return catalog.get_model(model_id)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Detected local apps (custom mode)
# ---------------------------------------------------------------------------

def get_detected_items() -> List[Tuple[str, str, str]]:
    """EnumProperty items for the detected-apps dropdown (stable refs)."""
    if _detected_items_cache:
        return [_DETECT_NONE_ITEM] + _detected_items_cache
    if _probe_running:
        return [('NONE', "Scanning…", "Looking for local AI apps")]
    return [('NONE', "No local apps detected", "Use the fields below, or Rescan")]


def detected_entry(identifier: str) -> Optional[dict]:
    for index, entry in enumerate(_detected):
        if f"DET_{index}" == identifier:
            return entry
    return None


_DETECT_LABELS = {
    "ollama": "Ollama",
    "lm_studio": "LM Studio",
    "omlx": "oMLX",
    "llama_cpp": "llama.cpp server",
}


def refresh_detected_async() -> None:
    """Probe known local servers on a worker thread; mirror results back on
    the main thread (never blocks a draw or an update callback)."""
    global _probe_running
    if _probe_running:
        return
    _probe_running = True

    def _thread():
        found = []
        try:
            from mixar.modules.local_models.core import detect
            found = detect.probe_known_servers()
        except Exception as exc:
            logger.debug("Local server probe failed: %s", exc)
        _schedule_on_main(_apply_detected, found)

    threading.Thread(
        target=_thread, daemon=True, name="MixarLocalDetect"
    ).start()


def _apply_detected(found) -> None:
    """Main thread: rewrite the mirror + enum cache, nudge a redraw."""
    global _detected, _detected_items_cache, _probe_running
    _probe_running = False
    _detected = list(found or [])
    items = []
    for index, entry in enumerate(_detected):
        kind = _DETECT_LABELS.get(entry.get("kind"), entry.get("kind", "?"))
        models = entry.get("models") or []
        first = models[0] if models else ""
        label = f"{kind} — {entry.get('base_url', '')}"
        detail = f"{len(models)} model(s)" + (f", e.g. {first}" if first else "")
        items.append((f"DET_{index}", label, detail))
    _detected_items_cache = items
    _redraw()


def apply_detected_selection(wm, identifier: str) -> None:
    """Fill the custom fields from a detected entry (enum update callback)."""
    entry = detected_entry(identifier)
    if not entry:
        return
    try:
        wm.byok_form_local_custom_base = entry.get("base_url", "")
        models = entry.get("models") or []
        if models:
            wm.byok_form_local_custom_model = models[0]
    except Exception as exc:
        logger.debug("Applying detected selection failed: %s", exc)


# ---------------------------------------------------------------------------
# Save paths
# ---------------------------------------------------------------------------

def save_managed(wm, on_done: Callable) -> Tuple[bool, Optional[str]]:
    """Managed save: the supervised server must be healthy and serving the
    selected model. Registers ``http://127.0.0.1:<port>`` + the manifest
    api-token with the backend. Returns (started, ui_error)."""
    from mixar.modules.local_models.core import manifest, server_supervisor

    model_id = wm.byok_form_local_model
    row = model_row(model_id)
    if row is None:
        return False, "Choose a local model first."
    current = server_supervisor.current()
    if (not server_supervisor.is_healthy() or not current
            or current.get("model_id") != model_id):
        return False, "Start the local model first (it must be running to save)."
    base_url = current["base_url"]
    supports_vision = bool(row.get("vision"))

    def _wrapped(success, data, err):
        if success:
            try:
                manifest.set_registered(base_url, model_id, supports_vision)
                manifest.set_active_model_id(model_id)
                from mixar.modules.local_models.core import orchestrator
                orchestrator.refresh_approved_bases()
            except Exception as exc:
                logger.warning("Local registration snapshot failed: %s", exc)
        on_done(success, data, err)

    from . import byok_client
    byok_client.save_credentials(
        provider=LOCAL_PROVIDER_ID,
        model=model_id,
        api_key=manifest.get_api_token(),
        base_url=base_url,
        supports_vision=supports_vision,
        on_done=_wrapped,
    )
    return True, None


def save_custom_async(wm, on_done: Callable) -> Tuple[bool, Optional[str]]:
    """Custom save: validate the base is local, ping ``/v1/models`` on a
    worker thread, then PUT the credential. Returns (started, ui_error)."""
    from mixar.modules.local_models.core import relay

    base_url = (wm.byok_form_local_custom_base or "").strip().rstrip("/")
    model = (wm.byok_form_local_custom_model or "").strip()
    # Many local servers need no key. The backend's local provider accepts a
    # keyless credential (api_key null) — omit the field entirely when blank.
    api_key = (wm.byok_form_local_custom_key or "").strip() or None
    if not base_url or not model:
        return False, "Base URL and model name are required."
    invalid = relay.validate_base_url(base_url)
    if invalid:
        return False, invalid

    def _thread():
        err = _ping_models_endpoint(base_url)
        _schedule_on_main(_after_ping, err)

    def _after_ping(err):
        if err:
            on_done(False, None, err)
            return

        def _wrapped(success, data, save_err):
            if success:
                try:
                    from mixar.modules.local_models.core import (
                        manifest, orchestrator,
                    )
                    manifest.set_registered(base_url, model, False)
                    orchestrator.refresh_approved_bases()
                except Exception as exc:
                    logger.warning("Local registration snapshot failed: %s", exc)
            on_done(success, data, save_err)

        from . import byok_client
        byok_client.save_credentials(
            provider=LOCAL_PROVIDER_ID,
            model=model,
            api_key=api_key,
            base_url=base_url,
            supports_vision=False,
            on_done=_wrapped,
        )

    threading.Thread(
        target=_thread, daemon=True, name="MixarLocalCustomPing"
    ).start()
    return True, None


def _ping_models_endpoint(base_url: str) -> Optional[str]:
    """Worker thread: quick GET of the server's models listing. Returns a
    UI-safe error, or None when reachable."""
    path = "/models" if base_url.rstrip("/").endswith("/v1") else "/v1/models"
    url = base_url.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=_PING_TIMEOUT_S) as response:
            status = getattr(response, "status", None) or response.getcode()
        if 200 <= status < 500:
            # 401/403 still proves a server is listening — the key may be
            # required per-request; the backend relay will surface that.
            return None
        return f"The local server answered HTTP {status}."
    except Exception:
        return (
            "Could not reach the local server. Check that it is running "
            "and the base URL is correct."
        )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _schedule_on_main(callback: Callable, *args) -> None:
    import bpy

    def _run():
        try:
            callback(*args)
        except Exception as exc:
            logger.warning("Local provider callback failed: %s", exc, exc_info=True)
        return None

    bpy.app.timers.register(_run, first_interval=0.0)


def _redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw
        trigger_ui_redraw()
    except Exception:
        pass


def clear() -> None:
    """Logout: drop caches so the next login starts fresh."""
    global _model_items_cache, _detected, _detected_items_cache
    _model_items_cache = None
    _detected = []
    _detected_items_cache = []
