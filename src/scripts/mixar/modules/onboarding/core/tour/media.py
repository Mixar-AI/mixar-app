# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — which video, narration and beat table play.

``resolve(tour, language)`` decides once, at tour start:

* a complete, verified pack for ``language`` whose ``timing.json`` fits the
  bundled script → that language's parts (``PartsMovie``, one joined audio
  clock) with the re-timed ``Tour``, ``narration == language``;
* anything else → the bundled English video, the English table and
  ``narration == "en"``; the session then shows ``language``'s subtitles.

The decision is a pure function of what is on disk so it is unit-tested
with a temp cache; opening the media (``open_media``) is the only step that
touches Blender.
"""

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from mixar.config.logging_config import get_logger

from . import config, language as language_mod, packs, timing
from .beats import Tour

logger = get_logger(__name__)


@dataclass(frozen=True)
class MediaPlan:
    tour: Tour
    narration: str
    video_paths: Tuple[str, ...]                 # one path (English) or the parts
    parts: Optional[Tuple[Tuple[int, int, str], ...]]   # None for the English file
    duration_ms: Optional[int]                   # known for a pack, None for English
    ready: Optional[Callable[[int], bool]] = None   # pack: is part k on disk yet?


def resolve(tour: Tour, language: str, root: Optional[str] = None,
            allow_partial: bool = True) -> MediaPlan:
    """``allow_partial``: a pack whose timing table and first part are
    verified plays while the rest downloads (the session holds at a part
    that has not arrived); False demands the complete pack."""
    code = language_mod.normalize(language)
    english = MediaPlan(tour, language_mod.DEFAULT_CODE, (config.video_path(),), None, None)
    if language_mod.is_bundled(code):
        return english
    script = timing.script_hash(tour)
    pack = packs.installed(code, root=root, expected_script_hash=script)
    if pack is None and allow_partial:
        pack = packs.partial(code, root=root, expected_script_hash=script)
    if pack is None:
        logger.info("Tour: no usable %s pack; narrating in English with subtitles", code)
        return english
    try:
        retimed = timing.apply(tour, pack.timing)
    except timing.TimingError as exc:
        logger.warning("Tour: %s pack timing rejected (%s); using English", code, exc)
        return english
    return MediaPlan(retimed, code, tuple(p[2] for p in pack.parts), pack.parts,
                     pack.duration_ms, ready=pack.ready)


def open_media(plan: MediaPlan, silent: bool, rate: float):
    """(movie, clock) for a plan. English keeps today's single-file objects."""
    from .clock import make_clock
    if plan.parts is None:
        from .video import MovieTexture
        movie = MovieTexture(plan.video_paths[0])
        clock = make_clock(plan.video_paths[0], movie.duration_ms, silent=silent, rate=rate)
        return movie, clock
    from .video_parts import PartsMovie
    movie = PartsMovie(list(plan.parts), ready=plan.ready)
    movie.prepare(0)
    clock = make_clock(list(plan.parts), movie.duration_ms, silent=silent, rate=rate,
                       ready=plan.ready)
    return movie, clock
