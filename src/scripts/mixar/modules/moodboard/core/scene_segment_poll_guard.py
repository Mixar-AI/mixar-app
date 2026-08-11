# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thread-safe single-flight leases for Scene Segment status polling."""

import threading
from typing import Dict, Optional


class SceneSegmentPollGuard:
    """Allow at most one active status request for each moodboard image."""

    def __init__(self):
        self._lock = threading.Lock()
        self._leases: Dict[str, object] = {}

    def acquire(self, image_name: str) -> Optional[object]:
        """Return a lease, or ``None`` when this image is already polling."""
        with self._lock:
            if image_name in self._leases:
                return None
            lease = object()
            self._leases[image_name] = lease
            return lease

    def release(self, image_name: str, lease: object) -> bool:
        """Release only the matching lease, protecting replacement polls."""
        with self._lock:
            if self._leases.get(image_name) is not lease:
                return False
            self._leases.pop(image_name, None)
            return True

    def clear(self, image_name: Optional[str] = None) -> None:
        """Clear one image lease, or every lease during manager shutdown."""
        with self._lock:
            if image_name is None:
                self._leases.clear()
            else:
                self._leases.pop(image_name, None)
