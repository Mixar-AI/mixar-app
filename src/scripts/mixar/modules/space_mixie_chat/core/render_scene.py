# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private scene the agent's preview renders, so the user's scene never changes.

The preview job used to apply its engine, world, sun, camera and size to the user's
own scene for the length of the render. A 3D view in Rendered shading follows the
scene engine, so every agent inspection flipped it to a Cycles viewport render: the
view went black ("Loading render kernels") and every object vanished for seconds,
then EEVEE re-initialised when the engine came back.

``create`` makes a linked copy (``Scene.copy``: objects, collections, world, camera,
view layers, frame, colour management and engine settings shared or copied; 0.4 ms
with a 300-message transcript). Every Python-registered scene property except the
render engines' own settings is reset on the copy at once, and the Mixar-owned custom
properties are removed, so no module that scans scenes mistakes it for the user's
chat session, history, moodboard or tab. It is tagged with ``INTERNAL_RENDER_SCENE_PROP``
(``is_internal_scene`` in ``constants``) for the scans that list or adopt scenes.

The copy shares the user's objects, so anything written to an object (the rig's
``hide_render``) still reaches the user's data and stays restored by the job.
"""

import bpy

from ..constants import INTERNAL_RENDER_SCENE_PROP, is_internal_scene

#: Sorts after every ASCII scene name, so code that takes "the first scene" never
#: lands on it even before it checks the tag.
RENDER_SCENE_NAME = "~Mixar agent render"
#: Render-engine settings groups registered from Python: kept on the copy.
_ENGINE_GROUPS = frozenset({"cycles", "cycles_curves"})
_MIXAR_KEY_PREFIXES = ("mixar_", "mixie_", "_mixar")
_BUILTIN_ENGINES = frozenset({"CYCLES", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"})


def _scrub(copy) -> None:
    for prop in bpy.types.Scene.bl_rna.properties:
        name = prop.identifier
        if name in _ENGINE_GROUPS or not getattr(prop, "is_runtime", False):
            continue
        try:
            copy.property_unset(name)
        except (TypeError, AttributeError, RuntimeError):
            pass
    for key in [k for k in copy.keys() if k.startswith(_MIXAR_KEY_PREFIXES)]:
        del copy[key]
    copy[INTERNAL_RENDER_SCENE_PROP] = True


def isolate_final(source) -> bool:
    """Whether an explicit final render can run in the private copy.

    Not when the scene composites: its compositor node group is shared and a Render
    Layers node there names the user's scene, which would make the job render that
    scene as well. Not for a third-party engine whose settings may live in properties
    the copy resets. Those renders keep running on the user's scene as before.
    """
    if str(source.render.engine) not in _BUILTIN_ENGINES:
        return False
    composites = bool(source.render.use_compositing) and getattr(
        source, "compositing_node_group", None) is not None
    return not composites


def create(source, *, inspection: bool):
    """Linked copy of ``source`` for one preview job.

    The inspection rig owns its look (neutral world, sun, Cycles or Workbench), so
    the copy drops the compositor and the sequencer, which would otherwise replace
    or post-process the 3D render.
    """
    sweep()
    copy = source.copy()
    _scrub(copy)
    copy.name = RENDER_SCENE_NAME
    # Persistent Data would keep the whole engine and its device memory alive in
    # the copy's Render; it is freed with the scene (rna_main_api.cc) either way.
    copy.render.use_persistent_data = False
    if inspection:
        copy.render.use_compositing = False
        copy.render.use_sequencer = False
    return copy


def remove(scene) -> None:
    """Delete a private render scene. A scene already freed (undo, file load) is fine."""
    if scene is None:
        return
    try:
        if is_internal_scene(scene):
            bpy.data.scenes.remove(scene, do_unlink=True)
    except (ReferenceError, RuntimeError):
        pass


def sweep(keep=None) -> int:
    """Remove every private render scene except ``keep``.

    Undo, a checkpoint restore or a file saved mid-render can bring one back after
    its job ended. Returns how many were removed.
    """
    removed = 0
    for scene in [s for s in bpy.data.scenes if is_internal_scene(s)]:
        try:
            if keep is not None and scene == keep:
                continue
        except ReferenceError:
            pass
        remove(scene)
        removed += 1
    return removed
