# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene-level PropertyGroups for asset-search training, search, and reuse.

Split out of asset_train_ops so properties register in bootstrap's
properties pass (priority 0), before the operators and panel that use them.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


def _enrolled_update(self, context):
    """Persist a library tick to the per-user enrollment file."""
    from mixar.modules.asset_search.core.library_enrollment import set_enrolled
    set_enrolled(self.name, self.enabled)


class MixieAssetLibraryItem(PropertyGroup):
    """One registered asset library in the 'Libraries to Train' list."""

    name: StringProperty(name="Library", default="")
    path: StringProperty(name="Path", default="", subtype='DIR_PATH')
    asset_count: IntProperty(name="Assets", default=-1)  # -1 = not counted yet
    enabled: BoolProperty(
        name="Train",
        description="Include this library when training the asset search model",
        default=False,
        update=_enrolled_update,
    )


class MixieAssetSearchResult(PropertyGroup):
    """One structured search hit (name/score/library) for the results list."""

    name: StringProperty(name="Asset Name", default="")
    score: FloatProperty(name="Similarity", default=0.0, min=0.0, max=1.0)
    library: StringProperty(name="Library", default="")
    blend_file: StringProperty(name="Blend File", default="")
    asset_type: StringProperty(name="Type", default="")


class MixieAssetTrainingState(PropertyGroup):
    """Scene-level properties tracking asset training progress."""

    is_training: BoolProperty(name="Is Training", default=False)
    progress: FloatProperty(
        name="Training Progress", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
    )
    # -- Real-time progress detail (all display-only, written by the modal) --
    phase_text: StringProperty(name="Phase", default="")
    current_item: StringProperty(name="Current Item", default="")
    assets_done: IntProperty(name="Assets Done", default=0)
    assets_total: IntProperty(name="Assets Total", default=0)
    upload_done: IntProperty(name="Batches Uploaded", default=0)
    upload_total: IntProperty(name="Upload Batches", default=0)
    eta_text: StringProperty(name="ETA", default="")
    prepare_note: StringProperty(name="Prepare Summary", default="")
    failed_count: IntProperty(name="Failed Count", default=0)
    failed_list: StringProperty(name="Failed Assets", default="")
    show_failures: BoolProperty(
        name="Show Skipped",
        description="List the assets that could not be rendered/embedded",
        default=False,
    )
    cancel_requested: BoolProperty(name="Cancel Requested", default=False)
    # -- Persistent terminal summary (survives until the next run) --
    last_summary: StringProperty(name="Last Run Summary", default="")
    last_summary_success: BoolProperty(name="Last Run OK", default=True)
    # Client-side stamp of the last successful training (idle status block).
    last_trained_at: StringProperty(name="Last Trained", default="")

    search_prompt: StringProperty(name="Search", default="")
    search_results: CollectionProperty(type=MixieAssetSearchResult)
    needs_retraining: BoolProperty(name="Needs Retraining", default=False)
    retraining_message: StringProperty(name="Retraining Message", default="")
    search_message: StringProperty(name="Search Message", default="")
    is_searching: BoolProperty(name="Is Searching", default=False)
    is_refreshing: BoolProperty(name="Is Refreshing", default=False)
    has_model: BoolProperty(name="Has Trained Model", default=False)
    auto_check_done: BoolProperty(name="Auto Check Done", default=False)
    search_image: PointerProperty(type=bpy.types.Image, name="Search Image")
    match_threshold: FloatProperty(
        name="Match Threshold",
        description=(
            "Similarity cutoff (0-1) the modelling agent uses to reuse an asset "
            "from your library instead of modelling it from scratch. Higher = only "
            "very close matches are reused"
        ),
        default=0.7, min=0.0, max=1.0, subtype='FACTOR',
    )


classes = (
    MixieAssetLibraryItem,
    MixieAssetSearchResult,
    MixieAssetTrainingState,
)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)
    bpy.types.Scene.mixie_asset_training = bpy.props.PointerProperty(
        type=MixieAssetTrainingState,
    )
    # Enrollment list is per-user/session state — WindowManager, not saved
    # into the .blend (rebuilt from the enrollment config on demand).
    bpy.types.WindowManager.mixie_asset_libraries = bpy.props.CollectionProperty(
        type=MixieAssetLibraryItem,
    )
    bpy.types.WindowManager.mixie_asset_libraries_index = bpy.props.IntProperty(
        name="Active Library", default=0,
    )


def unregister():
    from bpy.utils import unregister_class
    for attr in ("mixie_asset_libraries", "mixie_asset_libraries_index"):
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)
    if hasattr(bpy.types.Scene, 'mixie_asset_training'):
        del bpy.types.Scene.mixie_asset_training
    for cls in reversed(classes):
        unregister_class(cls)
