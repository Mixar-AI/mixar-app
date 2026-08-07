# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Hunyuan 3D Module Constants

Centralized constants for the Hunyuan module: poll durations, file size
limits, face count defaults, and per-mode validation limits.
"""

# ============================================================================
# JOB QUEUE IDENTIFIERS
# ============================================================================

HUNYUAN_RAPID_JOB_TYPE = "hunyuan_rapid"
HUNYUAN_RAPID_MODEL = "hunyuan_rapid"

# Retopology engines. Hunyuan uses the "retopology" backend service; Tripo uses
# its own "retopology_tripo" service (independent concurrency) with model slug
# "tripo_v2". Both feed the same client-side retopology queue UI.
RETOPOLOGY_HUNYUAN_SERVICE = "retopology"
RETOPOLOGY_HUNYUAN_MODEL = "hunyuan_topology"
RETOPOLOGY_TRIPO_SERVICE = "retopology_tripo"
RETOPOLOGY_TRIPO_MODEL = "tripo_v2"

# Animate capability (Tripo v3 animations API). Service keys == job_queue
# job_types; models are catalog rows routed by model_ref on the backend.
ANIMATE_RIG_SERVICE = "tripo_rig"
ANIMATE_RIG_MODEL = "tripo_rig_v2_5"
ANIMATE_RETARGET_SERVICE = "tripo_retarget"
ANIMATE_RETARGET_MODEL = "tripo_retarget_v2_5"
# Custom property stamped on every object imported from an Auto Rig job;
# holds OUR queue job id (never Tripo's task id) — the retarget payload
# sends it and the backend resolves/authorizes the vendor task.
ANIMATE_RIG_JOB_PROP = "mixar_rig_job_id"

# Segmentation (Tripo v3 mesh APIs). Two services split by INPUT, not by
# endpoint: SEGMENT takes a mesh already in the scene (/v3/mesh/segment),
# SMART_SEGMENT takes a 2D image and both models AND segments it in one task
# (/v3/mesh/smartsegment). The backend routes each model row by model_ref.
SEGMENT_SERVICE = "tripo_segment"
SEGMENT_MODEL = "tripo_seg_v2"          # semantic + part labels (Beta)
SEGMENT_MODEL_GEOMETRY = "tripo_seg_v1"  # geometry only, unnamed parts
SMART_SEGMENT_SERVICE = "tripo_smart_segment"
SMART_SEGMENT_MODEL = "tripo_smartseg_v1"
# Collection suffix for a segmentation import; the source object is hidden
# rather than deleted so the split is non-destructive and comparable.
SEGMENT_PARTS_SUFFIX = "_parts"
# Stamped on every object imported from a segmentation job, holding OUR queue
# job id — lets the agent (and a later re-segment) recognise generated parts.
SEGMENT_JOB_PROP = "mixar_segment_job_id"

# ============================================================================
# POLL CONFIGURATION
# ============================================================================

# Client-side ceiling on the waiting-for-the-backend phase. It must stay >= the
# backend's own budgets (job_queue_configs: default_queue_timeout_s +
# default_execution_timeout_s), or the client cancels a job the user has already
# paid for while the backend is still working on it.
MAX_POLL_DURATION = 3600.0  # 60 minutes

# Maximum consecutive poll errors before marking job as FAILED
MAX_CONSECUTIVE_POLL_ERRORS = 5

# ============================================================================
# FILE SIZE LIMITS (bytes)
# ============================================================================

MAX_FILE_SIZE_PART = 100 * 1024 * 1024       # 100 MB
MAX_FILE_SIZE_TOPOLOGY = 200 * 1024 * 1024   # 200 MB
MAX_FILE_SIZE_TRIPO_RETOPOLOGY = 150 * 1024 * 1024  # 150 MB (Tripo mesh limit)
MAX_FILE_SIZE_ANIMATE_RIG = 150 * 1024 * 1024  # 150 MB (aligned with backend upload cap)
MAX_FILE_SIZE_SEGMENT = 150 * 1024 * 1024    # 150 MB (Tripo mesh limit)
MAX_FILE_SIZE_UV = 100 * 1024 * 1024         # 100 MB

# ============================================================================
# PROPERTY DEFAULTS
# ============================================================================

DEFAULT_FACE_COUNT = 500000

# ============================================================================
# PER-MODE VALIDATION LIMITS
# ============================================================================

LIMITS = {
    'PART': {'max_faces': 30000, 'max_mb': 100},
    'UV': {'max_faces': 30000, 'max_mb': 100},
    'TOPOLOGY': {'max_mb': 200},
}
