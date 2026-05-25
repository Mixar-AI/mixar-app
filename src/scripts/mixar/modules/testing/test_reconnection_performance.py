#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Benchmark script for node reconnection performance.

This script measures the performance of the reconnect_layer_nodes() function
to determine if C++ optimization is worthwhile.

Usage:
    Run inside Blender:
    blender --background --python src/scripts/mixar/modules/testing/test_reconnection_performance.py
"""

import bpy
import time
import sys


def setup_test_material(num_layers=10):
    """Create a material with multiple layers for testing."""
    print(f"\nSetting up test material with {num_layers} layers...")

    # Clear existing scene
    bpy.ops.wm.read_homefile(use_empty=True)

    # Create a plane
    bpy.ops.mesh.primitive_plane_add()
    ob = bpy.context.object

    # Create material system
    bpy.ops.layers.create_material()

    # Add layers
    layer_creation_times = []
    for i in range(num_layers - 1):  # -1 because create_material adds one layer
        start = time.time()

        # Alternate between different layer types for realistic test
        if i % 3 == 0:
            bpy.ops.layers.add_paint_layer()
        elif i % 3 == 1:
            bpy.ops.layers.add_fill_layer()
        else:
            bpy.ops.layers.add_procedural_layer('INVOKE_DEFAULT', layer_type='NOISE')

        elapsed = (time.time() - start) * 1000  # ms
        layer_creation_times.append(elapsed)

    avg_creation_time = sum(layer_creation_times) / len(layer_creation_times) if layer_creation_times else 0
    print(f"  Average layer creation time: {avg_creation_time:.2f} ms")
    print(f"  Total layers created: {num_layers}")

    return ob


def benchmark_reconnection(num_iterations=10):
    """Benchmark the node reconnection function."""
    print(f"\nBenchmarking reconnection ({num_iterations} iterations)...")

    # Get material and layer info
    ob = bpy.context.active_object
    if not ob or not ob.active_material:
        print("  ERROR: No active object or material found!")
        return None

    mat = ob.active_material
    if not hasattr(mat.node_tree, 'mp'):
        print("  ERROR: Material is not a Mixar paint material!")
        return None

    mp = mat.node_tree.mp

    if not mp.layers:
        print("  ERROR: No layers found!")
        return None

    print(f"  Material has {len(mp.layers)} layers")

    # Import reconnection function
    from mixar.modules.paint.core.io.layer_connections import reconnect_layer_nodes

    # Warm-up run
    layer = mp.layers[0]
    reconnect_layer_nodes(layer)

    # Benchmark runs
    times = []
    for i in range(num_iterations):
        # Test reconnection on first layer
        start = time.time()
        reconnect_layer_nodes(layer)
        elapsed = (time.time() - start) * 1000  # ms
        times.append(elapsed)

    # Calculate statistics
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)

    print(f"\n  Results:")
    print(f"    Average: {avg_time:.3f} ms")
    print(f"    Min:     {min_time:.3f} ms")
    print(f"    Max:     {max_time:.3f} ms")

    # Assess if C++ optimization is worthwhile
    print(f"\n  Assessment:")
    if avg_time < 1.0:
        print(f"    WARNING: Very fast (<1ms) - C++ optimization may not be worthwhile")
        print(f"    The overhead of Python-C++ data conversion would likely")
        print(f"    exceed any performance gain.")
    elif avg_time < 10.0:
        print(f"    WARNING: Fast (<10ms) - C++ optimization borderline worthwhile")
        print(f"    Potential 2-5x speedup might not justify complexity.")
    elif avg_time < 100.0:
        print(f"    OK: Moderate (10-100ms) - C++ optimization could be beneficial")
        print(f"    Target: 2-10x speedup -> {avg_time/5:.1f}-{avg_time/2:.1f} ms")
    else:
        print(f"    RECOMMENDED: Slow (>100ms) - C++ optimization strongly recommended!")
        print(f"    Target: 5-10x speedup -> {avg_time/10:.1f}-{avg_time/5:.1f} ms")

    return avg_time


def benchmark_batch_operations(layer_counts=[5, 10, 20, 50]):
    """Benchmark with different layer counts to see scalability."""
    print("\n" + "="*60)
    print("BATCH SCALABILITY TEST")
    print("="*60)

    results = {}

    for count in layer_counts:
        print(f"\n{'-'*60}")
        print(f"Testing with {count} layers...")
        print(f"{'-'*60}")

        setup_test_material(count)
        avg_time = benchmark_reconnection(num_iterations=5)
        results[count] = avg_time

    # Analyze scalability
    print(f"\n{'='*60}")
    print("SCALABILITY ANALYSIS")
    print(f"{'='*60}\n")

    print("  Layers  | Avg Time  | Time/Layer | Scaling")
    print("  --------|-----------|------------|----------")

    baseline = results[layer_counts[0]]
    for count in layer_counts:
        avg_time = results[count]
        per_layer = avg_time / count
        scaling = avg_time / baseline
        print(f"  {count:6d}  | {avg_time:7.2f}ms | {per_layer:8.3f}ms | {scaling:6.2f}x")

    # Check if complexity is linear or worse
    last_count = layer_counts[-1]
    second_last_count = layer_counts[-2]
    complexity_ratio = results[last_count] / results[second_last_count]
    expected_linear = last_count / second_last_count

    print(f"\n  Complexity analysis:")
    print(f"    Actual ratio {last_count}/{second_last_count} layers: {complexity_ratio:.2f}x")
    print(f"    Expected (linear): {expected_linear:.2f}x")

    if complexity_ratio > expected_linear * 1.5:
        print(f"    WARNING: Appears to be worse than O(n) - optimization critical!")
    elif complexity_ratio > expected_linear * 1.2:
        print(f"    WARNING: Slightly worse than linear - optimization beneficial")
    else:
        print(f"    OK: Approximately linear scaling")


def main():
    """Main benchmark runner."""
    print("="*60)
    print("NODE RECONNECTION PERFORMANCE BENCHMARK")
    print("="*60)

    # Quick test first
    print("\n[1/2] Quick benchmark with 10 layers...")
    setup_test_material(10)
    quick_time = benchmark_reconnection(num_iterations=10)

    # If quick test shows it's worthwhile, do full batch test
    if quick_time and quick_time > 5.0:  # If >5ms, worth doing full test
        print("\n[2/2] Full scalability test...")
        benchmark_batch_operations([5, 10, 20, 50])
    elif quick_time:
        print("\n[2/2] Skipping full test - reconnection too fast for C++ to help")
        print(f"      ({quick_time:.2f}ms average - Python-C++ conversion overhead")
        print(f"       would likely exceed any performance gain)")
    else:
        print("\n[2/2] Benchmark failed - skipping full test")

    print("\n" + "="*60)
    print("BENCHMARK COMPLETE")
    print("="*60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nError during benchmark: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
