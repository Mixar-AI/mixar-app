# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""web_publish module constants."""

# Upload policy (mirrors backend SCENE_PUBLISH_* settings; the backend remains
# authoritative — these only gate the UI earlier for a clearer error message).
MAX_SCENE_BYTES = 200 * 1024 * 1024
MAX_THUMBNAIL_BYTES = 5 * 1024 * 1024

# Multipart upload tuning
UPLOAD_PART_SIZE = 8 * 1024 * 1024  # backend: DEFAULT_PART_SIZE — keep in sync
UPLOAD_TIMEOUT_SECONDS = 300  # per part / per PUT
API_TIMEOUT_SECONDS = 30
UPLOAD_RETRIES_PER_PART = 3
RETRY_BACKOFF_SECONDS = 1.5
GLB_CONTENT_TYPE = "model/gltf-binary"

# Export: the shared agent export lane with the web_publish profile
# (space_mixie_chat/core/export_presets.PROFILES).
EXPORT_USE_CASE = "web"
EXPORT_FORMAT = "glb"
EXPORT_SCOPE = "scene"
EXPORT_PROFILE = "web_publish"
EXPORT_TELEMETRY_VIA = "web_publish"
EXPORT_TELEMETRY_TOOL = "publish_to_web"
GLB_EXPORT_FILENAME = "scene.glb"
WORKSPACE_PREFIX = "mixar_web_publish_"

# Thumbnail (best-effort; skipped while a window resizes or a render runs)
THUMBNAIL_FILENAME = "thumbnail.png"
THUMBNAIL_RESOLUTION = (640, 360)
THUMBNAIL_RENDER_OWNER = "web-publish:thumbnail"

# UI / polling
STATE_POLL_INTERVAL_SECONDS = 0.2
TITLE_MAX_LENGTH = 140
DESCRIPTION_MAX_LENGTH = 2000
VISIBILITIES = ("public", "unlisted")
