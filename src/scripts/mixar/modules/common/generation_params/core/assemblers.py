# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Payload assembly — one generic wire contract for every service.

Catalog params travel as ``payload["params"]`` (snake_case, exactly the
``collect_params()`` output, plus ``prompt`` where a service takes one);
file/image inputs stay top-level (``image_bytes_b64``, ``file_bytes_b64``,
``multi_view_images``, ...). The backend provider adapters own the vendor
mapping — Tencent's PascalCase ``sdk_params``, Tripo's decimate body, fal's
snake_case — so the client never builds provider-specific shapes and new
providers/params are DB rows, not client releases.

(The per-service assembler registry that used to live here — Hunyuan
PascalCase maps, ``tripo_params`` clamping — moved into the corresponding
backend adapters when the wire contract was normalized.)

Contract: ``assemble(params, payload, model_slug="") -> payload`` — mutates
and returns *payload*. ``model_slug`` is unused today but kept so call
sites don't churn if a service ever needs model-aware assembly again.
"""

from typing import Any, Callable, Dict

Assembler = Callable[[Dict[str, Any], Dict[str, Any], str], Dict[str, Any]]


def _assemble_default(
    params: Dict[str, Any], payload: Dict[str, Any], model_slug: str = ""
) -> Dict[str, Any]:
    """Catalog params → ``payload["params"]`` (None values dropped)."""
    cleaned = {k: v for k, v in (params or {}).items() if v is not None}
    if cleaned:
        payload["params"] = cleaned
    return payload


def get_assembler(service_key: str) -> Assembler:
    """The assembler for a service key (generic for all services)."""
    return _assemble_default


def assemble_payload(
    service_key: str,
    params: Dict[str, Any],
    payload: Dict[str, Any],
    model_slug: str = "",
) -> Dict[str, Any]:
    """Merge *params* into *payload* using the generic wire contract."""
    return _assemble_default(params, payload, model_slug)
