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
from .brush_service import BrushService, get_brush_service
from .images_service import ImagesService, get_images_service
from .imagegen_service import ImageGenService, get_imagegen_service
from .lookdev_service import LookdevService, get_lookdev_service
from .lookdev_360_service import Lookdev360Service, get_lookdev_360_service
from .lookdev_3d_service import Lookdev3DService, get_lookdev_3d_service
from .mesh_segment_service import MeshSegmentService, get_mesh_segment_service
from .model_3d_gen_service import Model3DGenService, get_model_3d_gen_service
from .scene_recon_service import SceneReconService, get_scene_recon_service
from .hunyuan_service import HunyuanService, get_hunyuan_service
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
    # Brushes
    "BrushService",
    "get_brush_service",
    # Images
    "ImagesService",
    "get_images_service",
    # ImageGen
    "ImageGenService",
    "get_imagegen_service",
    # Lookdev
    "LookdevService",
    "get_lookdev_service",
    # Lookdev 360
    "Lookdev360Service",
    "get_lookdev_360_service",
    # Lookdev 3D
    "Lookdev3DService",
    "get_lookdev_3d_service",
    # Mesh Segment
    "MeshSegmentService",
    "get_mesh_segment_service",
    # Model 3D Gen
    "Model3DGenService",
    "get_model_3d_gen_service",
    # Scene Reconstruction
    "SceneReconService",
    "get_scene_recon_service",
    # Hunyuan 3D
    "HunyuanService",
    "get_hunyuan_service",
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
