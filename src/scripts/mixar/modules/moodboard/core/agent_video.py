# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The bpy-free half of the agent's video operators.

``mixie.agent_video_generate`` and ``mixie.agent_video_upscale`` are driven by
the backend agent's ``enqueue_generation`` tool, which addresses moodboard
media by NAME and hands the model's catalog parameters over as ONE JSON
string (the schema differs per model — Seedance vs the MiniMax H3 tiers — so
a scalar operator property per field would freeze one model's shape into the
client). Everything here is plain Python so the standalone suite can pin it:
name resolution, the params merge and the model check. The operators keep
only the bpy calls and the enqueue.
"""

from __future__ import annotations

import json
from typing import Callable

#: The one moodboard item collection every lookup walks (see media_utils).
MOODBOARD_ITEMS_ATTR = "mixie_moodboard_images"


def split_names(raw) -> list[str]:
    """A comma-separated operator string -> ordered, de-duplicated names."""
    names: list[str] = []
    for part in str(raw or "").split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    return names


def find_moodboard_media(
    scene, names: list[str], *, describe: Callable, want_video: bool,
) -> list[dict]:
    """Resolve moodboard items by their image datablock name, in ``names`` order.

    Raises ``ValueError`` naming the first name that is not on the board, is
    the wrong kind of media (a still where a movie was asked for, or the
    reverse), or whose linked movie file has gone missing. The agent reads
    these reasons back through ``mixar_agent_gen_reason``, so each one says
    what to do instead of just what failed.
    """
    by_name: dict[str, object] = {}
    for item in getattr(scene, MOODBOARD_ITEMS_ATTR, ()) or ():
        image = getattr(item, "image", None)
        name = str(getattr(image, "name", "") or "") if image is not None else ""
        if name:
            by_name.setdefault(name, item)

    kind = "video" if want_video else "image"
    found: list[dict] = []
    for name in names:
        item = by_name.get(name)
        if item is None:
            raise ValueError(
                f"No moodboard media named '{name}' — pass a name from "
                "list_moodboard_images verbatim."
            )
        media = describe(item)
        is_video = media.get("media_type") == "VIDEO"
        if is_video != want_video:
            raise ValueError(
                f"'{name}' is a{'n image' if not is_video else ' video'} on the "
                f"moodboard, not a {kind}."
            )
        if is_video and not media.get("source_available"):
            raise ValueError(
                f"The video '{name}' was moved or deleted; its file is no longer "
                "readable."
            )
        found.append(media)
    return found


def merge_catalog_params(model: dict | None, raw_params) -> dict:
    """The model's catalog parameter defaults overlaid with the agent's values.

    ``raw_params`` is the operator's JSON string (``""``/``None`` = no
    overrides). With a catalog row, every non-metadata parameter that has a
    default is filled — the same values the Video Gen tab would submit
    untouched — and a key the model's schema does not know is refused rather
    than forwarded (the backend validated against the same schema; a stray key
    means the two disagree on the model). Without a row (catalog not loaded)
    the overrides pass through and the server validates.
    """
    if raw_params in (None, ""):
        overrides: dict = {}
    else:
        try:
            overrides = json.loads(raw_params) if isinstance(raw_params, str) else dict(raw_params)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"params is not a JSON object: {exc}") from None
        if not isinstance(overrides, dict):
            raise ValueError("params must be a JSON object of parameter values")

    schema = {
        key: spec
        for key, spec in ((model or {}).get("parameters") or {}).items()
        if isinstance(spec, dict) and not key.startswith("_")
    }
    if not schema:
        return dict(overrides)

    unknown = sorted(set(overrides) - set(schema))
    if unknown:
        raise ValueError(
            f"Unknown parameter(s) for this model: {', '.join(unknown)}. "
            f"Valid: {', '.join(sorted(schema))}."
        )
    params = {
        key: spec["default"] for key, spec in schema.items()
        if spec.get("default") is not None
    }
    params.update(overrides)
    return params


def resolve_agent_model(
    service_key: str, requested: str, *, get_model: Callable, get_default: Callable,
) -> str:
    """The catalog slug this enqueue runs on, or ``ValueError``.

    Unlike the tab's ``resolve_model_slug``, a requested slug the catalog does
    not serve is an ERROR, never silently swapped for the default: the agent
    named a model on purpose (and priced its answer on it).
    """
    requested = str(requested or "").strip()
    if requested:
        if get_model(service_key, requested) is None:
            raise ValueError(
                f"'{requested}' is not an enabled {service_key} model; leave model "
                "empty for the default or pass a slug from get_generation_params."
            )
        return requested
    slug = get_default(service_key) or ""
    if not slug:
        raise ValueError(f"No enabled {service_key} model is available right now.")
    return slug
