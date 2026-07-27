# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Asset Search Module Constants

API endpoint paths for the asset search backend.
"""

# ============================================================================
# ASSET SEARCH API ENDPOINTS
# ============================================================================

ASSET_SEARCH_ENDPOINT = "api/v1/asset-search/search"
ASSET_SEARCH_BATCH_ENDPOINT = "api/v1/asset-search/search-batch"
ASSET_STATUS_ENDPOINT = "api/v1/asset-search/status"
ASSET_TRAIN_PREPARE_ENDPOINT = "api/v1/asset-search/train/prepare"
ASSET_TRAIN_ENDPOINT = "api/v1/asset-search/train"
ASSET_EMBEDDINGS_DELETE_ENDPOINT = "api/v1/asset-search/embeddings"

# ============================================================================
# AUTO-CURATED "MIXAR GENERATIONS" LIBRARY
# ============================================================================

# Display name of the Mixar-owned asset library (shown in the Asset Browser and
# used as the `library` identity in embedding metadata). Registered at startup.
GENERATION_LIBRARY_NAME = "Mixar Generations"
# Sub-path under user_resource('DATAFILES', ...) where the library .blends live.
GENERATION_LIBRARY_SUBPATH = "mixar/generations"

# Job types whose completed 3D result is auto-archived into the library.
# ONLY pure image->3D model generations — no retopology / rapid / uv / part /
# scene-gen / auto-rig. Values match AsyncGLBJob.job_type (== backend service).
GENERATION_LIBRARY_JOB_TYPES = frozenset({"image_to_3d", "model_3d"})
