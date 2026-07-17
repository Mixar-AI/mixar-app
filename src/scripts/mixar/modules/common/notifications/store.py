# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Notification Store

Thread-safe singleton for managing active notifications.
Notifications are pushed from the WebSocket thread and consumed
by the main-thread toast renderer.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Union

from .constants import (
    DEFAULT_TTL_MS,
    FADE_DURATION_MS,
    MAX_VISIBLE_TOASTS,
    PRIORITY_TTL_MS,
    NotificationType,
)


@dataclass
class NotificationAction:
    """A clickable action button on a toast notification.

    A button either invokes ``operator`` or, when ``url`` is set, opens the
    URL in the browser (and reports the notification read). ``url`` avoids a
    module-global stash per notification type: several toasts with different
    links can be on screen at once, each button carrying its own URL.
    """
    label: str
    operator: str = ""  # e.g. "mixar.open_downloads_page"
    style: str = "secondary"  # "primary", "secondary", or "danger"
    url: Optional[str] = None  # when set, clicking opens this URL instead


@dataclass
class NotificationItem:
    """A single notification with lifecycle tracking."""
    id: str
    type: NotificationType
    title: str
    body: str
    ttl_ms: int
    priority: str = "normal"
    action_url: Optional[str] = None
    actions: List[NotificationAction] = field(default_factory=list)
    server_id: Optional[str] = None  # backend notification UUID (read receipts)
    dismissible: bool = True
    created_at: float = field(default_factory=time.time)

    @property
    def age_ms(self) -> float:
        return (time.time() - self.created_at) * 1000.0

    @property
    def is_sticky(self) -> bool:
        return self.ttl_ms <= 0

    @property
    def is_expired(self) -> bool:
        if self.is_sticky:
            return False
        return self.age_ms >= self.ttl_ms

    @property
    def remaining_ms(self) -> float:
        if self.is_sticky:
            return float("inf")
        return max(0.0, self.ttl_ms - self.age_ms)

    @property
    def opacity(self) -> float:
        """1.0 while visible, fades to 0.0 during the last FADE_DURATION_MS."""
        if self.is_sticky:
            return 1.0
        remaining = self.remaining_ms
        if remaining >= FADE_DURATION_MS:
            return 1.0
        if remaining <= 0:
            return 0.0
        return remaining / FADE_DURATION_MS


class NotificationStore:
    """Thread-safe store for active notifications (singleton)."""

    _instance: Optional["NotificationStore"] = None
    _lock_cls = threading.Lock()

    def __new__(cls) -> "NotificationStore":
        with cls._lock_cls:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self) -> None:
        self._lock = threading.Lock()
        self._items: List[NotificationItem] = []

    # ------------------------------------------------------------------
    # Push — primary entry point
    # ------------------------------------------------------------------

    def push(
        self,
        type_str: str,
        title: str,
        body: str = "",
        priority: str = "normal",
        action_url: Optional[str] = None,
        actions: Optional[List[NotificationAction]] = None,
        ttl_ms: Optional[int] = None,
        id: Optional[Union[str, int]] = None,
        dismissible: bool = True,
        server_id: Optional[str] = None,
    ) -> str:
        """Add a notification and ensure the toast timer is running.

        Args:
            type_str: One of "info", "warning", "update", "error", "success".
            title: Short notification title.
            body: Optional body text.
            priority: "low", "normal", "high", or "critical".
            action_url: Optional deep-link URL.
            actions: Optional list of NotificationAction for button rendering.
            ttl_ms: Explicit TTL override; if None, derived from priority.
            id: Optional unique id (str or int); auto-generated if omitted.
            dismissible: When False the toast renders without a close button
                and UI clicks cannot dismiss it (programmatic ``dismiss()``
                still works) — used for forced updates.
            server_id: Backend notification id (UUID string) for
                server-originated notifications; enables read receipts.
                Local/client notifications must leave this None.

        Returns:
            The notification id (as string).
        """
        try:
            ntype = NotificationType(type_str)
        except ValueError:
            ntype = NotificationType.INFO

        resolved_ttl = ttl_ms if ttl_ms is not None else PRIORITY_TTL_MS.get(priority, DEFAULT_TTL_MS)
        nid = str(id) if id is not None else uuid.uuid4().hex[:12]

        item = NotificationItem(
            id=nid,
            type=ntype,
            title=title,
            body=body,
            ttl_ms=resolved_ttl,
            priority=priority,
            action_url=action_url,
            actions=actions or [],
            server_id=server_id,
            dismissible=dismissible,
        )

        with self._lock:
            # Deduplicate by id
            self._items = [i for i in self._items if i.id != nid]
            self._items.append(item)

        # Start the toast timer on main thread (deferred import to avoid cycles)
        from .toast_timer import ensure_toast_timer_running
        ensure_toast_timer_running()

        return nid

    def push_from_server(self, data: dict) -> str:
        """Convenience wrapper that unpacks the server notification payload.

        Expected ``data`` keys: id, title, body (or legacy ``message``), type,
        priority, action_url, action_label. The server id doubles as the
        read-receipt handle.

        When ``action_url`` is present it renders as a primary button labelled
        ``action_label`` (default "Open") that opens the URL — matching the
        update toast's Download button — instead of the dimmed inline link.
        """
        server_id = data.get("id")
        action_url = data.get("action_url")
        actions = None
        if action_url:
            actions = [
                NotificationAction(
                    label=data.get("action_label") or "Open",
                    style="primary",
                    url=action_url,
                ),
            ]
        return self.push(
            type_str=data.get("type", "info"),
            title=data.get("title", ""),
            body=data.get("body", data.get("message", "")),
            priority=data.get("priority", "normal"),
            actions=actions,
            id=server_id,
            server_id=str(server_id) if server_id is not None else None,
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_visible(self) -> List[NotificationItem]:
        """Return active (non-expired) items, newest first, capped."""
        with self._lock:
            active = [i for i in self._items if not i.is_expired]
            return list(reversed(active[-MAX_VISIBLE_TOASTS:]))

    def expire_old(self) -> int:
        """Remove expired items. Returns count of remaining items."""
        with self._lock:
            self._items = [i for i in self._items if not i.is_expired]
            return len(self._items)

    def get_server_ids(self) -> List[str]:
        """Return server IDs of all currently held items (for mark-read)."""
        with self._lock:
            return [i.server_id for i in self._items if i.server_id is not None]

    def get_server_id(self, nid: str) -> Optional[str]:
        """Return the server id for one notification, without removing it."""
        with self._lock:
            for i in self._items:
                if i.id == nid:
                    return i.server_id
            return None

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def dismiss(self, nid: str) -> Optional[str]:
        """Remove a notification by id. Returns its server_id if present."""
        with self._lock:
            server_id = None
            for i in self._items:
                if i.id == nid:
                    server_id = i.server_id
                    break
            self._items = [i for i in self._items if i.id != nid]
            return server_id

    def clear_all(self) -> None:
        """Remove all notifications."""
        with self._lock:
            self._items.clear()

    def reset(self) -> None:
        """Full reset — clear items."""
        self.clear_all()


def get_notification_store() -> NotificationStore:
    """Module-level accessor for the notification store singleton."""
    return NotificationStore()
