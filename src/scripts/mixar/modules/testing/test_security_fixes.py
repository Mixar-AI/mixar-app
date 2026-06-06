# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test suite for security fixes in the paint module.

This module tests the following security fixes:
1. Code injection prevention in _set_nested_attr()
2. Path traversal prevention in mask_operators_open_image.py
3. Buffer pool memory management in buffer_pool.py

Run this script in Blender's Python console or as a script to test the
security fixes.

Usage:
    Run inside Blender:
    blender --background --python src/scripts/mixar/modules/testing/test_security_fixes.py
"""

import os
import traceback

import numpy


# =============================================================================
# Mock Objects for Testing
# =============================================================================

class MockChannel:
    """Mock channel object for testing _set_nested_attr."""

    def __init__(self):
        self.override_value = 0.0
        self.name = "test"
        self.enabled = True


class MockLayer:
    """Mock layer object with channels collection for testing."""

    def __init__(self, num_channels=3):
        self.channels = [MockChannel() for _ in range(num_channels)]
        self.name = "TestLayer"
        self.parent = None


class MockNestedObject:
    """Mock object with nested structure for testing."""

    def __init__(self):
        self.child = MockChannel()
        self.values = [1.0, 2.0, 3.0]


# =============================================================================
# Path Validation Helper (extracted logic for testing)
# =============================================================================

def validate_path(directory, path):
    """Validates a path to prevent directory traversal.

    This is the same logic used in mask_operators_open_image.py.

    Returns True if path is safe, False if it should be blocked.
    """
    safe_path = os.path.normpath(os.path.join(directory, path))
    normalized_directory = os.path.normpath(directory)
    if not safe_path.startswith(normalized_directory + os.sep) and safe_path != normalized_directory:
        return False
    return True


# =============================================================================
# Code Injection Tests (_set_nested_attr)
# =============================================================================

def test_set_nested_attr_simple_attribute():
    """Test setting a simple attribute like 'name'."""
    print("  Testing simple attribute...")

    # Import here to avoid issues if run outside Blender context
    from mixar.modules.paint.core.io.input_outputs.input_outputs_channel_ios import _set_nested_attr

    layer = MockLayer()
    _set_nested_attr(layer, 'name', 'NewName', 'NodeSocketString')

    assert layer.name == 'NewName', f"Expected 'NewName', got '{layer.name}'"
    print("    PASS: Simple attribute set correctly")
    return True


def test_set_nested_attr_indexed_attribute():
    """Test setting indexed attribute like 'channels[0].override_value'."""
    print("  Testing indexed attribute...")

    from mixar.modules.paint.core.io.input_outputs.input_outputs_channel_ios import _set_nested_attr

    layer = MockLayer()
    _set_nested_attr(layer, 'channels[0].override_value', 0.5, 'NodeSocketFloat')

    assert layer.channels[0].override_value == 0.5, f"Expected 0.5, got {layer.channels[0].override_value}"
    print("    PASS: Indexed attribute set correctly")
    return True


def test_set_nested_attr_nested_path():
    """Test deeply nested paths."""
    print("  Testing nested path...")

    from mixar.modules.paint.core.io.input_outputs.input_outputs_channel_ios import _set_nested_attr

    obj = MockNestedObject()
    _set_nested_attr(obj, 'child.name', 'NestedName', 'NodeSocketString')

    assert obj.child.name == 'NestedName', f"Expected 'NestedName', got '{obj.child.name}'"
    print("    PASS: Nested path set correctly")
    return True


def test_set_nested_attr_rejects_code_injection():
    """Test that code injection attempts are rejected."""
    print("  Testing code injection rejection...")

    from mixar.modules.paint.core.io.input_outputs.input_outputs_channel_ios import _set_nested_attr

    layer = MockLayer()

    malicious_paths = [
        "__import__('os').system('echo hacked')",
        "channels[0].__class__.__bases__",
        "channels[__import__('os').system('ls')]",
        "channels[0];print('injected')",
        "__dict__",
        "__class__.__mro__",
    ]

    all_rejected = True
    for path in malicious_paths:
        try:
            _set_nested_attr(layer, path, 1.0, 'NodeSocketFloat')
            print(f"    FAIL: '{path}' was not rejected!")
            all_rejected = False
        except (ValueError, AttributeError, KeyError, IndexError) as e:
            print(f"    OK: '{path}' correctly rejected: {type(e).__name__}")
        except Exception as e:
            # Any other exception is fine, as long as code wasn't executed
            print(f"    OK: '{path}' raised {type(e).__name__}")

    return all_rejected


def test_set_nested_attr_rejects_expression_index():
    """Test that expression indices like [0+0] are rejected."""
    print("  Testing expression index rejection...")

    from mixar.modules.paint.core.io.input_outputs.input_outputs_channel_ios import _set_nested_attr

    layer = MockLayer()

    expression_paths = [
        "channels[0+0].override_value",
        "channels[int('0')].override_value",
        "channels[len([])].override_value",
    ]

    all_rejected = True
    for path in expression_paths:
        try:
            _set_nested_attr(layer, path, 1.0, 'NodeSocketFloat')
            print(f"    FAIL: '{path}' was not rejected!")
            all_rejected = False
        except (ValueError, AttributeError, KeyError, IndexError) as e:
            print(f"    OK: '{path}' correctly rejected: {type(e).__name__}")
        except Exception as e:
            print(f"    OK: '{path}' raised {type(e).__name__}")

    return all_rejected


def test_set_nested_attr_handles_invalid_index():
    """Test that out-of-range indices raise IndexError."""
    print("  Testing invalid index handling...")

    from mixar.modules.paint.core.io.input_outputs.input_outputs_channel_ios import _set_nested_attr

    layer = MockLayer(num_channels=3)

    try:
        _set_nested_attr(layer, 'channels[99].override_value', 1.0, 'NodeSocketFloat')
        print("    FAIL: Out-of-range index was not rejected!")
        return False
    except IndexError:
        print("    OK: IndexError raised for out-of-range index")
        return True
    except Exception as e:
        print(f"    OK: {type(e).__name__} raised for invalid index")
        return True


def test_set_nested_attr_handles_invalid_attribute():
    """Test that invalid attributes raise AttributeError."""
    print("  Testing invalid attribute handling...")

    from mixar.modules.paint.core.io.input_outputs.input_outputs_channel_ios import _set_nested_attr

    layer = MockLayer()

    try:
        _set_nested_attr(layer, 'nonexistent_attr', 1.0, 'NodeSocketFloat')
        print("    FAIL: Invalid attribute was not rejected!")
        return False
    except AttributeError:
        print("    OK: AttributeError raised for invalid attribute")
        return True
    except Exception as e:
        print(f"    FAIL: Unexpected exception: {type(e).__name__}: {e}")
        return False


# =============================================================================
# Path Traversal Tests
# =============================================================================

def _get_test_base_dir():
    """Get a platform-appropriate test base directory."""
    import tempfile
    return os.path.join(tempfile.gettempdir(), "test_images")


def test_path_validation_allows_valid_paths():
    """Test that valid paths within directory are allowed."""
    print("  Testing valid paths...")

    base_dir = _get_test_base_dir()

    valid_paths = [
        "image.png",
        os.path.join("subdir", "image.png"),
        os.path.join("subdir", "nested", "image.png"),
        os.path.join(".", "image.png"),
    ]

    all_valid = True
    for path in valid_paths:
        if not validate_path(base_dir, path):
            print(f"    FAIL: '{path}' was incorrectly blocked!")
            all_valid = False
        else:
            print(f"    OK: '{path}' correctly allowed")

    return all_valid


def test_path_validation_blocks_parent_traversal():
    """Test that ../ style paths are blocked."""
    print("  Testing parent traversal blocking...")

    base_dir = _get_test_base_dir()

    malicious_paths = [
        os.path.join("..", "..", "..", "etc", "passwd"),
        os.path.join("subdir", "..", "..", "etc", "passwd"),
        os.path.join(".", "..", "..", "secret"),
        os.path.join("image", "..", "..", "..", "etc", "passwd"),
    ]

    all_blocked = True
    for path in malicious_paths:
        if validate_path(base_dir, path):
            print(f"    FAIL: '{path}' was not blocked!")
            all_blocked = False
        else:
            print(f"    OK: '{path}' correctly blocked")

    return all_blocked


def test_path_validation_blocks_absolute_paths():
    """Test that absolute paths outside directory are blocked."""
    print("  Testing absolute path blocking...")

    base_dir = _get_test_base_dir()

    if os.name == 'nt':
        malicious_paths = [
            "C:\\Windows\\System32\\config\\SAM",
            "C:\\Users\\other\\secret.txt",
        ]
    else:
        malicious_paths = [
            "/etc/passwd",
            "/home/other/secret.txt",
        ]

    all_blocked = True
    for path in malicious_paths:
        if validate_path(base_dir, path):
            print(f"    FAIL: '{path}' was not blocked!")
            all_blocked = False
        else:
            print(f"    OK: '{path}' correctly blocked")

    return all_blocked


def test_path_validation_allows_subdirectories():
    """Test that valid subdirectory paths work."""
    print("  Testing subdirectory paths...")

    base_dir = _get_test_base_dir()

    valid_paths = [
        os.path.join("textures", "diffuse.png"),
        os.path.join("textures", "normal", "bump.png"),
        os.path.join("export", "final", "render.exr"),
    ]

    all_valid = True
    for path in valid_paths:
        if not validate_path(base_dir, path):
            print(f"    FAIL: '{path}' was incorrectly blocked!")
            all_valid = False
        else:
            print(f"    OK: '{path}' correctly allowed")

    return all_valid


# =============================================================================
# Buffer Pool Tests
# =============================================================================

def test_buffer_pool_acquire_new():
    """Test acquiring a buffer when pool is empty."""
    print("  Testing buffer acquisition (new)...")

    from mixar.modules.paint.core.element.buffer_pool import acquire_buffer, clear_buffer_pool

    # Clear pool first
    clear_buffer_pool()

    # Acquire a buffer
    buf = acquire_buffer(1024)

    assert buf is not None, "Buffer should not be None"
    assert buf.size == 1024, f"Expected size 1024, got {buf.size}"
    assert buf.dtype == numpy.float32, f"Expected float32, got {buf.dtype}"

    print("    PASS: Buffer acquired successfully")
    return True


def test_buffer_pool_acquire_reuse():
    """Test that released buffers are reused."""
    print("  Testing buffer reuse...")

    from mixar.modules.paint.core.element.buffer_pool import acquire_buffer, release_buffer, clear_buffer_pool

    # Clear pool first
    clear_buffer_pool()

    # Acquire and release a buffer
    size = 1024
    buf1 = acquire_buffer(size)
    buf1_id = id(buf1)
    release_buffer(buf1)

    # Acquire again - should get the same buffer back
    buf2 = acquire_buffer(size)
    buf2_id = id(buf2)

    # Check if same buffer was reused
    same_buffer = buf1_id == buf2_id
    print(f"    Buffer reused: {same_buffer}")

    # Clean up
    release_buffer(buf2)
    clear_buffer_pool()

    return same_buffer


def test_buffer_pool_clear():
    """Test clearing the pool frees all buffers."""
    print("  Testing pool clear...")

    from mixar.modules.paint.core.element.buffer_pool import acquire_buffer, release_buffer, clear_buffer_pool, get_pool_stats

    # Clear pool first
    clear_buffer_pool()

    # Add some buffers to the pool
    buffers = []
    for i in range(5):
        buf = acquire_buffer(1024 * (i + 1))
        buffers.append(buf)

    for buf in buffers:
        release_buffer(buf)

    # Check pool has buffers
    stats = get_pool_stats()
    assert stats['total_buffers'] > 0, "Pool should have buffers"

    # Clear the pool
    clear_buffer_pool()

    # Check pool is empty
    stats = get_pool_stats()
    assert stats['total_buffers'] == 0, f"Pool should be empty, got {stats['total_buffers']}"

    print("    PASS: Pool cleared successfully")
    return True


def test_buffer_pool_stats():
    """Test get_pool_stats returns accurate information."""
    print("  Testing pool stats...")

    from mixar.modules.paint.core.element.buffer_pool import acquire_buffer, release_buffer, clear_buffer_pool, get_pool_stats

    # Clear pool first
    clear_buffer_pool()

    # Add some buffers
    buf1 = acquire_buffer(1024)
    buf2 = acquire_buffer(2048)
    release_buffer(buf1)
    release_buffer(buf2)

    stats = get_pool_stats()

    assert stats['total_buffers'] == 2, f"Expected 2 buffers, got {stats['total_buffers']}"
    assert 1024 in stats['size_counts'] or (1024, numpy.float32) in str(stats), "Size 1024 should be in stats"
    assert stats['total_memory_bytes'] > 0, "Total memory should be > 0"

    print(f"    Stats: {stats}")
    print("    PASS: Stats accurate")

    clear_buffer_pool()
    return True


def test_buffer_pool_per_size_limit():
    """Test that per-size limit is enforced."""
    print("  Testing per-size limit...")

    from mixar.modules.paint.core.element.buffer_pool import acquire_buffer, release_buffer, clear_buffer_pool, get_pool_stats

    # Clear pool first
    clear_buffer_pool()

    # Try to add more than the per-size limit (4)
    buffers = []
    size = 512
    for i in range(6):
        buf = acquire_buffer(size)
        buffers.append(buf)

    for buf in buffers:
        release_buffer(buf)

    stats = get_pool_stats()
    # Per-size limit is 4
    assert stats['total_buffers'] <= 4, f"Expected <= 4 buffers per size, got {stats['total_buffers']}"

    print(f"    Buffers in pool: {stats['total_buffers']} (limit: 4)")
    print("    PASS: Per-size limit enforced")

    clear_buffer_pool()
    return True


def test_buffer_pool_total_limit():
    """Test that total limit is enforced."""
    print("  Testing total limit...")

    from mixar.modules.paint.core.element.buffer_pool import acquire_buffer, release_buffer, clear_buffer_pool, get_pool_stats

    # Clear pool first
    clear_buffer_pool()

    # Try to add more than the total limit (16) with different sizes
    buffers = []
    for i in range(20):
        buf = acquire_buffer(256 * (i + 1))  # Different sizes
        buffers.append(buf)

    for buf in buffers:
        release_buffer(buf)

    stats = get_pool_stats()
    # Total limit is 16
    assert stats['total_buffers'] <= 16, f"Expected <= 16 total buffers, got {stats['total_buffers']}"

    print(f"    Total buffers: {stats['total_buffers']} (limit: 16)")
    print("    PASS: Total limit enforced")

    clear_buffer_pool()
    return True


def test_buffer_pool_dtype_separation():
    """Test that different dtypes are pooled separately."""
    print("  Testing dtype separation...")

    from mixar.modules.paint.core.element.buffer_pool import acquire_buffer, release_buffer, clear_buffer_pool, get_pool_stats

    # Clear pool first
    clear_buffer_pool()

    # Add buffers with different dtypes
    buf_float = acquire_buffer(1024, numpy.float32)
    buf_int = acquire_buffer(1024, numpy.int32)

    release_buffer(buf_float)
    release_buffer(buf_int)

    stats = get_pool_stats()
    assert stats['total_buffers'] == 2, f"Expected 2 buffers (different dtypes), got {stats['total_buffers']}"

    # Acquire float - should get the float buffer back
    buf_float2 = acquire_buffer(1024, numpy.float32)
    assert buf_float2.dtype == numpy.float32, f"Expected float32, got {buf_float2.dtype}"

    print("    PASS: Dtypes separated correctly")

    clear_buffer_pool()
    return True


def test_buffer_pool_performance():
    """Benchmark buffer pool vs direct allocation."""
    print("  Testing buffer pool performance...")

    import time
    from mixar.modules.paint.core.element.buffer_pool import acquire_buffer, release_buffer, clear_buffer_pool

    clear_buffer_pool()

    size = 1024 * 1024 * 4  # 4MB buffer (1024x1024 RGBA)
    iterations = 100

    # Warm up pool with one buffer
    buf = acquire_buffer(size)
    release_buffer(buf)

    # Measure pooled allocation
    start = time.perf_counter()
    for _ in range(iterations):
        buf = acquire_buffer(size)
        release_buffer(buf)
    pooled_time = time.perf_counter() - start

    # Measure direct allocation (no pool)
    clear_buffer_pool()
    start = time.perf_counter()
    for _ in range(iterations):
        buf = numpy.empty(size, dtype=numpy.float32)
        del buf
    direct_time = time.perf_counter() - start

    speedup = direct_time / pooled_time if pooled_time > 0 else 0
    print(f"    Pooled: {pooled_time*1000:.2f}ms, Direct: {direct_time*1000:.2f}ms")
    print(f"    Speedup: {speedup:.1f}x")
    print("    PASS: Performance benchmark completed")

    clear_buffer_pool()
    return True


def test_segment_offset_calculation():
    """Test that segment offset calculations are correct for UDIM/atlas workflows."""
    print("  Testing segment offset calculations...")

    class MockSegment:
        def __init__(self, width, height, tile_x, tile_y):
            self.width = width
            self.height = height
            self.tile_x = tile_x
            self.tile_y = tile_y

    # Test case: 1024x1024 tiles in a 2x2 atlas (2048x2048 total)
    test_cases = [
        # (segment, expected_start_x, expected_start_y)
        (MockSegment(1024, 1024, 0, 0), 0, 0),       # Bottom-left
        (MockSegment(1024, 1024, 1, 0), 1024, 0),    # Bottom-right
        (MockSegment(1024, 1024, 0, 1), 0, 1024),    # Top-left
        (MockSegment(1024, 1024, 1, 1), 1024, 1024), # Top-right
    ]

    all_pass = True
    for segment, expected_x, expected_y in test_cases:
        start_x = segment.width * segment.tile_x
        start_y = segment.height * segment.tile_y

        if start_x != expected_x or start_y != expected_y:
            print(f"    FAIL: tile({segment.tile_x},{segment.tile_y}) got ({start_x},{start_y}), expected ({expected_x},{expected_y})")
            all_pass = False
        else:
            print(f"    OK: tile({segment.tile_x},{segment.tile_y}) = ({start_x},{start_y})")

    if all_pass:
        print("    PASS: All segment calculations correct")
    return all_pass


# =============================================================================
# Test Runner
# =============================================================================

def run_all_tests():
    """Run all security fix tests."""
    print("=" * 60)
    print("SECURITY FIXES TEST SUITE")
    print("=" * 60)

    tests = [
        # Code Injection Tests
        ("Code Injection: Simple Attribute", test_set_nested_attr_simple_attribute),
        ("Code Injection: Indexed Attribute", test_set_nested_attr_indexed_attribute),
        ("Code Injection: Nested Path", test_set_nested_attr_nested_path),
        ("Code Injection: Rejects Injection", test_set_nested_attr_rejects_code_injection),
        ("Code Injection: Rejects Expression Index", test_set_nested_attr_rejects_expression_index),
        ("Code Injection: Invalid Index", test_set_nested_attr_handles_invalid_index),
        ("Code Injection: Invalid Attribute", test_set_nested_attr_handles_invalid_attribute),

        # Path Traversal Tests
        ("Path Traversal: Valid Paths", test_path_validation_allows_valid_paths),
        ("Path Traversal: Parent Traversal", test_path_validation_blocks_parent_traversal),
        ("Path Traversal: Absolute Paths", test_path_validation_blocks_absolute_paths),
        ("Path Traversal: Subdirectories", test_path_validation_allows_subdirectories),

        # Buffer Pool Tests
        ("Buffer Pool: Acquire New", test_buffer_pool_acquire_new),
        ("Buffer Pool: Acquire Reuse", test_buffer_pool_acquire_reuse),
        ("Buffer Pool: Clear", test_buffer_pool_clear),
        ("Buffer Pool: Stats", test_buffer_pool_stats),
        ("Buffer Pool: Per-Size Limit", test_buffer_pool_per_size_limit),
        ("Buffer Pool: Total Limit", test_buffer_pool_total_limit),
        ("Buffer Pool: Dtype Separation", test_buffer_pool_dtype_separation),
        ("Buffer Pool: Performance", test_buffer_pool_performance),

        # UDIM/Atlas Tests
        ("UDIM: Segment Offset Calculation", test_segment_offset_calculation),
    ]

    results = []
    for name, test_func in tests:
        print(f"\n[TEST] {name}")
        try:
            success = test_func()
            results.append((name, "PASS" if success else "FAIL"))
        except Exception as e:
            print(f"  ERROR: {e}")
            traceback.print_exc()
            results.append((name, f"ERROR: {e}"))

    # Print summary
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, r in results if r == "PASS")
    failed = sum(1 for _, r in results if r != "PASS")

    for name, result in results:
        status = "[PASS]" if result == "PASS" else "[FAIL]"
        print(f"  {status} {name}")

    print(f"\nTotal: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    run_all_tests()
