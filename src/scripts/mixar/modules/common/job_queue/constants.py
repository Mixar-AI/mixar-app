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

# ============================================================================
# RESULT DOWNLOAD
# ============================================================================

# Per-read socket timeout for the result transfer. Kept because it still kills
# a fully dead socket in ~2 min, but it is NOT a bound on the transfer: any
# trickle of bytes resets it on every chunk, which is exactly how a job sat in
# "Downloading…" for 10+ minutes in production. Deliberately not
# api.constants.HUNYUAN_TIMEOUT — that budgets a submit upload, not a download.
DOWNLOAD_SOCKET_TIMEOUT_S = 120.0

# Hard ceiling on ONE result transfer, spanning every retry attempt.
#
# Sizing: the biggest mesh this client ever moves is 200 MB (hunyuan
# MAX_FILE_SIZE_TOPOLOGY) and a textured Hunyuan Pro GLB comes back in the tens
# of MB. 600 s covers ~150 MB at 250 KB/s (a 2 Mbit/s effective home line) or
# ~50 MB at 85 KB/s. Slower than that floor is a stall, not a slow connection,
# and the user is better served by a failure they can retry than by an
# unbounded spinner holding a concurrency slot. It also keeps a job's whole
# worst case inside ~30 min, since MAX_POLL_DURATION (1200 s) is the other half.
DOWNLOAD_TOTAL_DEADLINE_S = 600.0

# Retry budget for one transfer. Connection resets, read timeouts, 5xx/408/429
# and truncated bodies are retried; a 4xx is not (a presigned S3 URL that 403s
# will keep 403ing, and re-deriving it client-side is not an option).
# Backoff is 2 s then 4 s, so retries add at most ~6 s of sleep. The retry loop
# SHARES DOWNLOAD_TOTAL_DEADLINE_S rather than extending it, so retrying can
# never push a transfer past the ceiling or outlive the presigned URL.
DOWNLOAD_MAX_ATTEMPTS = 3
DOWNLOAD_RETRY_BACKOFF_S = 2.0
DOWNLOAD_RETRY_BACKOFF_FACTOR = 2.0

# Read size. Every chunk boundary is also a cancel check and a deadline check,
# so this doubles as the granularity of both.
DOWNLOAD_CHUNK_BYTES = 8192

# Progress plumbing. The worker thread stamps byte counts onto the Job at most
# this often (plain attribute writes — never bpy, never _notify); a main-thread
# timer in FeatureQueue re-syncs the queue mirror every refresh interval and
# only when the byte count actually moved.
DOWNLOAD_PROGRESS_INTERVAL_S = 0.25
DOWNLOAD_PROGRESS_REFRESH_S = 0.5

# Main-thread watchdog for RUNNING_DOWNLOAD. Grace over the in-thread deadline
# so the worker's own error normally wins and this only fires when the thread
# died without registering either callback. Must exceed the 30 s watchdog tick
# granularity plus the retry backoff tail.
DOWNLOAD_WATCHDOG_DEADLINE_S = DOWNLOAD_TOTAL_DEADLINE_S + 120.0

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
    "DOWNLOAD_SOCKET_TIMEOUT_S",
    "DOWNLOAD_TOTAL_DEADLINE_S",
    "DOWNLOAD_MAX_ATTEMPTS",
    "DOWNLOAD_RETRY_BACKOFF_S",
    "DOWNLOAD_RETRY_BACKOFF_FACTOR",
    "DOWNLOAD_CHUNK_BYTES",
    "DOWNLOAD_PROGRESS_INTERVAL_S",
    "DOWNLOAD_PROGRESS_REFRESH_S",
    "DOWNLOAD_WATCHDOG_DEADLINE_S",
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
