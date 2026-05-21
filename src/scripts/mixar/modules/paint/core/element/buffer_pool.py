# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thread-safe buffer pooling for pixel operations.

This module provides a buffer pool to reduce memory allocation overhead during
repeated pixel operations. Buffers are reused across operations, significantly
reducing GC pressure and allocation time.

Buffer Pool Lifecycle
=====================
1. ACQUISITION: Call acquire_buffer(size, dtype) to get a buffer.
   - Returns a pooled buffer if available, otherwise allocates new.
   - The caller is responsible for the buffer until release.

2. USAGE: Use the buffer for pixel operations.
   - Buffer contents are undefined on acquisition (not zeroed).
   - Caller must initialize or overwrite all values.

3. RELEASE: Call release_buffer(buffer) when done.
   - Buffer is returned to pool for reuse.
   - Do NOT use the buffer after releasing.

4. CLEANUP: Call clear_buffer_pool() to free all pooled memory.
   - Call during idle periods or when memory is constrained.
   - Safe to call at any time; pool will rebuild as needed.

Thread Safety
=============
All pool operations are protected by a threading.Lock. Multiple threads
can safely acquire and release buffers concurrently.

Example Usage
=============
    from .buffer_pool import acquire_buffer, release_buffer, clear_buffer_pool

    # Acquire a buffer
    buf = acquire_buffer(1024 * 1024 * 4)
    try:
        image.pixels.foreach_get(buf)
        # ... process buf ...
        image.pixels.foreach_set(buf)
    finally:
        release_buffer(buf)

    # Clear pool when done with batch operations
    clear_buffer_pool()

Test Isolation
==============
For unit tests, call clear_buffer_pool() in setUp/tearDown to ensure test
isolation. The global state is thread-safe but shared across tests within
the same process.

    class TestPixelOps(unittest.TestCase):
        def setUp(self):
            clear_buffer_pool()  # Start with empty pool

        def tearDown(self):
            clear_buffer_pool()  # Clean up after test
"""

import threading

import numpy


# =============================================================================
# Pool Configuration
# =============================================================================

# Maximum number of buffers to keep per size (prevents unbounded memory growth)
_POOL_MAX_BUFFERS_PER_SIZE = 4

# Maximum total buffers across all sizes
_POOL_MAX_TOTAL_BUFFERS = 16


# =============================================================================
# Pool State (protected by _pool_lock)
# =============================================================================

# Buffer pool: dict mapping (size, dtype) to list of available buffers
_buffer_pool = {}

# Track total buffers in pool
_pool_buffer_count = 0

# Lock for thread-safe pool access
_pool_lock = threading.Lock()


def acquire_buffer(size, dtype=numpy.float32):
    """Acquire a buffer from the pool or allocate a new one.

    Thread-safe. Returns a buffer of the requested size and type.
    The buffer contents are undefined (not zeroed).

    Args:
        size: The size of the buffer (number of elements).
        dtype: The numpy dtype for the buffer. Default: numpy.float32

    Returns:
        numpy.ndarray: A buffer of the requested size and type.
    """
    global _pool_buffer_count

    key = (size, dtype)

    with _pool_lock:
        if key in _buffer_pool and _buffer_pool[key]:
            _pool_buffer_count -= 1
            return _buffer_pool[key].pop()

    # Allocate outside the lock to minimize lock contention
    return numpy.empty(shape=size, dtype=dtype)


def release_buffer(buffer):
    """Return a buffer to the pool for reuse.

    Thread-safe. The buffer should not be used after calling this function.

    Args:
        buffer: The numpy array to return to the pool.
    """
    global _pool_buffer_count

    size = buffer.size
    dtype = buffer.dtype
    key = (size, dtype)

    # Ensure buffer is 1D before pooling
    if buffer.ndim != 1:
        buffer = buffer.ravel()

    with _pool_lock:
        # Don't pool if we've exceeded total limit
        if _pool_buffer_count >= _POOL_MAX_TOTAL_BUFFERS:
            return

        if key not in _buffer_pool:
            _buffer_pool[key] = []

        # Don't exceed per-size limit
        if len(_buffer_pool[key]) < _POOL_MAX_BUFFERS_PER_SIZE:
            _buffer_pool[key].append(buffer)
            _pool_buffer_count += 1


def clear_buffer_pool():
    """Clear all pooled buffers to free memory.

    Thread-safe. Call this function when you want to reclaim memory used by
    the buffer pool, such as after completing a batch of operations or when
    memory is constrained.
    """
    global _buffer_pool, _pool_buffer_count

    with _pool_lock:
        _buffer_pool.clear()
        _pool_buffer_count = 0


def get_pool_stats():
    """Get statistics about the buffer pool.

    Thread-safe.

    Returns:
        dict: Statistics including total buffers, sizes, and memory usage.
    """
    with _pool_lock:
        total_memory = 0
        size_counts = {}

        for (size, dtype), buffers in _buffer_pool.items():
            count = len(buffers)
            size_counts[size] = count
            # Calculate memory: size * itemsize * count
            itemsize = numpy.dtype(dtype).itemsize
            total_memory += size * itemsize * count

        return {
            'total_buffers': _pool_buffer_count,
            'size_counts': dict(size_counts),
            'total_memory_bytes': total_memory,
            'total_memory_mb': total_memory / (1024 * 1024),
        }
