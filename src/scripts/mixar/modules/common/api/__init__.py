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
    GenerationMetadataService,
    GenerationQueueService,
    ImagesService,
    UpdateService,
    get_agent_service,
    get_auth_service,
    get_generation_metadata_service,
    get_generation_queue_service,
    get_images_service,
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
    "ImagesService",
    "get_images_service",
    "GenerationMetadataService",
    "get_generation_metadata_service",
    "UpdateService",
    "get_update_service",
    "GenerationQueueService",
    "get_generation_queue_service",
]
