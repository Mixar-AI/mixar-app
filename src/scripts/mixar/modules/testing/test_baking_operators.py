# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Test script for BAKING_OT_* operators.

Run this script in Blender's Python console or as a script to test the
baking operators. Make sure to build Blender with the space_baking module.

Usage:
    Run inside Blender:
    blender --background --python src/scripts/mixar/modules/testing/test_baking_operators.py

    Or run from Blender's Scripting workspace:
    1. Open Blender
    2. Go to Scripting workspace
    3. Open this file and run it

Note: Set BLENDER_LOG=ed.baking:2 in environment before starting Blender
to see detailed logging output.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def create_test_image(name, width=256, height=256, color=(0.5, 0.5, 0.5, 1.0)):
    """Create a test image with a solid color."""
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])

    image = bpy.data.images.new(name, width=width, height=height, float_buffer=True)

    # Fill with color
    pixels = [0.0] * (width * height * 4)
    for i in range(width * height):
        idx = i * 4
        pixels[idx] = color[0]      # R
        pixels[idx + 1] = color[1]  # G
        pixels[idx + 2] = color[2]  # B
        pixels[idx + 3] = color[3]  # A

    image.pixels[:] = pixels
    return image


def create_gradient_image(name, width=256, height=256):
    """Create a test image with a gradient."""
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])

    image = bpy.data.images.new(name, width=width, height=height, float_buffer=True)

    pixels = [0.0] * (width * height * 4)
    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            # Horizontal gradient
            val = x / (width - 1)
            pixels[idx] = val
            pixels[idx + 1] = val
            pixels[idx + 2] = val
            pixels[idx + 3] = 1.0

    image.pixels[:] = pixels
    return image


def create_checkerboard_image(name, width=256, height=256, tile_size=32):
    """Create a checkerboard pattern for edge detection testing."""
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])

    image = bpy.data.images.new(name, width=width, height=height, float_buffer=True)

    pixels = [0.0] * (width * height * 4)
    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            # Checkerboard pattern
            val = 1.0 if ((x // tile_size) + (y // tile_size)) % 2 == 0 else 0.0
            pixels[idx] = val
            pixels[idx + 1] = val
            pixels[idx + 2] = val
            pixels[idx + 3] = 1.0

    image.pixels[:] = pixels
    return image


def test_pixel_operations():
    """Test pixel copy and set operations."""
    print("\n=== Testing Pixel Operations ===")

    src_image = create_test_image("test_src", 256, 256, (1.0, 0.5, 0.25, 1.0))
    dst_image = create_test_image("test_dst", 256, 256, (0.0, 0.0, 0.0, 1.0))

    # Test copy_image_pixels
    result = bpy.ops.baking.copy_image_pixels(
        src_image=src_image,
        dest_image=dst_image,
        width=256,
        height=256
    )
    print(f"copy_image_pixels: {result}")

    # Verify copy worked
    dst_pixels = list(dst_image.pixels[:4])
    print(f"  Dst pixel after copy: R={dst_pixels[0]:.3f}, G={dst_pixels[1]:.3f}, B={dst_pixels[2]:.3f}")

    # Test copy_image_channel_pixels (copy R channel to G channel)
    result = bpy.ops.baking.copy_image_channel_pixels(
        src_image=src_image,
        dest_image=dst_image,
        width=256,
        height=256,
        src_channel=0,  # R
        dst_channel=1   # G
    )
    print(f"copy_image_channel_pixels: {result}")

    # Test set_image_pixels
    result = bpy.ops.baking.set_image_pixels(
        image=dst_image,
        width=256,
        height=256,
        value=0.75
    )
    print(f"set_image_pixels: {result}")

    return True


def test_colorspace_operations():
    """Test color space conversion operations."""
    print("\n=== Testing Color Space Operations ===")

    # Create sRGB image (mid gray)
    srgb_image = create_test_image("test_srgb", 256, 256, (0.5, 0.5, 0.5, 1.0))

    # Convert to linear
    result = bpy.ops.baking.pixels_to_linear(
        image=srgb_image,
        width=256,
        height=256
    )
    print(f"pixels_to_linear: {result}")

    # Check result (sRGB 0.5 -> linear ~0.214)
    linear_pixel = list(srgb_image.pixels[:4])
    print(f"  After to_linear: R={linear_pixel[0]:.4f} (expected ~0.214)")

    # Convert back to sRGB
    result = bpy.ops.baking.pixels_to_srgb(
        image=srgb_image,
        width=256,
        height=256
    )
    print(f"pixels_to_srgb: {result}")

    srgb_pixel = list(srgb_image.pixels[:4])
    print(f"  After to_srgb: R={srgb_pixel[0]:.4f} (expected ~0.5)")

    return True


def test_alpha_operations():
    """Test alpha multiply/divide operations."""
    print("\n=== Testing Alpha Operations ===")

    # Create image with varying alpha
    alpha_image = create_test_image("test_alpha", 256, 256, (1.0, 0.5, 0.25, 0.5))

    # Multiply RGB by alpha (premultiply)
    result = bpy.ops.baking.multiply_rgb_by_alpha(
        image=alpha_image,
        width=256,
        height=256
    )
    print(f"multiply_rgb_by_alpha: {result}")

    premul_pixel = list(alpha_image.pixels[:4])
    print(f"  After premultiply: R={premul_pixel[0]:.3f}, G={premul_pixel[1]:.3f}, B={premul_pixel[2]:.3f}")
    print(f"  (Expected: R=0.5, G=0.25, B=0.125)")

    # Divide RGB by alpha (unpremultiply)
    result = bpy.ops.baking.divide_rgb_by_alpha(
        image=alpha_image,
        width=256,
        height=256
    )
    print(f"divide_rgb_by_alpha: {result}")

    unpremul_pixel = list(alpha_image.pixels[:4])
    print(f"  After unpremultiply: R={unpremul_pixel[0]:.3f}, G={unpremul_pixel[1]:.3f}, B={unpremul_pixel[2]:.3f}")

    return True


def test_filter_operations():
    """Test filter operations (blur, bilateral, FXAA)."""
    print("\n=== Testing Filter Operations ===")

    # Create gradient image for blur testing
    blur_image = create_gradient_image("test_blur", 256, 256)

    # Test Gaussian blur
    result = bpy.ops.baking.gaussian_blur(
        image=blur_image,
        width=256,
        height=256,
        radius=5,
        sigma=2.0
    )
    print(f"gaussian_blur: {result}")

    # Test box blur
    blur_image2 = create_gradient_image("test_box_blur", 256, 256)
    result = bpy.ops.baking.box_blur(
        image=blur_image2,
        width=256,
        height=256,
        radius=3
    )
    print(f"box_blur: {result}")

    # Test bilateral filter
    bilateral_image = create_checkerboard_image("test_bilateral", 256, 256, 16)
    result = bpy.ops.baking.bilateral_filter(
        image=bilateral_image,
        width=256,
        height=256,
        radius=5,
        sigma_space=3.0,
        sigma_color=0.1
    )
    print(f"bilateral_filter: {result}")

    # Test FXAA
    fxaa_image = create_checkerboard_image("test_fxaa", 256, 256, 32)
    result = bpy.ops.baking.fxaa(
        image=fxaa_image,
        width=256,
        height=256
    )
    print(f"fxaa: {result}")

    return True


def test_morphology_operations():
    """Test morphological operations (dilate, erode, sobel)."""
    print("\n=== Testing Morphology Operations ===")

    # Create binary-like image for morphology
    morph_image = create_test_image("test_morph", 256, 256, (0.0, 0.0, 0.0, 1.0))

    # Set a small white square in the center
    pixels = list(morph_image.pixels)
    for y in range(120, 136):
        for x in range(120, 136):
            idx = (y * 256 + x) * 4
            pixels[idx] = 1.0
            pixels[idx + 1] = 1.0
            pixels[idx + 2] = 1.0
    morph_image.pixels[:] = pixels

    # Test dilate
    result = bpy.ops.baking.dilate(
        image=morph_image,
        width=256,
        height=256,
        radius=3,
        channel=0  # R channel
    )
    print(f"dilate: {result}")

    # Test erode
    erode_image = create_test_image("test_erode", 256, 256, (1.0, 1.0, 1.0, 1.0))

    # Set a small black square in the center
    pixels = list(erode_image.pixels)
    for y in range(120, 136):
        for x in range(120, 136):
            idx = (y * 256 + x) * 4
            pixels[idx] = 0.0
            pixels[idx + 1] = 0.0
            pixels[idx + 2] = 0.0
    erode_image.pixels[:] = pixels

    result = bpy.ops.baking.erode(
        image=erode_image,
        width=256,
        height=256,
        radius=2,
        channel=0
    )
    print(f"erode: {result}")

    # Test sobel edge detection
    edge_image = create_checkerboard_image("test_edges", 256, 256, 32)
    result = bpy.ops.baking.sobel_edge_detect(
        image=edge_image,
        width=256,
        height=256
    )
    print(f"sobel_edge_detect: {result}")

    return True


def test_statistics_operations():
    """Test statistics operations (minmax, normalize)."""
    print("\n=== Testing Statistics Operations ===")

    # Create image with known range
    stats_image = create_test_image("test_stats", 256, 256, (0.25, 0.5, 0.75, 1.0))

    # Test get_image_minmax
    result = bpy.ops.baking.get_image_minmax(
        image=stats_image,
        width=256,
        height=256
    )
    print(f"get_image_minmax: {result}")

    # NOTE: Result values are stored in the operator properties
    # Access via op.properties['min_value'] and op.properties['max_value']
    # when called with invoke or from a panel

    # Test normalize
    norm_image = create_gradient_image("test_normalize", 256, 256)

    # Modify to have range [0.2, 0.8]
    pixels = list(norm_image.pixels)
    for i in range(0, len(pixels), 4):
        for c in range(3):
            pixels[i + c] = pixels[i + c] * 0.6 + 0.2
    norm_image.pixels[:] = pixels

    result = bpy.ops.baking.normalize_image(
        image=norm_image,
        width=256,
        height=256,
        target_min=0.0,
        target_max=1.0
    )
    print(f"normalize_image: {result}")

    # Check range after normalization
    pixels_after = list(norm_image.pixels)
    min_val = min(pixels_after[i] for i in range(0, len(pixels_after), 4))
    max_val = max(pixels_after[i] for i in range(0, len(pixels_after), 4))
    print(f"  Range after normalize: [{min_val:.4f}, {max_val:.4f}]")

    return True


def test_normal_map_operations():
    """Test normal map operations (height_to_normal, blend_normal_maps)."""
    print("\n=== Testing Normal Map Operations ===")

    # Create a height map (gradient as simple height)
    height_image = create_gradient_image("test_height", 256, 256)

    # Test height_to_normal
    result = bpy.ops.baking.height_to_normal(
        image=height_image,
        width=256,
        height=256,
        strength=1.0
    )
    print(f"height_to_normal: {result}")

    # Check that center pixel is now a normal (should have R, G near 0.5, B near 1.0)
    center_idx = (128 * 256 + 128) * 4
    pixels = list(height_image.pixels)
    print(f"  Center normal: R={pixels[center_idx]:.3f}, G={pixels[center_idx+1]:.3f}, B={pixels[center_idx+2]:.3f}")

    # Create two normal maps for blending test
    base_normal = create_test_image("test_base_normal", 256, 256, (0.5, 0.5, 1.0, 1.0))
    detail_normal = create_test_image("test_detail_normal", 256, 256, (0.6, 0.5, 0.8, 1.0))

    # Test blend_normal_maps
    result = bpy.ops.baking.blend_normal_maps(
        base_image=base_normal,
        detail_image=detail_normal,
        width=256,
        height=256,
        detail_strength=0.5
    )
    print(f"blend_normal_maps: {result}")

    return True


def test_blend_operations():
    """Test blend operations (blend_images, dither_image)."""
    print("\n=== Testing Blend Operations ===")

    # Create two images for blending
    base_image = create_test_image("test_blend_base", 256, 256, (0.2, 0.4, 0.6, 1.0))
    overlay_image = create_test_image("test_blend_overlay", 256, 256, (0.8, 0.6, 0.4, 1.0))

    # Test blend_images with different modes
    blend_modes = ['MIX', 'ADD', 'MULTIPLY', 'SCREEN', 'OVERLAY']

    for mode in blend_modes:
        # Reset base image
        base_image = create_test_image("test_blend_base", 256, 256, (0.2, 0.4, 0.6, 1.0))

        result = bpy.ops.baking.blend_images(
            base_image=base_image,
            blend_image=overlay_image,
            width=256,
            height=256,
            opacity=0.5,
            blend_mode=mode
        )

        # Get result pixel
        pixels = list(base_image.pixels[:4])
        print(f"blend_images ({mode}): {result} -> R={pixels[0]:.3f}, G={pixels[1]:.3f}, B={pixels[2]:.3f}")

    # Test dither_image
    dither_image = create_gradient_image("test_dither", 256, 256)

    # Get pixel before dithering
    before = list(dither_image.pixels[512:516])  # Sample a pixel

    result = bpy.ops.baking.dither_image(
        image=dither_image,
        width=256,
        height=256,
        amount=0.01,
        seed=42
    )
    print(f"dither_image: {result}")

    # Get pixel after dithering
    after = list(dither_image.pixels[512:516])
    print(f"  Before dither: R={before[0]:.4f}")
    print(f"  After dither:  R={after[0]:.4f}")

    return True


def run_all_tests():
    """Run all baking operator tests."""
    print("=" * 60)
    print("BAKING OPERATORS TEST SUITE")
    print("=" * 60)

    tests = [
        ("Pixel Operations", test_pixel_operations),
        ("Color Space Operations", test_colorspace_operations),
        ("Alpha Operations", test_alpha_operations),
        ("Filter Operations", test_filter_operations),
        ("Morphology Operations", test_morphology_operations),
        ("Statistics Operations", test_statistics_operations),
        ("Normal Map Operations", test_normal_map_operations),
        ("Blend Operations", test_blend_operations),
    ]

    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, "PASS" if success else "FAIL"))
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, f"ERROR: {e}"))

    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    for name, result in results:
        status = "[PASS]" if result == "PASS" else "[FAIL]"
        print(f"  {status} {name}")

    print("\n" + "=" * 60)
    print("Test images created in bpy.data.images:")
    for img in bpy.data.images:
        if img.name.startswith("test_"):
            print(f"  - {img.name} ({img.size[0]}x{img.size[1]})")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
