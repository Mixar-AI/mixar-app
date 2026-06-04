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
FEATURE_SCENE_GEN_HP = "scene_gen_hp"
FEATURE_SCENE_GEN_LP = "scene_gen_lp"

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
    "LOG_PREFIX",
)
