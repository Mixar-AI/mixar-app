# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Input-driven World Labs mode — no Blender imports."""


def resolve_world_labs_mode(catalog_mode, *, has_image, has_prompt):
    """Mode we will actually submit. Never send ``image`` without image bytes.

    The catalog default is ``image``. A prompt-only body that keeps that
    default is charged and then rejected server-side for a missing
    ``image_s3_key``. Honor an explicit text choice; otherwise fall back
    to text when the user only typed a prompt.
    """
    catalog_mode = str(catalog_mode or "").strip().lower()
    if catalog_mode == "text":
        return "text"
    if has_image:
        return "image"
    if has_prompt:
        return "text"
    return catalog_mode or "text"
