# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""web_publish — publish the current scene as an explorable 3D website.

Exports the scene to a viewer-optimized GLB (Draco mesh compression, WEBP
textures), uploads it directly to storage through backend-presigned URLs, and
records the resulting shareable site on the scene. The public viewer is the
three.js app in the mixar-scene-viewer repo.

Module layout:
    core/publish_api.py    REST client for /scene-publish (thread-side)
    core/glb_export.py     Blender export + thumbnail + stats (main thread)
    core/upload_worker.py  Background publish pipeline (thread)
    core/publish_state.py  Thread-safe progress state + pure helpers
    ui/properties/         Scene-bound publish metadata (auto-registered)
    ui/operators/          Publish / update / unpublish / share operators
    ui/panels/             VIEW_3D N-panel "Web" tab
"""

from mixar.modules.web_publish.constants import (
    MAX_SCENE_BYTES,
    MIN_TITLE_LENGTH,
)

__all__ = ["MAX_SCENE_BYTES", "MIN_TITLE_LENGTH"]
