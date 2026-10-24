# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish to Web: the current scene as an explorable three.js website.

The GLB comes from the shared agent export lane (``web`` preset plus the
``web_publish`` profile: Draco, WebP); a worker thread uploads it straight
to storage through backend-presigned URLs (``/api/v1/scene-publish``); the
public viewer is the mixar-scene-viewer app. The panel operator and the
agent (``core/agent_api.py``) share one pipeline (``core/pipeline.py``).
"""
