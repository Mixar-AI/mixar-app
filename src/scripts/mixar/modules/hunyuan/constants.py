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

# ============================================================================
# POLL CONFIGURATION
# ============================================================================

MAX_POLL_DURATION = 1200.0  # 20 minutes

# Maximum consecutive poll errors before marking job as FAILED
MAX_CONSECUTIVE_POLL_ERRORS = 5

# ============================================================================
# FILE SIZE LIMITS (bytes)
# ============================================================================

MAX_FILE_SIZE_PART = 100 * 1024 * 1024       # 100 MB
MAX_FILE_SIZE_TOPOLOGY = 200 * 1024 * 1024   # 200 MB
MAX_FILE_SIZE_TRIPO_RETOPOLOGY = 150 * 1024 * 1024  # 150 MB (Tripo mesh limit)
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
