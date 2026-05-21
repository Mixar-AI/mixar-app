# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Performance Metrics for Mixie Chat

Lightweight timing instrumentation to measure UI responsiveness
and identify performance bottlenecks.
"""

import time
from collections import defaultdict
from typing import Dict, List, Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class PerformanceMetrics:
    """Collects and reports performance metrics for debugging lag issues."""

    def __init__(self):
        self._timers: Dict[str, float] = {}
        self._measurements: Dict[str, List[float]] = defaultdict(list)
        self._enabled = False  # Enable via env var or config

    def enable(self):
        """Enable metrics collection."""
        self._enabled = True
        logger.info("Performance metrics enabled")

    def disable(self):
        """Disable metrics collection."""
        self._enabled = False
        logger.info("Performance metrics disabled")

    def start_timer(self, name: str):
        """Start a named timer."""
        if not self._enabled:
            return
        self._timers[name] = time.perf_counter()

    def stop_timer(self, name: str) -> Optional[float]:
        """Stop a named timer and record the duration."""
        if not self._enabled:
            return None

        if name not in self._timers:
            logger.warning(f"Timer '{name}' was never started")
            return None

        start_time = self._timers.pop(name)
        duration = time.perf_counter() - start_time
        self._measurements[name].append(duration)

        # Log slow operations (>100ms)
        if duration > 0.1:
            logger.warning(
                f"⚠️  SLOW OPERATION: {name} took {duration*1000:.1f}ms"
            )

        return duration

    def get_stats(self, name: str) -> Dict[str, float]:
        """Get statistics for a named metric."""
        if name not in self._measurements or not self._measurements[name]:
            return {}

        durations = self._measurements[name]
        return {
            'count': len(durations),
            'total': sum(durations),
            'mean': sum(durations) / len(durations),
            'min': min(durations),
            'max': max(durations),
        }

    def report(self):
        """Log a performance report."""
        if not self._enabled:
            return

        logger.info("=== PERFORMANCE METRICS REPORT ===")

        for name, durations in sorted(self._measurements.items()):
            if not durations:
                continue

            stats = self.get_stats(name)
            logger.info(
                f"{name}:"
                f"  count={stats['count']}"
                f"  mean={stats['mean']*1000:.1f}ms"
                f"  min={stats['min']*1000:.1f}ms"
                f"  max={stats['max']*1000:.1f}ms"
            )

        logger.info("=== END PERFORMANCE METRICS ===")

    def clear(self):
        """Clear all measurements."""
        self._timers.clear()
        self._measurements.clear()


# Global singleton
_metrics: Optional[PerformanceMetrics] = None


def get_metrics() -> PerformanceMetrics:
    """Get the global performance metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = PerformanceMetrics()
    return _metrics
