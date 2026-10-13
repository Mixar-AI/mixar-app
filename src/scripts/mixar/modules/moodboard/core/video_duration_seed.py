# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Seed a Generate Video node's output duration from the videos feeding it.

Video-to-video generation almost always wants an output as long as what was
fed in, and the catalog default (a flat 5s) silently truncated longer
references. ``node_graph.connect_nodes`` calls ``seed_video_duration`` when a
VIDEO source is connected — only then: connecting a still must not move the
value, and recomputing on disconnect would discard a duration the user had
since dialled in by hand.
"""

from __future__ import annotations

import math

from mixar.modules.common.generation_params.core.bounds import integer_window

from .media_utils import describe_moodboard_media


# Catalog parameter carrying a video model's OUTPUT length in seconds. Keyed by
# name, which is a KNOWN CATALOG GAP: parameter schemas publish type/bounds/
# widget but nothing that identifies a parameter's MEANING, and "as long as the
# input" is inherently semantic. Every other schema consumer is name-agnostic
# on purpose, so this is the one place a name is assumed — and it fails soft: a
# model that renames or omits the parameter keeps the catalog default. Retire
# it by publishing a role hint on the parameter (e.g. "role": "output_duration").
VIDEO_DURATION_PARAM_NAME = "duration"

# Tolerance for the frames/fps division: an exactly-5s clip can measure
# 5.0000001, which a bare ceil() would inflate to a 6s output (billed as one).
DURATION_EPSILON_SECONDS = 1e-6


def video_duration_seconds(item: object) -> float | None:
    """Best-effort length of a moodboard movie in seconds, or ``None``.

    Blender's ``Image`` exposes a movie's frame COUNT but not its frame rate,
    so the file is loaded as a temporary ``MovieClip`` purely to read ``fps``
    and freed before returning. Advisory only: the backend parses the uploaded
    file and owns the reference-duration cap, so a codec Blender cannot read
    degrades to "no default", never to a wrong limit.
    """
    media = describe_moodboard_media(item)
    if media["media_type"] != "VIDEO" or not media["source_available"]:
        return None

    import bpy

    clip = None
    try:
        clip = bpy.data.movieclips.load(media["resolved_filepath"])
        fps = float(getattr(clip, "fps", 0.0) or 0.0)
        frames = int(getattr(clip, "frame_duration", 0) or 0)
        if fps <= 0.0 or frames <= 0:
            return None
        return frames / fps
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None
    finally:
        if clip is not None:
            try:
                bpy.data.movieclips.remove(clip)
            except (AttributeError, ReferenceError, RuntimeError):
                pass


def seed_video_duration(node, input_items, measure=video_duration_seconds) -> bool:
    """Set ``node``'s duration parameter to the total length of its videos.

    The total is used because several references read as one timeline. Returns
    False whenever nothing was seeded, leaving the catalog default alone.
    """
    if node is None or node.action_type != 'VIDEO_GEN':
        return False
    parameter = next(
        (
            item for item in node.parameters
            if item.name == VIDEO_DURATION_PARAM_NAME
            and item.parameter_type in {'INTEGER', 'FLOAT'}
        ),
        None,
    )
    if parameter is None:
        return False

    total = 0.0
    for item in input_items:
        seconds = measure(item)
        if seconds and seconds > 0.0:
            total += seconds
    if total <= 0.0:
        return False

    # The schema's bounds are authoritative: a 40s reference must not submit a
    # duration the model rejects after credits are held.
    if parameter.parameter_type == 'FLOAT':
        lower, upper = float(parameter.minimum), float(parameter.maximum)
        parameter.value_float = float(min(max(total, lower), upper))
        return True

    # Integer models take whole seconds (Seedance 2.5: any integer 4-30). Round
    # UP: 12.4s seeded as 12s is the truncation this exists to stop. The window
    # is the representable integer range, so a fractional bound cannot admit an
    # excluded value and the unbounded +/-1e18 sentinels stay inside a C int.
    window = integer_window(parameter.minimum, parameter.maximum)
    if window is None:
        return False
    low, high = window
    seconds = math.ceil(total - DURATION_EPSILON_SECONDS)
    parameter.value_integer = int(min(max(seconds, low), high))
    return True
