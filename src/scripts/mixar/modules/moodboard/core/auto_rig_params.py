# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rig params for the agent's auto-rig entry point, gated by the catalog.

The rig model's catalog schema owns which params exist and their allowed
values (never hardcode param names: the backend adapters own vendor mapping).
A key the chosen model does not declare is dropped; an enum it declares is
validated against the schema. Only when the catalog is unknown (not loaded,
model or schema absent) does the legacy Tripo behaviour apply: ``rig_type`` /
``spec`` are validated against the historical sets and always sent.
"""

from typing import Dict, Optional, Tuple

#: Legacy (catalog-unknown) validation sets: Tripo's knobs.
LEGACY_RIG_TYPES = frozenset({
    "auto", "biped", "quadruped", "hexapod", "octopod",
    "avian", "serpentine", "aquatic",
})
LEGACY_SPECS = frozenset({"tripo", "mixamo", "actorcore", "unity", "unreal", "vrm"})


def declared_params(model_slug: str) -> Optional[Dict[str, dict]]:
    """The rig model's catalog param schemas, or None when unknown.

    Tri-state per param: declared (key present), not declared (schema known,
    key absent), unknown (None: no catalog, no such model, no schema).
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model
        from mixar.modules.hunyuan.constants import ANIMATE_RIG_SERVICE

        model = get_model(ANIMATE_RIG_SERVICE, model_slug)
    except Exception:
        return None
    if not isinstance(model, dict) or not model:
        return None
    params = model.get("parameters")
    return params if isinstance(params, dict) else None


def _allowed_values(spec) -> Optional[Dict[str, object]]:
    """Case-insensitive lookup of a schema's enum/choices: lower -> value."""
    if not isinstance(spec, dict):
        return None
    choices = spec.get("choices")
    if choices:
        values = [c.get("value") for c in choices if isinstance(c, dict)]
    else:
        values = list(spec.get("enum") or ())
    return {str(v).lower(): v for v in values if v is not None} or None


def build_rig_params(
    model_slug: str, rig_type: str, spec: str, height_meters: float,
) -> Tuple[Optional[dict], str]:
    """``(params, "")`` for the rig job, or ``(None, reason)`` on a bad value."""
    schema = declared_params(model_slug)
    params: dict = {}
    for key, raw, default, legacy in (
        ("rig_type", rig_type, "auto", LEGACY_RIG_TYPES),
        ("spec", spec, "tripo", LEGACY_SPECS),
    ):
        value = (raw or default).strip().lower()
        if schema is None:
            allowed = {v: v for v in legacy}
        elif key in schema:
            allowed = _allowed_values(schema[key])
        else:
            continue  # the chosen model has no such knob
        if allowed is not None:
            if value not in allowed:
                return None, (
                    f"Invalid {key} '{raw}'. Expected one of: "
                    f"{', '.join(sorted(str(v) for v in allowed.values()))}."
                )
            params[key] = allowed[value]
        else:
            params[key] = value
    if height_meters and height_meters > 0 and schema is not None and "height_meters" in schema:
        params["height_meters"] = float(height_meters)
    return params, ""
