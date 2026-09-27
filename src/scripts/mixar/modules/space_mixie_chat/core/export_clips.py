# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Clip-aware export (``animations``, export contract §3).

``animations`` is ``None`` (every clip the exporter would include), ``[]``
(no animation) or a list of names that match an Action name or an NLA
strip name on an exported armature — case-sensitive first, then
case-insensitive. ``clip_selection`` mutes the non-matching NLA tracks for
the duration of the export and force-unmutes the matching ones (pushing a
matching active action onto a temporary track when it is not on one);
mute state, active action and the current frame are restored in ``finally``.
"""

from __future__ import annotations

from contextlib import contextmanager


def scene_clips(armatures) -> list[str]:
    """Names of every Action / NLA strip an exporter could include."""
    names: list[str] = []

    def add(name):
        if name and name not in names:
            names.append(str(name))

    for obj in armatures:
        anim = getattr(obj, "animation_data", None)
        if anim is None:
            continue
        action = getattr(anim, "action", None)
        add(getattr(action, "name", None))
        for track in getattr(anim, "nla_tracks", ()) or ():
            for strip in getattr(track, "strips", ()) or ():
                add(getattr(strip, "name", None))
                add(getattr(getattr(strip, "action", None), "name", None))
    return names


def match_clip(requested: str, candidates) -> str | None:
    """Case-sensitive match first, then case-insensitive."""
    if requested in candidates:
        return requested
    lowered = str(requested).lower()
    for name in candidates:
        if str(name).lower() == lowered:
            return name
    return None


def select_clips(armatures, requested) -> tuple[list[str], list[str]]:
    """(matched scene clip names, requested names with no scene match)."""
    available = scene_clips(armatures)
    if requested is None:
        return list(available), []
    matched, missing = [], []
    for name in requested:
        hit = match_clip(str(name), available)
        if hit is None:
            missing.append(str(name))
        elif hit not in matched:
            matched.append(hit)
    return matched, missing


def _strip_matches(strip, selected: set) -> bool:
    if getattr(strip, "name", None) in selected:
        return True
    return getattr(getattr(strip, "action", None), "name", None) in selected


@contextmanager
def clip_selection(armatures, requested, scene=None):
    """Mute what is not requested; yields ``(selected, missing)``.

    With ``requested`` ``None`` or ``[]`` nothing is touched (the exporter
    kwargs from ``animation_kwargs`` decide whether animation is written).
    """
    selected, missing = select_clips(armatures, requested)
    if not requested:
        yield selected, missing
        return
    wanted = set(selected)
    muted: list[tuple[object, bool]] = []
    pushed: list[tuple[object, object]] = []
    actions: list[tuple[object, object]] = []
    frame = getattr(scene, "frame_current", None) if scene is not None else None
    try:
        for obj in armatures:
            anim = getattr(obj, "animation_data", None)
            if anim is None:
                continue
            tracks = list(getattr(anim, "nla_tracks", ()) or ())
            on_track = False
            for track in tracks:
                keep = any(_strip_matches(s, wanted) for s in getattr(track, "strips", ()) or ())
                on_track = on_track or keep
                # Only the requested tracks may sound: a matching track is
                # force-UNMUTED (workflows leave every clip muted, and the FBX
                # exporter skips a muted track), everything else is muted;
                # both are restored below.
                if keep == bool(getattr(track, "mute", False)):
                    muted.append((track, track.mute))
                    track.mute = not keep
                # glTF's ACTIONS mode reads STRIP mute (its NLA_TRACKS mode
                # exports every track whatever its mute flag), so strips
                # follow the same rule: requested ones sound, others do not.
                for strip in getattr(track, "strips", ()) or ():
                    want = _strip_matches(strip, wanted)
                    if want == bool(getattr(strip, "mute", False)):
                        muted.append((strip, strip.mute))
                        strip.mute = not want
            action = getattr(anim, "action", None)
            if action is not None:
                actions.append((anim, action))
                if action.name in wanted and not any(
                    _strip_matches(s, {action.name})
                    for t in tracks for s in (getattr(t, "strips", ()) or ())
                ):
                    track = anim.nla_tracks.new()
                    track.name = f"mixar_export_{action.name}"
                    start = int(round(float(action.frame_range[0])))
                    track.strips.new(action.name, start, action)
                    pushed.append((anim, track))
                # The exporters also write the active action beside the
                # tracks; it must not appear when it was not requested.
                anim.action = None
        yield selected, missing
    finally:
        for anim, track in pushed:
            try:
                anim.nla_tracks.remove(track)
            except Exception:
                pass
        for track, was_muted in muted:
            try:
                track.mute = was_muted
            except Exception:
                pass
        for anim, action in actions:
            try:
                anim.action = action
            except Exception:
                pass
        if scene is not None and frame is not None:
            try:
                scene.frame_set(frame)
            except Exception:
                try:
                    scene.frame_current = frame
                except Exception:
                    pass


def animation_kwargs(fmt: str, requested) -> tuple[dict, str, str]:
    """Exporter kwargs for the clip request → ``(kwargs, mode, warning)``.

    ``mode`` is reported in ``result.preset.animation_mode``: ``all``,
    ``none`` or ``selected``.
    """
    fmt = str(fmt or "").lower()
    family = "gltf" if fmt in ("glb", "gltf") else fmt
    if family in ("usd", "usdc", "usda", "usdz"):
        family = "usd"
    if family == "obj":
        return {}, "none", ""
    if requested is None:
        mode = "all"
    elif not requested:
        mode = "none"
    else:
        mode = "selected"
    if family == "fbx":
        if mode == "none":
            return {"bake_anim": False}, mode, ""
        if mode == "selected":
            return {"bake_anim": True, "bake_anim_use_nla_strips": True,
                    "bake_anim_use_all_actions": False}, mode, ""
        return {"bake_anim": True}, mode, ""
    if family == "gltf":
        if mode == "none":
            return {"export_animations": False}, mode, ""
        if mode == "selected":
            # ACTIONS, not NLA_TRACKS: the glTF exporter's NLA_TRACKS mode
            # writes every track regardless of mute; ACTIONS exports the
            # single non-muted strip of each track (clip_selection mutes the
            # rest) and the active action, which clip_selection clears.
            return {"export_animations": True, "export_animation_mode": "ACTIONS"}, mode, ""
        return {"export_animations": True}, mode, ""
    if family == "usd":
        if mode == "none":
            return {"export_animation": False}, mode, ""
        warning = ("USD has no per-clip selection; every animation was exported."
                   if mode == "selected" else "")
        return {"export_animation": True}, mode, warning
    return {}, mode, ""
