# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The export targets: what each sidebar tile is, which logo it carries and
which file it writes. Pure data — no ``bpy``."""

from __future__ import annotations

from dataclasses import dataclass

from mixar.modules.common.i18n import n_

from .. import constants as C


@dataclass(frozen=True)
class Target:
    id: str
    tile: str          # the tile's label (a format name or extension: never translated)
    title: str         # the right column's caption (msgid)
    subtitle: str      # one line under it (msgid)
    logo: str          # assets/logos/<logo>.png
    group: str         # sidebar caption (msgid)


GROUP_PROJECT = n_("PROJECT")
GROUP_MODEL = n_("3D MODEL")
GROUP_MEDIA = n_("MEDIA & WEB")

TARGETS = (
    Target(C.MIXAR, ".mixar", n_("Mixar project"),
           n_("A copy of everything: scene, paint layers, moodboards and chat. Your open file "
              "stays as it is."), "mixar", GROUP_PROJECT),
    Target(C.BLEND, ".blend", n_("Blender file"),
           n_("Opens in Blender 5.2 or newer. Mixar-only data is kept but ignored there."),
           "blend", GROUP_PROJECT),
    Target(C.GLTF, "glTF", n_("glTF / GLB"),
           n_("The open standard for the web and real-time engines."), "gltf", GROUP_MODEL),
    Target(C.FBX, "FBX", n_("FBX"),
           n_("The game-engine workhorse, with rigs and animation."), "fbx", GROUP_MODEL),
    Target(C.USD, "USD", n_("USD / USDZ"),
           n_("Pixar's scene format. USDZ opens in Quick Look on iPhone and Vision Pro."),
           "usd", GROUP_MODEL),
    Target(C.OBJ, "OBJ", n_("OBJ"),
           n_("Geometry and materials only. Rigs and animation are left out."), "obj",
           GROUP_MODEL),
    Target(C.STL, "STL", n_("3D printing"),
           n_("One solid STL for slicers like Cura, PrusaSlicer and Bambu Studio."), "stl",
           GROUP_MODEL),
    Target(C.IMAGE, "PNG", n_("Image"),
           n_("A still render from a camera, made in the background."), "png", GROUP_MEDIA),
    Target(C.VIDEO, "MP4", n_("Video"),
           n_("An animation render from a camera, made in the background."), "mp4",
           GROUP_MEDIA),
    Target(C.WEB, "Web", n_("Publish to Web"),
           n_("An explorable three.js page of this scene, with a link you can share."), "web",
           GROUP_MEDIA),
)

BY_ID = {target.id: target for target in TARGETS}
GROUPS = (GROUP_PROJECT, GROUP_MODEL, GROUP_MEDIA)

# Engine chips: (use_case, label, logo). Labels are product names (never
# translated) except "Other".
ENGINE_CHIPS = (
    ('web', "three.js", "web"),
    ('unreal', "Unreal", "unreal"),
    ('unity', "Unity", "unity"),
    ('godot', "Godot", "godot"),
    ('ar', "Apple AR", "apple"),
    ('other', n_("Other"), ""),
)


def get(target_id: str) -> Target:
    return BY_ID.get(target_id, BY_ID[C.GLTF])


def in_group(group: str):
    return [target for target in TARGETS if target.group == group]


def model_format(target_id: str, gltf_file: str = 'GLB', usd_file: str = 'USDZ') -> str:
    """The export lane's ``format`` for a 3D target ('' for any other)."""
    if target_id == C.GLTF:
        return 'gltf' if gltf_file == 'GLTF' else 'glb'
    if target_id == C.USD:
        return 'usdc' if usd_file == 'USDC' else 'usdz'
    return {C.FBX: 'fbx', C.OBJ: 'obj', C.STL: 'stl'}.get(target_id, '')


def extension(target_id: str, gltf_file='GLB', usd_file='USDZ', render_format='PNG') -> str:
    """The file extension the target writes ('' for Publish to Web)."""
    if target_id in C.MODEL_TARGETS:
        return "." + model_format(target_id, gltf_file, usd_file)
    if target_id == C.MIXAR:
        return ".mixar"
    if target_id == C.BLEND:
        return ".blend"
    if target_id == C.IMAGE:
        return C.RENDER_EXTENSIONS.get(render_format, ".png")
    if target_id == C.VIDEO:
        return ".mp4"
    return ""
