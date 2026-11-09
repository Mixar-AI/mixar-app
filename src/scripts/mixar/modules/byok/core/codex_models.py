# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Codex models the signed-in ChatGPT account can run.

Which models work through Codex depends on the user's ChatGPT plan: a model
the plan lacks fails Save with ``model_not_found`` (mixar-backend#1809, the
top reason AI Provider saves failed). The account's own listing answers it —
``GET CODEX_MODELS_URL`` with the sign-in, the call the Codex CLI makes to
fill its own model picker — so no plan-to-model table is kept here.

`fetch` is the one network call (worker thread). `refresh_async` runs it and
hands the slugs to `model_suggestions.set_codex_account_models` on the main
thread, which narrows the Codex chips to them. Every failure (no sign-in, an
expired token, offline, an unexpected answer) leaves the list unknown: the
dialog then offers the whole catalog as before and Save's probe decides.
The form's pick is never rewritten here: Save checks the stored pick itself
(`byok_codex_ops.execute_codex`), so no model is ever switched unasked.

Known limit: the list is the one asked for the sign-in file last shown in the
dialog; the island key chip reads the same list, not the saved record's file.
"""

from __future__ import annotations

import threading
import time
from typing import Any, FrozenSet, Optional

from mixar.config.logging_config import get_logger

from ..constants import (
    CODEX_CLIENT_VERSION,
    CODEX_MODELS_TIMEOUT_S,
    CODEX_MODELS_URL,
    CODEX_ORIGINATOR,
    CODEX_USER_AGENT,
)
from . import codex_auth, model_suggestions

logger = get_logger(__name__)

# Bumped by every refresh: only the newest one's answer is applied.
_generation = 0
# (resolved sign-in path, start time) of the fetch in flight: opening the
# dialog, picking Codex and the path field can all ask at once.
_inflight: Optional[tuple] = None


def parse_models(payload: Any) -> Optional[FrozenSet[str]]:
    """The slugs of a ``{"models": [{"slug": ...}, ...]}`` listing, or None
    when the answer is not one (unknown, which is not "no models")."""
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None
    slugs = frozenset(
        model["slug"] for model in models
        if isinstance(model, dict) and isinstance(model.get("slug"), str) and model["slug"]
    )
    return slugs or None


def fetch(path: str) -> Optional[FrozenSet[str]]:
    """The model slugs the sign-in at ``path`` (empty = the default) can run,
    or None when unknown. Worker thread only; never logs token material."""
    try:
        creds = codex_auth.read_auth_file(path)
    except codex_auth.CodexBundleError:
        return None
    if codex_auth.is_expired(creds.access_token):
        return None  # Save explains the expired sign-in; nothing to narrow meanwhile
    import requests

    from mixar.modules.common.network import classify_network_error, log_network_failure

    # The User-Agent stays the CLI one the token refresh sends; the listing's
    # version gate reads only ``client_version`` (probed with this User-Agent:
    # 0.20.0 -> no models, 999.0.0 -> the plan's list).
    headers = {
        "Authorization": f"Bearer {creds.access_token}",
        "chatgpt-account-id": creds.account_id,
        "originator": CODEX_ORIGINATOR,
        "User-Agent": CODEX_USER_AGENT,
    }
    try:
        response = requests.get(
            CODEX_MODELS_URL, params={"client_version": CODEX_CLIENT_VERSION},
            headers=headers, timeout=CODEX_MODELS_TIMEOUT_S,
        )
    except requests.exceptions.RequestException as exc:
        log_network_failure(logger, classify_network_error(exc, url=CODEX_MODELS_URL),
                            "Codex model list")
        return None
    if response.status_code != 200:
        logger.info("Codex model list: HTTP %s", response.status_code)
        return None
    try:
        return parse_models(response.json())
    except ValueError:
        return None


def refresh_for_form(wm) -> None:
    """Main thread: refresh the list when the dialog's form shows Codex."""
    if model_suggestions.is_codex(getattr(wm, 'byok_form_provider', '') or ''):
        refresh_async(getattr(wm, 'byok_form_codex_path', '') or '')


def refresh_async(path: str) -> None:
    """Fetch the list for the sign-in at ``path`` off the main thread; a fetch
    for the same file already in flight answers for this call too."""
    global _generation, _inflight
    key = codex_auth.resolve_auth_path(path)
    now = time.monotonic()
    if _inflight and _inflight[0] == key and now - _inflight[1] < 2 * CODEX_MODELS_TIMEOUT_S:
        return
    _generation += 1
    _inflight = (key, now)
    generation = _generation

    def _work():
        slugs = None
        try:
            slugs = fetch(path)
        except Exception as exc:  # noqa: BLE001 — unknown, never a crash
            logger.warning("Codex model list failed: %s", type(exc).__name__)
        _schedule_apply(generation, slugs)

    threading.Thread(target=_work, daemon=True, name="MixarCodexModels").start()


def _schedule_apply(generation: int, slugs: Optional[FrozenSet[str]]) -> None:
    import bpy

    def _run():
        try:
            apply(generation, slugs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Codex model list apply failed: %s", exc)
        return None

    bpy.app.timers.register(_run, first_interval=0.0)


def forget() -> None:
    """Logout: drop the list, and the answer of any fetch still in flight."""
    global _generation, _inflight
    _generation += 1
    _inflight = None
    model_suggestions.set_codex_account_models(None)


def apply(generation: int, slugs: Optional[FrozenSet[str]]) -> None:
    """Main thread: adopt the newest list and redraw. The form's pick is left
    as it is: a pick the list hides lights no chip and Save refuses it."""
    global _inflight
    if generation != _generation:
        return
    _inflight = None
    model_suggestions.set_codex_account_models(slugs)
    try:
        from mixar.modules.common.utils.platform_utils import (
            refresh_popup_dialogs,
            trigger_ui_redraw,
        )

        trigger_ui_redraw()
        refresh_popup_dialogs()  # the open dialog re-reads the chips without a mouse move
    except Exception as exc:  # noqa: BLE001
        logger.debug("Codex model list redraw failed: %s", exc)
