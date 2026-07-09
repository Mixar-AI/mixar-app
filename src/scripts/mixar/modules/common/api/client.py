# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Base HTTP client for REST API communication.

Provides a centralized HTTP client with:
- Synchronous and asynchronous request methods
- Automatic auth token injection
- Retry logic with exponential backoff
- Request/response logging
- Error handling and exception mapping
"""

import time
import uuid
from typing import Any, Callable, Dict, Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from mixar.config.config import get_server_url
from mixar.config.logging_config import get_logger
from ...auth.core.auth import get_access_token, refresh_access_token

from .constants import (
    CONTENT_TYPE_JSON,
    DEFAULT_RETRY_COUNT,
    DEFAULT_RETRY_DELAY,
    DEFAULT_TIMEOUT,
    HTTPMethod,
    POOL_CONNECTIONS,
    POOL_MAXSIZE,
)
from .exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConnectionError,
    HTTPClientError,
    InsufficientCreditsError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TimeoutError,
    ValidationError,
)
from .executor import AsyncRequest, RequestPriority, get_executor
from .processor import get_api_processor
from .request_queue import (
    AsyncResponse,
    ResponseStatus,
    get_request_queues,
)
from .response import APIResponse


_logger = get_logger(__name__)

_LOG_LEVEL_MAP = {
    "debug": _logger.debug,
    "info": _logger.info,
    "warning": _logger.warning,
    "error": _logger.error,
}


def _fallback_log(level: str, message: str) -> None:
    """Fallback logger when no on_log callback is provided."""
    log_fn = _LOG_LEVEL_MAP.get(level.lower(), _logger.debug)
    log_fn(message)


def _ensure_api_infrastructure() -> None:
    """Ensure executor and processor are running before async requests."""
    executor = get_executor()
    if not executor.is_running:
        executor.start()

    processor = get_api_processor()
    if not processor.is_processing:
        processor.start()


class HTTPClient:
    """
    Base HTTP client for REST API communication.

    Features:
    - Session management with connection pooling
    - Automatic auth token injection
    - Configurable retry logic with exponential backoff
    - Synchronous and asynchronous request methods
    - Request/response logging
    - Exception mapping for status codes
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_count: int = DEFAULT_RETRY_COUNT,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        on_log: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Initialize HTTP client.

        Args:
            base_url: Base URL for API requests (defaults to config)
            timeout: Request timeout in seconds
            retry_count: Number of retry attempts
            retry_delay: Initial retry delay in seconds
            on_log: Optional logging callback (level, message)
        """
        self._base_url = base_url or get_server_url()
        self._timeout = timeout
        self._retry_count = retry_count
        self._retry_delay = retry_delay
        self._on_log = on_log

        # Create session with retry adapter
        self._session = self._create_session()

        # Queue references for async operations
        self._queues = get_request_queues()

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry configuration."""
        session = requests.Session()

        # Configure retry strategy.
        # POST is included so transient 5xx responses on enqueue and other
        # POST endpoints are retried. The job-queue enqueue is safe
        # to retry because it carries an idempotency key; other POST callers
        # should ensure their endpoints are idempotent or guard against
        # duplicate work themselves.
        retry_strategy = Retry(
            total=self._retry_count,
            backoff_factor=self._retry_delay,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=POOL_CONNECTIONS,
            pool_maxsize=POOL_MAXSIZE,
        )

        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _log(self, level: str, message: str) -> None:
        """Log a message using the callback or fallback logger."""
        if self._on_log:
            self._on_log(level, message)
        else:
            _fallback_log(level, message)

    def _get_default_headers(self) -> Dict[str, str]:
        """Get default headers including auth token."""
        headers = {
            "Accept": CONTENT_TYPE_JSON,
            "Content-Type": CONTENT_TYPE_JSON,
        }

        # Add auth token if available
        token = get_access_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        return headers

    def _build_url(self, endpoint: str) -> str:
        """Build full URL from endpoint."""
        endpoint = endpoint.lstrip("/")
        return f"{self._base_url}/{endpoint}"

    def _map_exception(self, response: requests.Response) -> HTTPClientError:
        """Map HTTP status code to appropriate exception."""
        status = response.status_code
        data = None

        try:
            data = response.json()
            detail = data.get("detail")
            # Handle structured error format: {"detail": {"status": "failure", "message": "...", "data": {}}}
            if isinstance(detail, dict):
                message = detail.get("message", str(detail))
            elif detail:
                message = detail
            else:
                message = data.get("message", response.text)
        except Exception:
            message = response.text or f"HTTP {status}"

        error_kwargs = {
            "message": message,
            "status_code": status,
            "response_data": data,
        }

        if status == 401:
            return AuthenticationError(**error_kwargs)
        elif status == 402:
            # Credits exhausted. Pull the "manage subscription" CTA the backend
            # attaches under data.action_url / data.action_label (structured
            # body is either {detail: {..., data}} or {..., data} depending on
            # whether it was raised via HTTPException or ORJSONResponse).
            cta = {}
            if isinstance(data, dict):
                body = data.get("detail") if isinstance(data.get("detail"), dict) else data
                if isinstance(body, dict) and isinstance(body.get("data"), dict):
                    cta = body["data"]
            return InsufficientCreditsError(
                action_url=cta.get("action_url"),
                action_label=cta.get("action_label"),
                **error_kwargs,
            )
        elif status == 403:
            return AuthorizationError(**error_kwargs)
        elif status == 404:
            return NotFoundError(**error_kwargs)
        elif status in (400, 422):
            return ValidationError(**error_kwargs)
        elif status == 429:
            retry_after = response.headers.get("Retry-After")
            return RateLimitError(
                retry_after=float(retry_after) if retry_after else None,
                **error_kwargs,
            )
        elif 500 <= status < 600:
            return ServerError(**error_kwargs)
        else:
            return HTTPClientError(**error_kwargs)

    # ========================================================================
    # SYNCHRONOUS REQUEST METHODS
    # ========================================================================

    def request(
        self,
        method: Union[HTTPMethod, str],
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        files: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        raise_for_status: bool = True,
        _skip_token_refresh: bool = False,
    ) -> APIResponse:
        """
        Make a synchronous HTTP request.

        Args:
            method: HTTP method
            endpoint: API endpoint (will be appended to base_url)
            params: Query parameters
            data: Form data
            json: JSON body
            headers: Additional headers (merged with defaults)
            files: Files for multipart upload
            timeout: Request timeout override
            raise_for_status: Raise exception on error status codes

        Returns:
            APIResponse wrapper

        Raises:
            HTTPClientError subclass on error if raise_for_status=True
        """
        if isinstance(method, HTTPMethod):
            method = method.value

        url = self._build_url(endpoint)
        request_headers = self._get_default_headers()

        if headers:
            request_headers.update(headers)

        # Remove Content-Type for file uploads or form data (requests sets it automatically)
        if files or data:
            request_headers.pop("Content-Type", None)

        self._log("debug", f"{method} {url}")

        try:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json,
                headers=request_headers,
                files=files,
                timeout=timeout or self._timeout,
            )

            self._log("debug", f"Response: {response.status_code}")

            # Handle 401 with automatic token refresh
            # Skip refresh if _skip_token_refresh is True to prevent infinite recursion
            if response.status_code == 401 and raise_for_status and not _skip_token_refresh:
                self._log("debug", "Got 401, attempting token refresh")
                refresh_result = refresh_access_token()

                if refresh_result.get("success"):
                    # Retry with new token
                    self._log("debug", "Token refreshed, retrying request")
                    request_headers = self._get_default_headers()
                    if headers:
                        request_headers.update(headers)
                    if files or data:
                        request_headers.pop("Content-Type", None)

                    response = self._session.request(
                        method=method,
                        url=url,
                        params=params,
                        data=data,
                        json=json,
                        headers=request_headers,
                        files=files,
                        timeout=timeout or self._timeout,
                    )
                    self._log("debug", f"Retry response: {response.status_code}")

                # If still not ok after refresh attempt, raise the error
                if not response.ok:
                    raise self._map_exception(response)
            elif raise_for_status and not response.ok:
                raise self._map_exception(response)

            # Parse response
            try:
                response_data = response.json()
            except Exception:
                response_data = response.text

            return APIResponse(
                success=response.ok,
                status_code=response.status_code,
                data=response_data,
                message="Success" if response.ok else str(response_data),
                headers=dict(response.headers),
                raw=response,
            )

        except requests.exceptions.Timeout:
            self._log("error", f"Request timeout: {url}")
            raise TimeoutError(f"Request to {url} timed out")
        except requests.exceptions.ConnectionError as e:
            self._log("error", f"Connection error: {e}")
            raise ConnectionError(f"Failed to connect to {url}")
        except HTTPClientError:
            raise
        except Exception as e:
            self._log("error", f"Request error: {e}")
            raise HTTPClientError(str(e))

    # Convenience methods
    def get(self, endpoint: str, **kwargs) -> APIResponse:
        """Make a GET request."""
        return self.request(HTTPMethod.GET, endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> APIResponse:
        """Make a POST request."""
        return self.request(HTTPMethod.POST, endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs) -> APIResponse:
        """Make a PUT request."""
        return self.request(HTTPMethod.PUT, endpoint, **kwargs)

    def patch(self, endpoint: str, **kwargs) -> APIResponse:
        """Make a PATCH request."""
        return self.request(HTTPMethod.PATCH, endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs) -> APIResponse:
        """Make a DELETE request."""
        return self.request(HTTPMethod.DELETE, endpoint, **kwargs)

    # ========================================================================
    # ASYNCHRONOUS REQUEST METHODS
    # ========================================================================

    def request_async(
        self,
        method: Union[HTTPMethod, str],
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        files: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        priority: RequestPriority = RequestPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Make an asynchronous HTTP request.

        The request executes in a background thread. Results are delivered
        via callbacks on Blender's main thread.

        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            data: Form data
            json: JSON body
            headers: Additional headers
            files: Files for multipart upload
            timeout: Request timeout override
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse
            priority: Request priority level
            metadata: User data passed through to callbacks

        Returns:
            Request ID for tracking/cancellation
        """
        # Ensure API infrastructure is running
        _ensure_api_infrastructure()

        # Generate request ID
        request_id = str(uuid.uuid4())

        # Register callback if any handlers provided
        callback_id = None
        if on_success or on_error or on_complete:
            callback_id = self._queues.register_callback(
                on_success=on_success,
                on_error=on_error,
                on_complete=on_complete,
                timeout=timeout or self._timeout,
                metadata=metadata or {},
            )

        # Prepare request parameters (captured for closure)
        # All serialization happens here on main thread
        if isinstance(method, HTTPMethod):
            method_str = method.value
        else:
            method_str = method

        url = self._build_url(endpoint)
        request_headers = self._get_default_headers()
        if headers:
            request_headers.update(headers)
        if files or data:
            request_headers.pop("Content-Type", None)

        request_timeout = timeout or self._timeout

        # Create bound callable for background execution
        def execute_request() -> APIResponse:
            """Execute the HTTP request in background thread."""
            # Track if we've already attempted token refresh to prevent infinite recursion
            refresh_attempted = False

            try:
                response = self._session.request(
                    method=method_str,
                    url=url,
                    params=params,
                    data=data,
                    json=json,
                    headers=request_headers,
                    files=files,
                    timeout=request_timeout,
                )

                # Handle 401 with automatic token refresh
                # Only attempt refresh once to prevent infinite recursion
                if response.status_code == 401 and not refresh_attempted:
                    refresh_attempted = True
                    refresh_result = refresh_access_token()

                    if refresh_result.get("success"):
                        # Get fresh headers with new token
                        retry_headers = self._get_default_headers()
                        if headers:
                            retry_headers.update(headers)
                        if files or data:
                            retry_headers.pop("Content-Type", None)

                        # Retry with new token
                        response = self._session.request(
                            method=method_str,
                            url=url,
                            params=params,
                            data=data,
                            json=json,
                            headers=retry_headers,
                            files=files,
                            timeout=request_timeout,
                        )

                # Check for errors
                if not response.ok:
                    raise self._map_exception(response)

                # Parse response
                try:
                    response_data = response.json()
                except Exception:
                    response_data = response.text

                return APIResponse(
                    success=response.ok,
                    status_code=response.status_code,
                    data=response_data,
                    message="Success" if response.ok else str(response_data),
                    headers=dict(response.headers),
                )

            except requests.exceptions.Timeout:
                raise TimeoutError(f"Request to {url} timed out")
            except requests.exceptions.ConnectionError:
                raise ConnectionError(f"Failed to connect to {url}")

        # Completion handler (runs in background thread)
        def on_request_complete(
            req_id: str,
            result: Any,
            exception: Optional[Exception],
        ) -> None:
            """Handle request completion and queue response."""
            if exception:
                async_response = AsyncResponse(
                    request_id=req_id,
                    status=ResponseStatus.ERROR,
                    error=exception,
                    callback_id=callback_id,
                    metadata=metadata or {},
                )
            else:
                async_response = AsyncResponse(
                    request_id=req_id,
                    status=ResponseStatus.SUCCESS,
                    result=result,
                    callback_id=callback_id,
                    metadata=metadata or {},
                )

            self._queues.put_response(async_response)

        # Create async request
        async_request = AsyncRequest(
            request_id=request_id,
            callable=execute_request,
            priority=priority,
            callback_id=callback_id,
            metadata=metadata or {},
        )

        # Submit to executor
        executor = get_executor()
        executor.submit(async_request, on_request_complete)

        self._log("debug", f"[ASYNC] {method_str} {url} -> {request_id}")

        return request_id

    def cancel_request(self, request_id: str) -> bool:
        """
        Cancel a pending async request.

        Args:
            request_id: ID returned from request_async

        Returns:
            True if cancelled, False if already running/completed
        """
        executor = get_executor()
        return executor.cancel(request_id)

    # ========================================================================
    # ASYNC CONVENIENCE METHODS
    # ========================================================================

    def get_async(
        self,
        endpoint: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        **kwargs,
    ) -> str:
        """Make an async GET request."""
        return self.request_async(
            HTTPMethod.GET,
            endpoint,
            on_success=on_success,
            on_error=on_error,
            **kwargs,
        )

    def post_async(
        self,
        endpoint: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        **kwargs,
    ) -> str:
        """Make an async POST request."""
        return self.request_async(
            HTTPMethod.POST,
            endpoint,
            on_success=on_success,
            on_error=on_error,
            **kwargs,
        )

    def put_async(
        self,
        endpoint: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        **kwargs,
    ) -> str:
        """Make an async PUT request."""
        return self.request_async(
            HTTPMethod.PUT,
            endpoint,
            on_success=on_success,
            on_error=on_error,
            **kwargs,
        )

    def patch_async(
        self,
        endpoint: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        **kwargs,
    ) -> str:
        """Make an async PATCH request."""
        return self.request_async(
            HTTPMethod.PATCH,
            endpoint,
            on_success=on_success,
            on_error=on_error,
            **kwargs,
        )

    def delete_async(
        self,
        endpoint: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        **kwargs,
    ) -> str:
        """Make an async DELETE request."""
        return self.request_async(
            HTTPMethod.DELETE,
            endpoint,
            on_success=on_success,
            on_error=on_error,
            **kwargs,
        )

    # ========================================================================
    # FIRE-AND-FORGET PATTERN
    # ========================================================================

    def fire_and_forget(
        self,
        method: Union[HTTPMethod, str],
        endpoint: str,
        **kwargs,
    ) -> str:
        """
        Execute request without caring about the result.

        Useful for analytics, logging, or non-critical updates.

        Args:
            method: HTTP method
            endpoint: API endpoint
            **kwargs: Request parameters

        Returns:
            Request ID (for optional cancellation)
        """
        # Remove callback params if accidentally passed
        kwargs.pop("on_success", None)
        kwargs.pop("on_error", None)
        kwargs.pop("on_complete", None)

        return self.request_async(method, endpoint, **kwargs)


# Global client instance (singleton pattern)
_client: Optional[HTTPClient] = None


def get_http_client() -> HTTPClient:
    """Get or create the global HTTP client instance."""
    global _client
    if _client is None:
        _client = HTTPClient()
    return _client


def create_http_client(**kwargs) -> HTTPClient:
    """Create and set a new global HTTP client."""
    global _client
    if _client is not None:
        _client._session.close()
    _client = HTTPClient(**kwargs)
    return _client


def cleanup_http_client() -> None:
    """Clean up the global HTTP client."""
    global _client
    if _client is not None:
        _client._session.close()
        _client = None
