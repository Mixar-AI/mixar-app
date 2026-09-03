# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Core functionality for Mixie Chat module.

Provides session management, event processing, JSON-RPC client,
SSE handling, and script execution.
"""

from .connection_manager import ConnectionManager, get_connection_manager
from .dev_data import DevDataProvider, get_dummy_response, populate_dev_session
from .executor import ExecutionResult, ScriptExecutor, get_executor
from .image_utils import (
    cleanup_loaded_file_image,
    cleanup_loaded_file_images,
    cleanup_preview_collection,
    clear_thumbnail_cache,
    collect_message_file_image_paths,
    encode_attachment_for_upload,
    get_blend_images,
    get_image_display_name,
    get_image_thumbnail_id,
    get_mixar_screenshots_dir,
    validate_image_file,
)
from .jsonrpc_client import (
    JSONRPCWebSocketClient,
    cleanup_jsonrpc_client,
    create_jsonrpc_client,
    get_jsonrpc_client,
)
from .queue_processor import EventProcessor, get_event_processor
from .session import SessionManager, get_session_manager
from .sse_handler import (
    SSEEvent,
    SSEStreamHandler,
    cleanup_all_sse_handlers,
    cleanup_sse_handler,
    create_sse_handler,
    get_sse_handler,
)

__all__ = [
    # Session
    "SessionManager",
    "get_session_manager",
    # Connection Manager
    "ConnectionManager",
    "get_connection_manager",
    # Event Processor
    "EventProcessor",
    "get_event_processor",
    # JSON-RPC Client
    "JSONRPCWebSocketClient",
    "create_jsonrpc_client",
    "get_jsonrpc_client",
    "cleanup_jsonrpc_client",
    # SSE Handler
    "SSEStreamHandler",
    "SSEEvent",
    "create_sse_handler",
    "get_sse_handler",
    "cleanup_sse_handler",
    "cleanup_all_sse_handlers",
    # Executor
    "ScriptExecutor",
    "ExecutionResult",
    "get_executor",
    # Dev Mode
    "DevDataProvider",
    "get_dummy_response",
    "populate_dev_session",
    # Image Utils
    "validate_image_file",
    "encode_attachment_for_upload",
    "get_image_thumbnail_id",
    "get_blend_images",
    "get_image_display_name",
    "get_mixar_screenshots_dir",
    "clear_thumbnail_cache",
    "cleanup_preview_collection",
    "cleanup_loaded_file_image",
    "cleanup_loaded_file_images",
    "collect_message_file_image_paths",
]
