# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
API Client Module Constants

Centralized configuration values for the REST API client.
"""

from enum import Enum

# ============================================================================
# HTTP CONFIGURATION DEFAULTS
# ============================================================================

DEFAULT_TIMEOUT = 30.0  # seconds
DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_DELAY = 1.0  # seconds
DEFAULT_RETRY_BACKOFF = 2.0  # exponential multiplier
MAX_RETRY_DELAY = 30.0  # seconds

# Connection pool settings
POOL_CONNECTIONS = 10
POOL_MAXSIZE = 10

# ============================================================================
# ASYNC/BACKGROUND EXECUTION CONFIGURATION
# ============================================================================

# Thread pool settings
DEFAULT_POOL_SIZE = 4  # Number of background worker threads
MAX_POOL_SIZE = 10  # Maximum allowed pool size

# Queue processing settings
DEFAULT_POLL_INTERVAL = 0.05  # 50ms - how often to check response queue
MAX_RESPONSES_PER_TICK = 10  # Max responses to process per timer tick
CALLBACK_CLEANUP_INTERVAL = 30.0  # Seconds between expired callback cleanup

# Request settings
DEFAULT_QUEUE_TIMEOUT = 60.0  # Default timeout for async requests

# ============================================================================
# API ENDPOINTS (Base paths - version prefix added by services)
# ============================================================================

API_VERSION = "v1"


class APIModule(Enum):
    """API module base paths."""

    AGENT = "agent"
    AUTHENTICATION = "auth"
    IMAGES = "images"
    IMAGEGEN = "image-generation"
    LOOKDEV = "lookdev"
    MESH_SEGMENT = "mesh-segment"
    MODEL_3D_GEN = "model-3d-generation"
    PBR_GENERATION = "pbr-generation"
    SCENE_GEN = "scene-gen"
    SCENE_RECONSTRUCTION = "scene-reconstruction"
    SCENE_SEGMENT = "scene-segment"
    HUNYUAN = "hunyuan"
    UPDATES = "updates"
    JOB_QUEUE = "job-queue"
    GENERATION_CATALOG = "generation-catalog"


# ============================================================================
# HTTP METHODS
# ============================================================================


class HTTPMethod(Enum):
    """Supported HTTP methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


# ============================================================================
# CONTENT TYPES
# ============================================================================

CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_FORM = "application/x-www-form-urlencoded"
CONTENT_TYPE_MULTIPART = "multipart/form-data"

# ============================================================================
# SERVICE TIMEOUTS
# ============================================================================

# Brush texture generation can take 60+ seconds
BRUSH_GEN_TIMEOUT = 120.0

# Hunyuan submit calls can take a while to upload files
HUNYUAN_TIMEOUT = 120.0
