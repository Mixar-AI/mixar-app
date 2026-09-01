# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Human-facing text for queue jobs — shared by every surface that shows one.

The Queue UIList row and the Agent Bubble status pill describe the same job
in the same words, so the catalog lookup and the elapsed formatter live here
rather than in either surface. Both are pure and catalog-tolerant: they are
called from draw callbacks, which must never raise and must never write RNA.

Capability labels are BACKEND-OWNED (the generation catalog), so they change
without a client release — never hardcode a service→label map here.
"""


def format_elapsed(seconds: float) -> str:
    """``m:ss``, or ``h:mm:ss`` past the hour."""
    if seconds < 0:
        seconds = 0.0
    m, s = divmod(int(seconds), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_elapsed_compact(seconds: float) -> str:
    """``m:ss`` with a fixed-width ``Nh+`` past the hour.

    For width-constrained surfaces (the 148 px pill): ``h:mm:ss`` is three
    characters wider than ``m:ss`` and would push the label into clipping,
    and at that duration the minutes have stopped being interesting anyway.
    """
    if seconds < 0:
        seconds = 0.0
    if seconds >= 3600:
        return f"{int(seconds // 3600)}h+"
    return format_elapsed(seconds)


def catalog_feature_label(origin_capability_key: str, service: str) -> str:
    """Backend catalog capability label for a job, or "" if it can't answer.

    Empty means the catalog is unloaded, stale or no longer carries the row —
    callers decide whether to fall back to the raw identifier (fine in a wide
    list row) or to generic wording (better in a narrow pill, where a raw key
    like ``mesh_segment`` reads as a bug).
    """
    capability_key = (origin_capability_key or "").strip()
    service_key = (service or "").strip()
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_capability,
            get_capability_for_service,
            get_service,
        )

        # Composite workflows (Scene Gen HP/LP) name their origin capability
        # explicitly, because the service they execute belongs to another one.
        if capability_key:
            origin = get_capability(capability_key)
            if origin and origin.get("label"):
                return origin["label"]
        capability = get_capability_for_service(service_key)
        if capability and capability.get("label"):
            return capability["label"]
        catalog_service = get_service(service_key)
        if catalog_service and catalog_service.get("label"):
            return catalog_service["label"]
    except Exception:
        pass
    return ""


def model_label(service: str, model: str) -> str:
    """Backend catalog model label, with exact submitted-slug fallback.

    The one definition — the queue UIList and the agent island's Queue tab
    mirror both use it, so the two surfaces can never disagree on a name.
    """
    model_slug = (model or "").strip()
    if not model_slug:
        return ""
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model

        catalog_model = get_model((service or "").strip(), model_slug)
        if catalog_model and catalog_model.get("label"):
            return catalog_model["label"]
    except Exception:
        pass
    return model_slug


def feature_label(
    origin_capability_key: str,
    service: str,
    feature_key: str,
) -> str:
    """Catalog capability label, falling back to the exact identifier."""
    return (
        catalog_feature_label(origin_capability_key, service)
        or (origin_capability_key or "").strip()
        or (service or "").strip()
        or (feature_key or "").strip()
    )
