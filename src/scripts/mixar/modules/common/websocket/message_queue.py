# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Thread-safe message queues for WebSocket communication.

Provides inbound and outbound queues for communication between
the WebSocket background thread and Blender's main thread.

IMPORTANT: Outbound messages are serialized to JSON strings on the main thread
before being queued. This prevents thread safety issues where the background
send thread would access Python objects while Blender operators are executing.
"""

from queue import Empty, Queue
from typing import Optional, Union

from .protocol import Message, serialize_message


class MessageQueues:
    """
    Singleton holding inbound and outbound message queues.

    Thread-safe via Python's queue.Queue implementation.
    """

    _instance: Optional["MessageQueues"] = None

    def __new__(cls) -> "MessageQueues":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._inbound = Queue()
            cls._instance._outbound = Queue()
        return cls._instance

    @property
    def inbound(self) -> Queue:
        """Get the inbound message queue (server -> client)."""
        return self._inbound

    @property
    def outbound(self) -> Queue:
        """Get the outbound message queue (client -> server)."""
        return self._outbound

    def send(self, message: Message) -> None:
        """
        Queue a message to be sent to the server.

        The message is serialized to JSON here on the main thread to avoid
        thread safety issues when the background thread accesses the data.

        Args:
            message: Message to send
        """
        # Serialize on main thread to avoid background thread accessing Python objects
        serialized = serialize_message(message)
        self._outbound.put(serialized)

    def receive(self) -> Optional[Message]:
        """
        Non-blocking get from inbound queue.

        Returns:
            Message if available, None otherwise
        """
        try:
            return self._inbound.get_nowait()
        except Empty:
            return None

    def receive_blocking(self, timeout: float = 1.0) -> Optional[Message]:
        """
        Blocking get from inbound queue with timeout.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            Message if received, None on timeout
        """
        try:
            return self._inbound.get(timeout=timeout)
        except Empty:
            return None

    def put_inbound(self, message: Message) -> None:
        """
        Put a message in the inbound queue.

        Called by the WebSocket thread when receiving messages.

        Args:
            message: Message received from server
        """
        self._inbound.put(message)

    def get_outbound(self, timeout: float = 0.1) -> Optional[str]:
        """
        Get a serialized message from the outbound queue.

        Called by the WebSocket thread to send messages.
        Returns pre-serialized JSON strings to avoid thread safety issues.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            Serialized JSON string to send, or None on timeout
        """
        try:
            return self._outbound.get(timeout=timeout)
        except Empty:
            return None

    def clear_inbound(self) -> int:
        """
        Clear all messages from the inbound queue.

        Returns:
            Number of messages cleared
        """
        count = 0
        while True:
            try:
                self._inbound.get_nowait()
                count += 1
            except Empty:
                break
        return count

    def clear_outbound(self) -> int:
        """
        Clear all messages from the outbound queue.

        Returns:
            Number of messages cleared
        """
        count = 0
        while True:
            try:
                self._outbound.get_nowait()
                count += 1
            except Empty:
                break
        return count

    def clear_all(self) -> tuple[int, int]:
        """
        Clear all queues.

        Returns:
            Tuple of (inbound_cleared, outbound_cleared)
        """
        return self.clear_inbound(), self.clear_outbound()

    def inbound_size(self) -> int:
        """Get approximate size of inbound queue."""
        return self._inbound.qsize()

    def outbound_size(self) -> int:
        """Get approximate size of outbound queue."""
        return self._outbound.qsize()

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance. Useful for testing."""
        if cls._instance is not None:
            cls._instance.clear_all()
            cls._instance = None


def get_message_queues() -> MessageQueues:
    """Get the global MessageQueues singleton."""
    return MessageQueues()
