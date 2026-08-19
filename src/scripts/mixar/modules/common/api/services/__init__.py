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
from .generation_catalog_service import GenerationCatalogService, get_generation_catalog_service
from .model_3d_service import Model3DService, get_model_3d_service
from .scene_recon_service import SceneReconService, get_scene_recon_service
from .scene_segment_service import SceneSegmentService, get_scene_segment_service
from .update_service import UpdateService, get_update_service
from .job_queue_service import JobQueueService, get_job_queue_service
from .subscription_service import SubscriptionService, get_subscription_service

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
    # Generation Catalog (unified capability/service/model catalog)
    "GenerationCatalogService",
    "get_generation_catalog_service",
    # Model 3D (turnaround view detection)
    "Model3DService",
    "get_model_3d_service",
    # Scene Reconstruction
    "SceneReconService",
    "get_scene_recon_service",
    # Scene Segment (SAM3)
    "SceneSegmentService",
    "get_scene_segment_service",
    # Updates
    "UpdateService",
    "get_update_service",
    # Job Queue
    "JobQueueService",
    "get_job_queue_service",
    # Subscriptions (billing status / usage quota)
    "SubscriptionService",
    "get_subscription_service",
]
