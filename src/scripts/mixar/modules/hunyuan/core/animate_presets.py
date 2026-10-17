# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Retarget preset rules shared by the Animate node and the agent operator.

A preset value is ``preset:<skeleton>:<name>``; its skeleton must be the
rig's (the backend refuses a mismatch at submit, and fails closed at
dispatch), so both entry points filter and validate by it here. The preset
list itself is the catalog's: nothing in this module names a preset.

Refusals are English ``n_`` templates: the agent operator sends them as they
are, and the card passes ``rpt_`` as ``translate`` so its error line is in
the interface language (see ``preset_error``).
"""

from __future__ import annotations

from mixar.modules.common.i18n import n_
from ..constants import ANIMATE_PRESETS_PARAM, ANIMATION_CAPABILITY

# Why a character cannot be animated. A rig job stamps the skeleton only when
# the backend reported one, which it does for a retargetable Tripo rig alone
# (a Meshy rig or an older rig carries the job id without it).
NOT_A_RIG = n_("Animate needs a rigged character: connect an Auto Rig result")
RIG_TAKES_NO_PRESETS = n_(
    "This rig can't take preset animations: run Auto Rig again with a Tripo model")


def rig_refusal(rig_job_id, skeleton) -> str:
    """The ``n_`` refusal for a rig's stamps, or "" when it can be animated."""
    if not rig_job_id:
        return NOT_A_RIG
    if not skeleton:
        return RIG_TAKES_NO_PRESETS
    return ""


def preset_skeleton(value) -> str:
    """``preset:biped:walk`` -> ``biped``; "" for any other shape."""
    parts = str(value or "").split(":")
    return parts[1].strip().lower() if len(parts) >= 3 and parts[0] == "preset" else ""


def clip_name(value) -> str:
    """The short name a preset's clip carries in the result GLB (``walk``)."""
    return str(value or "").rsplit(":", 1)[-1]


def parse_preset_list(text) -> list:
    """Comma-separated preset values -> ordered, de-duplicated list."""
    seen, presets = set(), []
    for part in str(text or "").split(","):
        value = part.strip()
        if value and value not in seen:
            seen.add(value)
            presets.append(value)
    return presets


def retarget_catalog() -> tuple:
    """``(service_key, model_slug, choices)`` for the live retarget service.

    Reads the ``animation`` capability's first moodboard service and its
    default model; ``choices`` are the ``animations`` parameter's published
    ``{"value", "label"}`` rows. Everything is empty when the catalog does
    not publish the capability — callers fail closed, never substitute.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model, get_services
        from mixar.modules.common.generation_params import catalog_default_model
    except Exception:
        return "", "", []
    services = get_services(ANIMATION_CAPABILITY, surface="moodboard")
    service_key = str((services[0] if services else {}).get("key") or "")
    if not service_key:
        return "", "", []
    model_slug = catalog_default_model(service_key) or ""
    model = get_model(service_key, model_slug) or {}
    parameters = model.get("parameters") or {}
    spec = parameters.get(ANIMATE_PRESETS_PARAM) if isinstance(parameters, dict) else None
    from mixar.modules.common.generation_params.core.multi_select import spec_choices

    return service_key, model_slug, spec_choices(spec if isinstance(spec, dict) else {})


def preset_error(presets, choices, skeleton: str, translate=str) -> str:
    """One readable refusal for a preset list, or "" when it is submittable.

    ``choices`` is the catalog's published list (empty = unknown, not
    validated); ``skeleton`` is the rig's stamped skeleton ("" = unknown).
    The text is English unless a display path passes ``translate=rpt_``.
    """
    if choices and skeleton and not presets_for_skeleton(choices, skeleton):
        return translate(n_(
            "No preset animations are available for {skeleton} rigs yet"
        )).format(skeleton=skeleton)
    if not presets:
        return translate(n_("Choose at least one animation preset"))
    if choices:
        known = {str(choice.get("value")) for choice in choices}
        unknown = [preset for preset in presets if preset not in known]
        if unknown:
            return translate(n_("Unknown animation preset(s): {names}")).format(
                names=", ".join(unknown))
    if skeleton:
        mismatched = [
            preset for preset in presets
            if preset_skeleton(preset) and preset_skeleton(preset) != skeleton
        ]
        if mismatched:
            return translate(n_(
                "{names}: not for a {skeleton} rig — pick {skeleton} presets"
            )).format(names=", ".join(mismatched), skeleton=skeleton)
    return ""


def presets_for_skeleton(choices, skeleton: str) -> list:
    """The published choices a rig of *skeleton* can use (all when unknown)."""
    if not skeleton:
        return list(choices)
    return [
        choice for choice in choices
        if preset_skeleton(choice.get("value")) in ("", skeleton)
    ]
