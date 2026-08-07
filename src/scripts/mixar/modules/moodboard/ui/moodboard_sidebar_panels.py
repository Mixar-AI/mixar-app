# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Generative Sidebar Panels — Native N-Panel System

Independent Panel classes, each registered under its own bl_category
so they appear as separate vertical tabs in the sidebar — just like
Item / Tool / View in the 3D Viewport N-panel.

Tab structure (Stage 3)
-----------------------
One panel per generation-catalog capability, in catalog sort order:
Image Gen, AI Render, Model Gen, Texture Gen, Scene Gen, Retopology,
UV Unwrapping, Mesh Segmentation — plus the Queue utility panel (not a
capability; ``mixie.queue_view`` keys on its "Queue" category). AI
Render is catalog-only (no offline fallback): its panel hides unless the
loaded catalog has ``ai_render`` services.

Design decision — catalog-driven labels, two resolution points:
Blender consumes ``bl_category``/``bl_label`` once at class registration
(there is no draw-time callback for tab names), so dynamic labels work
in two stages. (1) At module load — after the bootstrap has already
loaded the persisted catalog payload — each capability panel's label is
resolved through ``generation_catalog_cache.get_capability_label``; the
hardcoded strings in ``_CAPABILITY_TABS`` are only the offline/pre-auth
fallbacks. (2) When a catalog revalidation swaps in a payload with a
renamed capability label, ``refresh_tab_labels()`` (invoked from the
cache's main-thread swap callback) unregisters and re-registers ONLY the
affected panel classes with the new label — a rare event, so losing that
panel's expand state at that moment is acceptable. ``bl_idname``s never
change (the tour driver and other code key on them). Other modules that
switch ``region.active_panel_category`` to a capability tab must resolve
the category through ``get_tab_category()`` instead of a literal.
Everything inside each panel — mode selector, model dropdowns, schema
params — is catalog-driven, and each panel's ``poll()`` hides the tab
when the loaded catalog has no moodboard services for its capability
(i.e. a capability disabled in the DB hides its tab). When the catalog
isn't loaded (offline / pre-auth) the legacy tabs show their fallback
UIs so the sidebar never goes blank.
"""

from bpy.types import Panel

from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE
from mixar.config.logging_config import get_logger

from .sidebar_panel_drawers import (
    _draw_imagegen,
    _draw_lookdev360,
    _draw_image_to_3d,
    _draw_scene_gen_exp,
    _draw_queue,
)
from .sidebar_tab_drawers import (
    _draw_mesh_segment,
    _draw_retopology,
    _draw_uv_unwrap,
)
from .ai_render_drawer import _draw_ai_render
from .animate_drawer import _draw_animate
from .scene_gen_drawer import _draw_scene_gen
from .video_gen_drawer import _draw_video_gen

logger = get_logger(__name__)


def _moodboard_poll(context):
    """Shared poll: require MIXIE space in MOODBOARD mode."""
    if not MIXIE_SPACE_AVAILABLE:
        return False
    smixie = context.space_data
    return smixie and hasattr(smixie, 'mixie_mode') and smixie.mixie_mode == 'MOODBOARD'


def _capability_visible(capability_key):
    """Whether a capability's tab should be visible.

    True when the catalog isn't loaded (offline / pre-auth — every tab
    renders its fallback UI) or when the loaded catalog has at least one
    moodboard-surfaced service for the capability. A capability disabled
    in the DB therefore hides its tab.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_services, is_loaded,
        )
        if not is_loaded():
            return True
        return bool(get_services(capability_key))
    except Exception:
        return True


def _safe_draw(drawer, layout, context):
    """Call a drawer function with error handling."""
    try:
        drawer(layout, context)
    except Exception as e:
        logger.exception("Panel drawer raised an exception")
        layout.label(text=f"Error: {e}", icon='ERROR')


# ---------------------------------------------------------------------------
# Panel classes — each bl_category = separate vertical tab.
# The class-body bl_label/bl_category strings are the offline fallbacks;
# _apply_catalog_labels() below overwrites them from the loaded catalog
# before registration, and refresh_tab_labels() re-registers renamed
# tabs after a catalog swap (see module docstring).
# ---------------------------------------------------------------------------

class MIXIE_PT_gen_imagegen(Panel):
    # Capability "image_gen" — Text to Image / From Blockout modes.
    bl_label = "Image Gen"
    bl_idname = "MIXIE_PT_gen_imagegen"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Image Gen"
    bl_order = 10
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context) and _capability_visible("image_gen")

    def draw_header(self, context):
        self.layout.label(text="", icon='IMAGE_DATA')

    def draw(self, context):
        _safe_draw(_draw_imagegen, self.layout, context)


class MIXIE_PT_gen_ai_render(Panel):
    # Capability "ai_render" — hosts depth_to_image (From Blockout) when
    # the catalog routes it here. Unlike the seven legacy tabs, this one
    # has NO offline fallback identity: it only exists as a catalog
    # capability, so poll() requires the catalog to be loaded AND to have
    # moodboard services for it (pre-move / reverted DBs hide the tab).
    bl_label = "AI Render"
    bl_idname = "MIXIE_PT_gen_ai_render"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "AI Render"
    bl_order = 15
    bl_options = set()

    @classmethod
    def poll(cls, context):
        if not _moodboard_poll(context):
            return False
        try:
            from mixar.bootstrap.generation_catalog_cache import (
                get_services, is_loaded,
            )
            return is_loaded() and bool(get_services("ai_render"))
        except Exception:
            return False

    def draw_header(self, context):
        self.layout.label(text="", icon='RESTRICT_RENDER_OFF')

    def draw(self, context):
        _safe_draw(_draw_ai_render, self.layout, context)


class MIXIE_PT_gen_video_gen(Panel):
    # Catalog-only capability. Seedance 2.5 remains hidden while its catalog
    # model is disabled; the enabled Seedance 2 models route through Seevio.
    bl_label = "Video Gen"
    bl_idname = "MIXIE_PT_gen_video_gen"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Video Gen"
    bl_order = 18
    bl_options = set()

    @classmethod
    def poll(cls, context):
        if not _moodboard_poll(context):
            return False
        try:
            from mixar.bootstrap.generation_catalog_cache import (
                get_services, is_loaded,
            )
            return is_loaded() and bool(get_services("video_gen"))
        except Exception:
            return False

    def draw_header(self, context):
        self.layout.label(text="", icon='FILE_MOVIE')

    def draw(self, context):
        _safe_draw(_draw_video_gen, self.layout, context)


class MIXIE_PT_gen_image_to_3d(Panel):
    # Capability "model_gen" — Image to 3D / Image to 3D Pro / Rapid 3D
    # modes. bl_idname kept stable — other code keys on it (tour driver).
    bl_label = "Model Gen"
    bl_idname = "MIXIE_PT_gen_image_to_3d"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Model Gen"
    bl_order = 20
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context) and _capability_visible("model_gen")

    def draw_header(self, context):
        self.layout.label(text="", icon='VIEW3D')

    def draw(self, context):
        _safe_draw(_draw_image_to_3d, self.layout, context)


class MIXIE_PT_gen_lookdev360(Panel):
    # Capability "texture_gen" — PBR Textures / Texture Edit /
    # Procedural Material modes. bl_idname kept stable.
    bl_label = "Texture Gen"
    bl_idname = "MIXIE_PT_gen_lookdev360"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Texture Gen"
    bl_order = 30
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context) and _capability_visible("texture_gen")

    def draw_header(self, context):
        self.layout.label(text="", icon='SPHERE')

    def draw(self, context):
        _safe_draw(_draw_lookdev360, self.layout, context)


class MIXIE_PT_gen_scene_recon(Panel):
    # Capability "scene_gen" — Scene Reconstruction / Segments to 3D
    # modes. bl_idname kept stable — other code keys on it.
    bl_label = "Scene Gen"
    bl_idname = "MIXIE_PT_gen_scene_recon"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Scene Gen"
    bl_order = 40
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context) and _capability_visible("scene_gen")

    def draw_header(self, context):
        self.layout.label(text="", icon='SCENE_DATA')

    def draw(self, context):
        _safe_draw(_draw_scene_gen, self.layout, context)


class MIXIE_PT_gen_retopology(Panel):
    # Capability "retopology" — Hunyuan / Tripo engines.
    bl_label = "Retopology"
    bl_idname = "MIXIE_PT_gen_retopology"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Retopology"
    bl_order = 50
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context) and _capability_visible("retopology")

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_REMESH')

    def draw(self, context):
        _safe_draw(_draw_retopology, self.layout, context)


class MIXIE_PT_gen_uv_unwrap(Panel):
    # Capability "uv_unwrapping" — Hunyuan UV flow (scene.hunyuan.uv).
    bl_label = "UV Unwrapping"
    bl_idname = "MIXIE_PT_gen_uv_unwrap"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "UV Unwrapping"
    bl_order = 60
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context) and _capability_visible("uv_unwrapping")

    def draw_header(self, context):
        self.layout.label(text="", icon='UV')

    def draw(self, context):
        _safe_draw(_draw_uv_unwrap, self.layout, context)


class MIXIE_PT_gen_mesh_segment(Panel):
    # Capability "mesh_segmentation" — Mesh Segmentation / Part
    # Segmentation modes.
    bl_label = "Mesh Segmentation"
    bl_idname = "MIXIE_PT_gen_mesh_segment"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mesh Segmentation"
    bl_order = 70
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context) and _capability_visible("mesh_segmentation")

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_MASK')

    def draw(self, context):
        _safe_draw(_draw_mesh_segment, self.layout, context)


class MIXIE_PT_gen_animate(Panel):
    # Capability "animate" — Auto Rig (Tripo). Catalog-only, like AI
    # Render: no offline fallback identity, so poll() requires the catalog
    # to be loaded AND to have animate services (disabling the capability
    # in the DB hides the tab). bl_idname kept stable across the rename to
    # "Auto Rig" to avoid breaking references.
    bl_label = "Auto Rig"
    bl_idname = "MIXIE_PT_gen_animate"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Auto Rig"
    bl_order = 75
    bl_options = set()

    @classmethod
    def poll(cls, context):
        if not _moodboard_poll(context):
            return False
        try:
            from mixar.bootstrap.generation_catalog_cache import (
                get_services, is_loaded,
            )
            return is_loaded() and bool(get_services("animate"))
        except Exception:
            return False

    def draw_header(self, context):
        self.layout.label(text="", icon='ARMATURE_DATA')

    def draw(self, context):
        _safe_draw(_draw_animate, self.layout, context)


class MIXIE_PT_gen_scene_gen_exp(Panel):
    bl_label = "Scene Gen Experimental"
    bl_idname = "MIXIE_PT_gen_scene_gen_exp"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Scene Gen Exp"
    bl_order = 45
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context)

    def draw_header(self, context):
        self.layout.label(text="", icon='EXPERIMENTAL')

    def draw(self, context):
        _safe_draw(_draw_scene_gen_exp, self.layout, context)


class MIXIE_PT_gen_queue(Panel):
    # Utility panel (not a catalog capability) — ``mixie.queue_view``
    # switches the sidebar to this category.
    bl_label = "Queue"
    bl_idname = "MIXIE_PT_gen_queue"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Queue"
    bl_order = 80

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context)

    def draw_header(self, context):
        self.layout.label(text="", icon='LINENUMBERS_ON')

    def draw(self, context):
        _safe_draw(_draw_queue, self.layout, context)


# ---------------------------------------------------------------------------
# Catalog-driven tab labels — machinery lives in moodboard_tab_labels;
# the mapping stays here, next to the classes. get_tab_category and
# refresh_tab_labels are re-exported so consumers (catalog cache swap
# hook, sidebar_ui_helpers, director handoff, onboarding tour) have one
# import point.
# ---------------------------------------------------------------------------

from .moodboard_tab_labels import (  # noqa: E402
    apply_catalog_labels as _apply_catalog_labels,
    get_tab_category,
    init_capability_tabs as _init_capability_tabs,
    refresh_tab_labels,
)

# Declarative map: capability key -> (panel class, offline fallback label).
# The Queue panel is a utility, not a capability — its label stays static.
_init_capability_tabs({
    "image_gen": (MIXIE_PT_gen_imagegen, "Image Gen"),
    "ai_render": (MIXIE_PT_gen_ai_render, "AI Render"),
    "video_gen": (MIXIE_PT_gen_video_gen, "Video Gen"),
    "model_gen": (MIXIE_PT_gen_image_to_3d, "Model Gen"),
    "texture_gen": (MIXIE_PT_gen_lookdev360, "Texture Gen"),
    "scene_gen": (MIXIE_PT_gen_scene_recon, "Scene Gen"),
    "retopology": (MIXIE_PT_gen_retopology, "Retopology"),
    "uv_unwrapping": (MIXIE_PT_gen_uv_unwrap, "UV Unwrapping"),
    "mesh_segmentation": (MIXIE_PT_gen_mesh_segment, "Mesh Segmentation"),
    "animate": (MIXIE_PT_gen_animate, "Auto Rig"),
})

# Resolve labels from the already-loaded persisted catalog before the
# classes tuple below is auto-registered (offline: fallbacks stand).
_apply_catalog_labels()


# Only register if MIXIE space is available.
classes = (
    MIXIE_PT_gen_imagegen,
    MIXIE_PT_gen_ai_render,
    MIXIE_PT_gen_video_gen,
    MIXIE_PT_gen_image_to_3d,
    MIXIE_PT_gen_lookdev360,
    MIXIE_PT_gen_scene_recon,
    MIXIE_PT_gen_retopology,
    MIXIE_PT_gen_uv_unwrap,
    MIXIE_PT_gen_mesh_segment,
    MIXIE_PT_gen_animate,
    # MIXIE_PT_gen_scene_gen_exp,  # Scene Gen Experimental disabled
    MIXIE_PT_gen_queue,
) if MIXIE_SPACE_AVAILABLE else ()
