# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Prompt/image slugs for generated mesh names — no Blender imports."""

import re

# Only these trailing extensions are stripped from a label — a bare "." in a
# name (e.g. "R2.D2", "v1.5") must NOT be treated as a file extension.
_STRIPPABLE_EXTS = (
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
    ".exr", ".gif",
    ".glb", ".gltf", ".fbx", ".obj", ".usd", ".usdz",
)


def sanitize_label(label: str) -> str:
    base = label or ""
    lower = base.lower()
    for ext in _STRIPPABLE_EXTS:
        if lower.endswith(ext):
            base = base[: -len(ext)]
            break
    base = re.sub(r'[^a-zA-Z0-9_]', '_', base)
    base = re.sub(r'_+', '_', base).strip('_') or "object"
    return base


def slug_from_prompt(prompt: str, max_words: int = 6, max_len: int = 40) -> str:
    """Concise underscore slug from a prompt.

    Mirrors the backend imagegen naming (`_derive_image_name_from_prompt`)
    so a mesh generated from a prompt reads like its image-gen twin:
    'A red sports car on a road' -> 'red_sports_car_on_a_road'. Returns ''
    when the prompt has no usable words.
    """
    if not prompt:
        return ""
    words = re.findall(r"[a-z0-9]+", prompt.lower())
    # Drop a single leading article so 'a wizard' -> 'wizard'.
    if words and words[0] in ("a", "an", "the"):
        words = words[1:]
    name = ""
    for word in words[:max_words]:
        candidate = f"{name}_{word}" if name else word
        if len(candidate) > max_len:
            break
        name = candidate
    return name


def derive_model_name(image=None, prompt: str = "", explicit: str = "") -> str:
    """Resolve the object name for a generated 3D mesh.

    Priority: an explicit (agent-supplied) name, else the input image's
    name, else a semantic slug derived from the prompt. Returns '' when
    nothing usable is available — the caller's on_imported hook then falls
    back to the queue label.
    """
    if explicit and explicit.strip():
        return sanitize_label(explicit)
    if image is not None and getattr(image, "name", ""):
        return sanitize_label(image.name)
    slug = slug_from_prompt(prompt or "")
    return sanitize_label(slug) if slug else ""
