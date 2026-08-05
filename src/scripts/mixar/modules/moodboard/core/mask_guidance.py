# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lossless mask constraints shared by SAM3-guided component workflows."""

from io import BytesIO


def constrain_refined_mask(refined_bytes: bytes, guide_bytes: bytes) -> bytes:
    """Intersect a SAM3 result with its user-drawn guide mask.

    SAM3 may expand from the prompted region to a larger connected object. The
    user's lasso is the authoritative inclusion boundary for component detail
    generation, so pixels outside it must never reach Gemini.
    """
    if not refined_bytes or not guide_bytes:
        raise ValueError("Both refined and guide masks are required")

    from PIL import Image, ImageChops

    with Image.open(BytesIO(refined_bytes)) as refined_opened:
        refined = refined_opened.convert("L")
    with Image.open(BytesIO(guide_bytes)) as guide_opened:
        guide = guide_opened.convert("L")

    if guide.size != refined.size:
        guide = guide.resize(refined.size, Image.Resampling.NEAREST)
    refined = refined.point(lambda value: 255 if value >= 128 else 0, mode="L")
    guide = guide.point(lambda value: 255 if value >= 128 else 0, mode="L")
    constrained = ImageChops.multiply(refined, guide)
    if constrained.getbbox() is None:
        raise ValueError("SAM3 result does not overlap the original lasso")

    output = BytesIO()
    constrained.save(output, format="PNG", optimize=True)
    return output.getvalue()
