# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the job queue framework."""

# Re-export poll constants from hunyuan to keep one source of truth.
from mixar.modules.hunyuan.constants import (
    MAX_POLL_DURATION,
    MAX_CONSECUTIVE_POLL_ERRORS,
)

# Auth watcher poll interval (seconds)
AUTH_RETRY_INTERVAL_S = 5.0

# Feature keys
FEATURE_IMAGE_TO_3D_PRO = "image_to_3d_pro"
FEATURE_RETOPOLOGY = "retopology"
FEATURE_ANIMATE = "animate"
FEATURE_SCENE_GEN_HP = "scene_gen_hp"
FEATURE_SCENE_GEN_LP = "scene_gen_lp"
FEATURE_HUNYUAN_RAPID = "hunyuan_rapid"
FEATURE_HUNYUAN_PART = "hunyuan_part"
FEATURE_HUNYUAN_UV = "hunyuan_uv"
FEATURE_MODEL_3D = "model_3d"
FEATURE_IMAGEGEN = "imagegen"
FEATURE_LOOKDEV360 = "lookdev360"
FEATURE_SCENE_GEN = "scene_gen"
FEATURE_MESH_SEGMENT = "mesh_segment"
# Tripo segmentation. Separate queues from FEATURE_MESH_SEGMENT (Jasper) so a
# Tripo job and a Jasper job on the same mesh don't collide on queue dedup,
# which keys on the job label.
FEATURE_TRIPO_SEGMENT = "tripo_segment"
FEATURE_SMART_SEGMENT = "smart_segment"
FEATURE_SCENE_RECON = "scene_recon"
FEATURE_MATGEN = "matgen"
FEATURE_BRUSH_GEN = "brush_gen"
FEATURE_LOOKDEV = "lookdev"
FEATURE_SCENE_GEN_EXP_LABELS = "scene_gen_exp_labels"

# Enqueue toast — transient "generation queued" viewport feedback.
# One stable id so bursts collapse into a single counting toast; the TTL is
# also the burst window (a re-push resets the store item's created_at).
ENQUEUE_TOAST_ID = "jobq_enqueued"
ENQUEUE_TOAST_TTL_MS = 8000

# Logging prefix
LOG_PREFIX = "[JobQueue]"

__all__ = (
    "MAX_POLL_DURATION",
    "MAX_CONSECUTIVE_POLL_ERRORS",
    "AUTH_RETRY_INTERVAL_S",
    "FEATURE_IMAGE_TO_3D_PRO",
    "FEATURE_RETOPOLOGY",
    "FEATURE_SCENE_GEN_HP",
    "FEATURE_SCENE_GEN_LP",
    "FEATURE_HUNYUAN_RAPID",
    "FEATURE_HUNYUAN_PART",
    "FEATURE_HUNYUAN_UV",
    "FEATURE_MODEL_3D",
    "FEATURE_IMAGEGEN",
    "FEATURE_LOOKDEV360",
    "FEATURE_SCENE_GEN",
    "FEATURE_MESH_SEGMENT",
    "FEATURE_SCENE_RECON",
    "FEATURE_MATGEN",
    "FEATURE_BRUSH_GEN",
    "FEATURE_LOOKDEV",
    "FEATURE_SCENE_GEN_EXP_LABELS",
    "ENQUEUE_TOAST_ID",
    "ENQUEUE_TOAST_TTL_MS",
    "LOG_PREFIX",
)
