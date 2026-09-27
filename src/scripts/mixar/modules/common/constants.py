# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Shared developer UI fixtures; independent of scene and service state."""
UI_GALLERY_ENUM_ITEMS = (
    ("LOW", "Low", "Non-contiguous enum value 3", 3),
    ("MEDIUM", "Medium", "Non-contiguous enum value 11", 11),
    ("HIGH", "High", "Non-contiguous enum value 27", 27),
)
UI_GALLERY_UNICODE = "材質 · café · 🎨"

FOREST_VIEWPORT_RGB = (15 / 255,) * 3  # #0F0F0F, display-referred RNA color.
FOREST_MOODBOARD_RGB = (30 / 255,) * 3  # #1E1E1E, shared by drawer and editor.

# Display-space ink shared by the Moodboard pencil and viewport Sketch.
SKETCH_COLOR_RGB = (105, 111, 108)  # #696F6C
SKETCH_COLOR_RGBA = tuple(channel / 255 for channel in SKETCH_COLOR_RGB) + (1.0,)
