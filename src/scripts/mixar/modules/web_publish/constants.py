# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""web_publish module constants."""

# API surface (scene_publish backend module)
API_BASE_PATH = "api/v1/scene-publish"
ENDPOINT_SCENES = "scenes"
ENDPOINT_COMPLETE = "complete"
ENDPOINT_THUMBNAIL = "thumbnail"
ENDPOINT_QUOTA = "quota"

# Upload policy (mirrors backend SCENE_PUBLISH_* settings; the backend remains
# authoritative — these only gate the UI earlier for a clearer error message).
MAX_SCENE_BYTES = 200 * 1024 * 1024
MAX_THUMBNAIL_BYTES = 5 * 1024 * 1024
SIMPLE_PUT_THRESHOLD = 16 * 1024 * 1024  # backend: single presigned PUT below this

# Multipart upload tuning
UPLOAD_PART_SIZE = 8 * 1024 * 1024  # backend: DEFAULT_PART_SIZE — keep in sync
UPLOAD_TIMEOUT_SECONDS = 300  # per part / per PUT
API_TIMEOUT_SECONDS = 30
UPLOAD_RETRIES_PER_PART = 3
RETRY_BACKOFF_SECONDS = 1.5

# Export
GLB_EXPORT_FILENAME = "scene.glb"
THUMBNAIL_FILENAME = "thumbnail.png"
THUMBNAIL_RESOLUTION = (640, 360)
DRACO_COMPRESSION_LEVEL = 6

# UI / polling
STATE_POLL_INTERVAL_SECONDS = 0.2
TITLE_MIN_LENGTH = 1
MIN_TITLE_LENGTH = TITLE_MIN_LENGTH  # clearer alias for operator checks
TITLE_MAX_LENGTH = 140
DESCRIPTION_MAX_LENGTH = 2000

# Viewer config camera defaults (relative to scene bounding sphere)
CAMERA_DISTANCE_FACTOR = 1.9
CAMERA_HEIGHT_FACTOR = 0.55

ANALYTICS_EVENT_PUBLISH = "web_publish.submitted"
ANALYTICS_EVENT_PUBLISH_OK = "web_publish.completed"
ANALYTICS_EVENT_PUBLISH_FAIL = "web_publish.failed"
