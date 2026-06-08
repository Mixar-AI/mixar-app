# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
API Service modules.

Provides service classes for each API module with singleton accessors.
"""

from .agent_service import AgentService, get_agent_service
from .auth_service import AuthService, get_auth_service
from .base_service import BaseService
from .images_service import ImagesService, get_images_service
from .generation_metadata_service import GenerationMetadataService, get_generation_metadata_service
from .scene_recon_service import SceneReconService, get_scene_recon_service
from .scene_segment_service import SceneSegmentService, get_scene_segment_service
from .update_service import UpdateService, get_update_service
from .generation_queue_service import GenerationQueueService, get_generation_queue_service

__all__ = [
    # Base
    "BaseService",
    # Auth
    "AuthService",
    "get_auth_service",
    # Agent
    "AgentService",
    "get_agent_service",
    # Images
    "ImagesService",
    "get_images_service",
    # Generation Metadata (models/styles listing)
    "GenerationMetadataService",
    "get_generation_metadata_service",
    # Scene Reconstruction
    "SceneReconService",
    "get_scene_recon_service",
    # Scene Segment (SAM3)
    "SceneSegmentService",
    "get_scene_segment_service",
    # Updates
    "UpdateService",
    "get_update_service",
    # Feature Gen Queue
    "GenerationQueueService",
    "get_generation_queue_service",
]
