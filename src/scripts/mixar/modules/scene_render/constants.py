# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Background scene-delivery protocol; no pixels or local paths leave the client."""
RESPONSE_NS = "mixar_scene_render_response"
RESULTS_NS = "mixar_scene_render_results"
MAX_RESULTS = 128
TICK_SECONDS = 0.2
LOST_AFTER_SECONDS = 3.0
