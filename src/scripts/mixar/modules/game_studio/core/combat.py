# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The spec's ``combat`` block (contract v1.3 §2).

Times are seconds on the EXPORTED clip timeline. The source of a window is,
in order: ``configure_game(combat=...)`` overrides (stored in the scene's
settings), then pose markers on the action (``hit_start``/``hit_end``, a
single ``hit`` = ``[t, t + 0.12]``, ``iframes_start``/``iframes_end``).
Nothing else: the client never invents timing, the fork owns defaults.

Frame → seconds. The glTF exporter samples an action from its first to its
last frame and writes key times ``frame / fps`` (``fps = render.fps /
fps_base``; no slide to zero), so a clip on frames 1-91 at 30 fps has key
times 0.0333-3.0333 and Godot plays it as a 3.033 s clip. ``prove`` takes
each animation's sampler input accessor ``min``/``max`` from the written GLB
(``exporter.read_timeline``; file reads stay out of this module, which agent
scripts can reach through ``spec``) and derives ``shift = file_min - first_frame / fps``; a clip is PROVEN when
``file_max`` also equals ``last_frame / fps + shift`` within half a frame.
``length_s`` is the file's ``max``. A clip that fails the proof keeps its
length but loses its marker windows, with a warning.
"""

from __future__ import annotations

import copy
import re

from ..constants import HIT_MARKER_SINGLE, HIT_MARKERS, HIT_SINGLE_S, IFRAME_MARKERS
from .characters import COMBAT_STATES

SHAPES = ("arc", "circle", "line")
CLIP_NAME = re.compile(r"^[A-Za-z0-9_.\- ]{1,64}$")
MAX_CLIPS = 64
_CLIP_NUMBERS = {"damage": (int, 0, 100000), "range": (float, 0.0, 100.0),
                 "radius": (float, 0.0, 100.0), "arc_deg": (float, 1.0, 360.0)}
_WINDOWS = ("hit", "iframes")
_SECTIONS = {"boss": {"phase2_at": (float, 0.0, 1.0), "aggression": (float, 0.1, 10.0)},
             "player": {"stamina": (float, 1.0, 10000.0), "lock_on": (bool, None, None)}}
_PLACES = 4


def _number(path, value, kind, low, high):
    if kind is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{path} must be true or false")
        return value
    if isinstance(value, bool):
        raise ValueError(f"{path} must be a number")
    number = kind(value)
    if not low <= number <= high:  # also rejects NaN
        raise ValueError(f"{path} must be between {low} and {high}")
    return number


def _window(path, value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(v, bool) for v in value)):
        raise ValueError(f"{path} must be [start_s, end_s]")
    start, end = float(value[0]), float(value[1])
    if not 0.0 <= start < end <= 600.0:
        raise ValueError(f"{path} needs 0 <= start < end")
    return [round(start, _PLACES), round(end, _PLACES)]


def normalize(raw, base=None) -> tuple[dict, list[str]]:
    """``base`` (stored overrides) updated with ``raw``; each bad field is
    skipped with one error. A clip set to ``null`` drops its override."""
    merged = copy.deepcopy(base) if isinstance(base, dict) else {}
    errors = []
    if raw is None:
        return merged, errors
    if not isinstance(raw, dict):
        return merged, ["combat must be an object"]
    for key, value in raw.items():
        if key == "clips":
            if not isinstance(value, dict):
                errors.append("combat.clips must be an object keyed by clip name")
                continue
            clips = merged.setdefault("clips", {})
            for name, fields in value.items():
                _merge_clip(clips, str(name), fields, errors)
            if not clips:
                merged.pop("clips")
        elif key in _SECTIONS:
            if not isinstance(value, dict):
                errors.append(f"combat.{key} must be an object")
                continue
            section = merged.setdefault(key, {})
            for field, field_value in value.items():
                spec = _SECTIONS[key].get(field)
                if spec is None:
                    errors.append(f"unknown setting combat.{key}.{field}")
                    continue
                try:
                    section[field] = _number(f"combat.{key}.{field}", field_value, *spec)
                except (TypeError, ValueError) as exc:
                    errors.append(str(exc) or f"combat.{key}.{field} is invalid")
            if not section:
                merged.pop(key)
        else:
            errors.append(f"unknown setting combat.{key}")
    return merged, errors


def _merge_clip(clips, name, fields, errors):
    path = f"combat.clips.{name}"
    if not CLIP_NAME.match(name):
        errors.append(f"{path}: clip names are 1-64 letters, digits, '_', '.', '-' or spaces")
        return
    if fields is None:
        clips.pop(name, None)
        return
    if not isinstance(fields, dict):
        errors.append(f"{path} must be an object")
        return
    if name not in clips and len(clips) >= MAX_CLIPS:
        errors.append(f"combat.clips holds at most {MAX_CLIPS} clips")
        return
    clip = dict(clips.get(name) or {})
    for field, value in fields.items():
        try:
            if field == "length_s":
                raise ValueError(f"{path}.length_s is measured from the exported file, not set")
            if field in _WINDOWS:
                clip[field] = _window(f"{path}.{field}", value)
            elif field == "shape":
                if value not in SHAPES:
                    raise ValueError(f"{path}.shape must be one of {', '.join(SHAPES)}")
                clip[field] = value
            elif field in _CLIP_NUMBERS:
                clip[field] = _number(f"{path}.{field}", value, *_CLIP_NUMBERS[field])
            else:
                raise ValueError(f"unknown setting {path}.{field}")
        except (TypeError, ValueError) as exc:
            errors.append(str(exc) or f"{path}.{field} is invalid")
    if clip:
        clips[name] = clip


# --- frames → seconds --------------------------------------------------------

def scene_fps(scene) -> float:
    render = getattr(scene, "render", None)
    fps = float(getattr(render, "fps", 24) or 24)
    return fps / float(getattr(render, "fps_base", 1.0) or 1.0)


def frame_range(action) -> tuple[float, float]:
    start, end = tuple(getattr(action, "frame_range", (0.0, 0.0)))[:2]
    return float(start), float(end)


def marker_frames(action) -> dict:
    """``{"hit": (f0, f1) | None, "iframes": ..., "problems": [...]}`` in frames."""
    marks = {}
    for marker in getattr(action, "pose_markers", ()) or ():
        marks.setdefault(str(getattr(marker, "name", "")).strip().lower(), float(marker.frame))
    out, problems = {"hit": None, "iframes": None}, []
    for key, (first, last) in (("hit", HIT_MARKERS), ("iframes", IFRAME_MARKERS)):
        if first in marks or last in marks:
            if first in marks and last in marks and marks[first] < marks[last]:
                out[key] = (marks[first], marks[last])
            else:
                problems.append(f"{key}: needs both {first} and {last}, {first} first")
    if out["hit"] is None and HIT_MARKER_SINGLE in marks and not any(m in marks for m in HIT_MARKERS):
        out["hit"] = (marks[HIT_MARKER_SINGLE], None)  # [t, t + HIT_SINGLE_S]
    out["problems"] = problems
    return out


def predicted(action, fps: float) -> dict:
    """The clip's timeline from the action alone (before a file exists)."""
    start, end = frame_range(action)
    return {"min": start / fps, "max": end / fps, "shift": 0.0, "proven": False}


def prove(actions: dict, timeline: dict, fps: float) -> dict:
    """Per clip ``{min, max, shift, proven, first_frame, last_frame}`` from
    the written file's ``timeline`` (``exporter.read_timeline``)."""
    proof, tolerance = {}, 0.5 / fps
    for name, action in actions.items():
        start, end = frame_range(action)
        if name not in timeline:
            proof[name] = {"proven": False, "in_file": False, "first_frame": start, "last_frame": end}
            continue
        low, high = timeline[name]
        shift = low - start / fps
        proof[name] = {"min": round(low, _PLACES), "max": round(high, _PLACES), "shift": round(shift, _PLACES),
                       "first_frame": start, "last_frame": end, "in_file": True,
                       "proven": abs(high - (end / fps + shift)) <= tolerance}
    return proof


def resolve(found, overrides: dict, fps: float, proof: dict | None = None) -> tuple[dict, dict, list[str]]:
    """``(combat_block, timing_sources, warnings)``.

    ``found`` is ``characters.find``; ``proof`` is ``prove`` of the written
    GLB (None → predicted lengths, as ``game_status`` shows before a build).
    ``timing_sources`` maps every combat clip (§3 attack/light/heavy/dodge)
    to ``markers | configured | default``.
    """
    overrides = overrides or {}
    wanted = (overrides.get("clips") or {})
    clips, sources, warnings = {}, {}, []
    exported = {}
    for character in found:
        for state, names in character["clips"].items():
            for name in names:
                exported[name] = (state, character["actions"][name])
    for name in sorted(wanted):
        if name not in exported:
            warnings.append(f"combat.clips.{name}: no exported character clip has that name")
    for name, (state, action) in sorted(exported.items()):
        timeline = (proof or {}).get(name) or predicted(action, fps)
        if proof is not None and not timeline.get("in_file", True):
            warnings.append(f"{name}: clip missing from the exported file")
            continue
        entry, source = {}, "default"
        marks = marker_frames(action)
        for problem in marks["problems"]:
            warnings.append(f"{name}: pose markers {problem}")
        for key in _WINDOWS:
            frames = marks[key]
            if frames is None:
                continue
            if proof is not None and not timeline.get("proven"):
                warnings.append(f"{name}: exported timeline did not match frames/fps; marker timing left out")
                break
            start = frames[0] / fps + timeline["shift"]
            end = (start + HIT_SINGLE_S) if frames[1] is None else frames[1] / fps + timeline["shift"]
            entry[key] = [round(start, _PLACES), round(end, _PLACES)]
            source = "markers"
        configured = wanted.get(name) or {}
        if any(key in configured for key in _WINDOWS):
            source = "configured"
        entry.update(configured)
        if state in COMBAT_STATES:
            sources[name] = source
        if not entry:
            continue
        length = round(timeline["max"], _PLACES)
        for key in _WINDOWS:
            window = entry.get(key)
            if window and not 0.0 <= window[0] < window[1] <= length + 1e-6:
                warnings.append(f"{name}: {key} {window} lies outside the clip (0-{length} s); left out")
                entry.pop(key)
        if entry:
            clips[name] = {"length_s": length, **entry}
    block = {"clips": clips}
    for key in ("boss", "player"):
        if overrides.get(key):
            block[key] = dict(overrides[key])
    return block, sources, warnings
