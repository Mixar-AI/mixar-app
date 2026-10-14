# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Background scene-delivery protocol; no pixels or local paths leave the client."""
RESPONSE_NS = "mixar_scene_render_response"
RESULTS_NS = "mixar_scene_render_results"
MAX_RESULTS = 128
TICK_SECONDS = 0.2
LOST_AFTER_SECONDS = 3.0
# Advertised in the WebSocket handshake: the backend passes ``agent_ref_json``
# to ``mixar.scene_render_start`` only on a client that advertises it, because
# an older operator rejects unknown kwargs.
CALLBACKS_CAPABILITY = "scene_render_callbacks_v1"
# ``generation.agent_result`` identity for scene renders (no job-queue entry).
CALLBACK_FEATURE_KEY = "scene_render"
CALLBACK_JOB_TYPES = {"image": "scene_render_image", "video": "scene_render_video"}
CALLBACK_STATUSES = {"done": "succeeded", "cancelled": "cancelled", "failed": "failed"}
