# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Encode the outgoing chat attachments, index-aligned with the send list.

Main thread entry (``BLEND_DATA`` reads ``bpy.data``); ``FILE`` images are
compressed on the encoder thread pool. The result has one slot per outgoing
attachment — ``(base64, mime_type)`` or ``None`` — so
``attachment_pairing.pair_names_with_images`` can attach each resolved name to
exactly the image it belongs to.
"""

import os
from concurrent.futures import TimeoutError as FuturesTimeoutError

from mixar.config.logging_config import get_logger

from .image_utils import encode_attachment_for_upload
from mixar.modules.common.i18n import rpt_

logger = get_logger(__name__)

# Per-image budget. Compression bounds the work (a 12MP photo is decoded at
# reduced scale and re-encoded in well under a second), so a timeout here
# means something is genuinely wrong with that one image — drop it and send
# the rest, never the whole set.
TIMEOUT_PER_IMAGE = 10.0


def encode_outgoing_attachments(outgoing_attachments, executor, report=None) -> list:
    """``[(base64, mime_type) | None]`` aligned with ``outgoing_attachments``.

    ``report(level_set, text)`` is the operator's report, used to warn about
    a skipped image. A skipped attachment keeps its ``None`` slot.
    """
    encoding_futures = []
    attachment_data = []  # (path, source) per attachment
    for att in outgoing_attachments:
        attachment_data.append((att.image_path, att.image_source))
        if att.image_source == 'FILE':
            # FILE images (read + PIL compress) are safe off the main thread
            future = executor.submit(
                encode_attachment_for_upload, att.image_path, att.image_source
            )
            encoding_futures.append(future)
        else:
            # BLEND_DATA images access bpy.data — must stay on main thread
            encoding_futures.append(None)

    results = []
    for idx, future in enumerate(encoding_futures):
        att_path, att_source = attachment_data[idx]
        try:
            if att_source == 'MODEL_FILE':
                encoded = None  # imported scene objects, never an image
            elif future is None:
                # BLEND_DATA: encode on main thread (bpy.data access)
                encoded = encode_attachment_for_upload(att_path, att_source)
            else:
                encoded = future.result(timeout=TIMEOUT_PER_IMAGE)
        except FuturesTimeoutError:
            logger.error(f"Image encoding timeout for {att_path}")
            if report:
                report({'WARNING'}, rpt_("Skipped slow image: {name}").format(
                    name=os.path.basename(att_path)))
            results.append(None)
            continue
        except Exception as e:
            logger.error(f"Image encoding error for {att_path}: {e}")
            if report:
                report({'WARNING'}, rpt_("Image encoding failed: {error}").format(error=e))
            results.append(None)
            continue

        if encoded:
            b64, mime_type = encoded
            results.append((b64, mime_type))
        else:
            if att_source != 'MODEL_FILE':
                logger.warning(f"Failed to encode attachment index {idx}")
            results.append(None)
    return results
