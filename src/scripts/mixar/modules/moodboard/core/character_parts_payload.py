# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Align normalized SAM component masks to their unchanged source pixels."""

import base64
import io

from PIL import Image


def encode_source_and_masks(source_png, mask_pngs):
    """SAM can return scaled masks; nearest-neighbor preserves their hard edges."""
    with Image.open(io.BytesIO(source_png)) as source:
        source_size = source.size
    masks = []
    for mask_png in mask_pngs:
        with Image.open(io.BytesIO(mask_png)) as mask:
            if mask.size != source_size:
                mask = mask.resize(source_size, Image.Resampling.NEAREST)
                buffer = io.BytesIO()
                mask.save(buffer, format='PNG')
                mask_png = buffer.getvalue()
        masks.append(base64.b64encode(mask_png).decode('ascii'))
    return base64.b64encode(source_png).decode('ascii'), masks
