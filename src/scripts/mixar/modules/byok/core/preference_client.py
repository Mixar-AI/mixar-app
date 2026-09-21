# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Async wrappers around the hosted agent model-preference endpoints.

Same shape as `byok_client`: a daemon thread does the HTTP call, the result is
marshalled back onto Blender's main thread through `bpy.app.timers`, and callers
receive a (success, data, error_message) tri-tuple without ever seeing a thread,
an APIResponse or a `requests` exception.

The status policy and the NET-* classification are *imported* from
`byok_client` rather than re-implemented — these endpoints share its router and
its envelope, and a second copy would be a second place for the network
contract to drift (generic "Unable to connect" strings are banned; see
`common/network` and tests/network/).

Separate module from `byok_client` because the lifecycles differ: credentials
are a secret the user types, the model preference is a plain stored pick that
the picker writes optimistically.
"""

import threading
from typing import Callable, Optional

from mixar.config.logging_config import get_logger

from ...common.api import get_agent_service
from .byok_client import schedule_on_main, translate_exception, translate_response

logger = get_logger(__name__)

#: The only role the desktop client writes. The backend fans it out to the
#: per-agent roles; exposing nine dropdowns would be a server-admin surface.
DEFAULT_ROLE = "default"


def fetch_preference(
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
) -> None:
    """GET /agent/model-preference — the saved pick plus ``byok_active``."""

    def _thread():
        try:
            response = get_agent_service().get_model_preference()
            success, data, err = translate_response(response)
        except Exception as exc:  # noqa: BLE001 — translated below
            logger.warning("Agent model preference fetch failed: %s", exc)
            success, data, err = translate_exception(exc)
        schedule_on_main(on_done, success, data, err)

    threading.Thread(
        target=_thread, daemon=True, name="MixarAgentModelPrefFetch"
    ).start()


def save_preference(
    provider: str,
    model: str,
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
    thinking_level: Optional[str] = None,
    role: str = DEFAULT_ROLE,
) -> None:
    """PUT /agent/model-preference — save the pick.

    ``thinking_level`` None means "the model's own default" and is omitted from
    the payload rather than sent as null.
    """

    def _thread():
        try:
            response = get_agent_service().put_model_preference(
                provider=provider, model=model, role=role,
                thinking_level=thinking_level,
            )
            success, data, err = translate_response(response)
        except Exception as exc:  # noqa: BLE001 — translated below
            logger.warning("Agent model preference save failed: %s", exc)
            success, data, err = translate_exception(exc)
        schedule_on_main(on_done, success, data, err)

    threading.Thread(
        target=_thread, daemon=True, name="MixarAgentModelPrefSave"
    ).start()


def delete_preference(
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
    role: str = DEFAULT_ROLE,
) -> None:
    """DELETE /agent/model-preference/{role} — back to the server default.

    A 404 means "there was nothing saved", which is the state the caller asked
    for, so it is reported as success.
    """

    def _thread():
        try:
            response = get_agent_service().delete_model_preference(role)
            if response.status_code == 404:
                success, data, err = True, None, None
            else:
                success, data, err = translate_response(response)
        except Exception as exc:  # noqa: BLE001 — translated below
            if getattr(exc, "status_code", None) == 404:
                success, data, err = True, None, None
            else:
                logger.warning("Agent model preference delete failed: %s", exc)
                success, data, err = translate_exception(exc)
        schedule_on_main(on_done, success, data, err)

    threading.Thread(
        target=_thread, daemon=True, name="MixarAgentModelPrefDelete"
    ).start()
