# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Reusable HTTP/REST API infrastructure for Mixar modules.

This package provides a centralized HTTP client and service modules
for REST API communication with the backend server. Supports both
synchronous and asynchronous (background thread) execution.

Usage:
    from mixar.modules.common.api import (
        # Lifecycle
        start_executor,
        stop_executor,
        start_api_processor,
        stop_api_processor,
        # Client
        HTTPClient,
        get_http_client,
        # Response
        APIResponse,
        # Exceptions
        HTTPClientError,
        AuthenticationError,
        # Services
        get_auth_service,
        get_agent_service,
        get_images_service,
    )

    # Async usage (recommended for Blender operators)
    images = get_images_service()
    images.generate_async(
        prompt="wooden texture",
        on_success=lambda r: print(f"Generated: {r.data}"),
        on_error=lambda e: print(f"Error: {e}"),
    )

    # Sync usage (blocks UI - use sparingly)
    response = images.generate(prompt="wooden texture")
    if response.success:
        print(response.data)
"""

# Lifecycle management
from .executor import (
    HTTPExecutor,
    get_executor,
    start_executor,
    stop_executor,
)
from .processor import (
    APIQueueProcessor,
    get_api_processor,
    start_api_processor,
    stop_api_processor,
)

# Client
from .client import (
    HTTPClient,
    cleanup_http_client,
    create_http_client,
    get_http_client,
)

# Response and request types
from .response import APIResponse
from .request_queue import (
    AsyncResponse,
    PendingCallback,
    RequestQueues,
    ResponseStatus,
    get_request_queues,
)

# Exceptions
from .exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConnectionError,
    HTTPClientError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TimeoutError,
    ValidationError,
)

# Constants
from .constants import (
    API_VERSION,
    APIModule,
    HTTPMethod,
)

# Services
from .services import (
    AgentService,
    AuthService,
    BaseService,
    BrushService,
    GenerationQueueService,
    HunyuanService,
    ImagesService,
    ImageGenService,
    LookdevService,
    Lookdev360Service,
    Lookdev3DService,
    MeshSegmentService,
    Model3DGenService,
    UpdateService,
    get_agent_service,
    get_auth_service,
    get_brush_service,
    get_generation_queue_service,
    get_hunyuan_service,
    get_images_service,
    get_imagegen_service,
    get_lookdev_service,
    get_lookdev_360_service,
    get_lookdev_3d_service,
    get_mesh_segment_service,
    get_model_3d_gen_service,
    get_update_service,
)

__all__ = [
    # Lifecycle
    "HTTPExecutor",
    "get_executor",
    "start_executor",
    "stop_executor",
    "APIQueueProcessor",
    "get_api_processor",
    "start_api_processor",
    "stop_api_processor",
    # Client
    "HTTPClient",
    "get_http_client",
    "create_http_client",
    "cleanup_http_client",
    # Response
    "APIResponse",
    "AsyncResponse",
    "ResponseStatus",
    "PendingCallback",
    "RequestQueues",
    "get_request_queues",
    # Exceptions
    "HTTPClientError",
    "ConnectionError",
    "TimeoutError",
    "AuthenticationError",
    "AuthorizationError",
    "NotFoundError",
    "ValidationError",
    "ServerError",
    "RateLimitError",
    # Constants
    "HTTPMethod",
    "APIModule",
    "API_VERSION",
    # Services
    "BaseService",
    "AuthService",
    "get_auth_service",
    "AgentService",
    "get_agent_service",
    "BrushService",
    "get_brush_service",
    "HunyuanService",
    "get_hunyuan_service",
    "ImagesService",
    "get_images_service",
    "ImageGenService",
    "get_imagegen_service",
    "LookdevService",
    "get_lookdev_service",
    "Lookdev360Service",
    "get_lookdev_360_service",
    "Lookdev3DService",
    "get_lookdev_3d_service",
    "MeshSegmentService",
    "get_mesh_segment_service",
    "Model3DGenService",
    "get_model_3d_gen_service",
    "UpdateService",
    "get_update_service",
    "GenerationQueueService",
    "get_generation_queue_service",
]
