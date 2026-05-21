# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for image processing during baking operations."""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def process_baked_images(
    operator,
    channels,
    tree,
    baked_exists,
    use_dithering,
    dither_intensity,
    denoise,
    aa_level,
    width,
    height,
    fxaa,
    bake_device,
):
    """Process baked images with dithering, denoising, AA, and FXAA.

    Args:
        operator: The operator instance for calling image processing functions
        channels: List of channels to process
        tree: Node tree
        baked_exists: List of booleans indicating if baked node existed before
        use_dithering: Whether to apply dithering
        dither_intensity: Dithering intensity
        denoise: Whether to apply denoising
        aa_level: Anti-aliasing level
        width: Target width
        height: Target height
        fxaa: Whether to apply FXAA
        bake_device: Device to use for baking

    Returns:
        List of baked images
    """
    from .bake_common import denoise_image, dither_image, fxaa_image, resize_image

    baked_images = []
    for i, ch in enumerate(channels):
        if ch.no_layer_using:
            continue

        baked = tree.nodes.get(ch.baked)
        if baked and baked.image:

            # Only expand baked data when baked is just created
            if not baked_exists[i]:
                ch.expand_baked_data = True

            # Dithering
            if (
                ch.type == "RGB"
                and ch.colorspace == "SRGB"
                and use_dithering
                and ch.use_clamp
            ):
                dither_image(
                    baked.image,
                    dither_intensity=dither_intensity,
                    alpha_aware=ch.enable_alpha,
                )

            # Denoise
            if denoise and ch.type != "NORMAL":
                denoise_image(baked.image)

            # AA process
            if aa_level > 1:
                resize_image(
                    baked.image,
                    width,
                    height,
                    baked.image.colorspace_settings.name,
                    alpha_aware=ch.enable_alpha,
                    bake_device=bake_device,
                )

            # FXAA doesn't work with hdr image
            if fxaa and ch.use_clamp:
                fxaa_image(
                    baked.image, ch.enable_alpha, bake_device=bake_device
                )

            baked_images.append(baked.image)

        if ch.type == "NORMAL":
            baked_images.extend(
                _process_normal_channel_images(
                    ch, tree, denoise, aa_level, width, height, fxaa, bake_device, baked
                )
            )

    return baked_images


def _process_normal_channel_images(
    ch, tree, denoise, aa_level, width, height, fxaa, bake_device, baked
):
    """Process normal channel specific images (displacement, overlay, vdisp).

    Args:
        ch: The channel
        tree: Node tree
        denoise: Whether to apply denoising
        aa_level: Anti-aliasing level
        width: Target width
        height: Target height
        fxaa: Whether to apply FXAA
        bake_device: Device to use for baking
        baked: The baked node

    Returns:
        List of processed images
    """
    from .bake_common import denoise_image, fxaa_image, resize_image

    images = []

    baked_disp = tree.nodes.get(ch.baked_disp)
    if baked_disp and baked_disp.image:

        # Denoise
        if denoise:
            denoise_image(baked_disp.image)

        # AA process
        if aa_level > 1:
            resize_image(
                baked_disp.image,
                width,
                height,
                baked.image.colorspace_settings.name if baked else "sRGB",
                alpha_aware=ch.enable_alpha,
                bake_device=bake_device,
            )

        # FXAA
        if fxaa and not baked_disp.image.is_float:
            fxaa_image(
                baked_disp.image,
                ch.enable_alpha,
                bake_device=bake_device,
            )

        images.append(baked_disp.image)

    baked_normal_overlay = tree.nodes.get(ch.baked_normal_overlay)
    if baked_normal_overlay and baked_normal_overlay.image:

        # AA process
        if aa_level > 1:
            resize_image(
                baked_normal_overlay.image,
                width,
                height,
                baked.image.colorspace_settings.name if baked else "sRGB",
                alpha_aware=ch.enable_alpha,
                bake_device=bake_device,
            )
        # FXAA
        if fxaa:
            fxaa_image(
                baked_normal_overlay.image,
                ch.enable_alpha,
                bake_device=bake_device,
            )

        images.append(baked_normal_overlay.image)

    baked_vdisp = tree.nodes.get(ch.baked_vdisp)
    if baked_vdisp and baked_vdisp.image:

        # AA process
        if aa_level > 1:
            resize_image(
                baked_vdisp.image,
                width,
                height,
                baked.image.colorspace_settings.name if baked else "sRGB",
                alpha_aware=ch.enable_alpha,
                bake_device=bake_device,
            )

        images.append(baked_vdisp.image)

    return images


def set_bake_info_to_images(baked_images, operator):
    """Set bake info attributes to baked images.

    Args:
        baked_images: List of images to set info on
        operator: Operator instance to get attributes from
    """
    for img in baked_images:
        bi = img.m_bake_info
        for attr in dir(bi):
            # if attr in dir(self):
            if attr.startswith("__"):
                continue
            if attr.startswith("bl_"):
                continue
            if attr in {"rna_type"}:
                continue
            try:
                setattr(bi, attr, getattr(operator, attr))
            except Exception:
                pass
        bi.is_baked = True
        bi.is_baked_channel = True
