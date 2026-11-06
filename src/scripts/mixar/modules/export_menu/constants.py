# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export sheet catalogue: the format tiles, their sections and what each runs.

Tile labels are file extensions or product names and are never translated;
section captions and the Web tile are (``n_``).
"""

from mixar.modules.common.i18n import n_

# Pipelines a format runs (`core/runner.py`).
KIND_MODEL = "MODEL"      # agent export lane, `export_to_path`
KIND_PROJECT = "PROJECT"  # copy save of the open file
KIND_IMAGE = "IMAGE"      # scene_render still
KIND_VIDEO = "VIDEO"      # scene_render animation
KIND_WEB = "WEB"          # Publish to Web


class Format:
    __slots__ = ("key", "label", "icon", "kind", "use_case", "translate")

    def __init__(self, key, label, icon, kind, use_case="other", translate=False):
        self.key = key
        self.label = label
        self.icon = icon
        self.kind = kind
        self.use_case = use_case
        self.translate = translate


FORMATS = (
    Format("BLEND", ".blend", "BLENDER", KIND_PROJECT),
    Format("MIXAR", ".mixar", "MIXAR_ICON", KIND_PROJECT),
    Format("GLB", ".glb", "FILE_3D", KIND_MODEL),
    Format("FBX", ".fbx", "ARMATURE_DATA", KIND_MODEL),
    Format("OBJ", ".obj", "MESH_CUBE", KIND_MODEL),
    Format("UNREAL", "Unreal", "", KIND_MODEL, use_case="unreal"),
    Format("UNITY", "Unity", "GHOST_ENABLED", KIND_MODEL, use_case="unity"),
    Format("WEB", n_("Web"), "WORLD", KIND_WEB, translate=True),
    Format("PNG", ".png", "FILE_IMAGE", KIND_IMAGE),
    Format("MP4", ".mp4", "FILE_MOVIE", KIND_VIDEO),
)
BY_KEY = {fmt.key: fmt for fmt in FORMATS}

SECTIONS = (
    (n_("3D FILES"), ("BLEND", "MIXAR", "GLB", "FBX", "OBJ")),
    (n_("GAME ENGINES & WEB"), ("UNREAL", "UNITY", "WEB")),
    (n_("IMAGE & VIDEO"), ("PNG", "MP4")),
)
TILES_PER_ROW = 4

FORMAT_ITEMS = [(fmt.key, fmt.label, "") for fmt in FORMATS]

QUALITY_ITEMS = [
    ("FAST", n_("Fast"), n_("EEVEE at half resolution: a quick preview")),
    ("GOOD", n_("Good"), n_("EEVEE at full resolution")),
    ("AWESOME", n_("Awesome"), n_("Cycles at full resolution: slowest, best light")),
]

# scene_render options per quality; width/height scale the scene resolution.
RENDER_QUALITY = {
    "FAST": {"engine": "eevee", "samples": 16, "scale": 0.5},
    "GOOD": {"engine": "eevee", "samples": 64, "scale": 1.0},
    "AWESOME": {"engine": "cycles", "samples": 256, "video_samples": 128, "scale": 1.0},
}

GLTF_ITEMS = [
    ("GLB", n_("Single .glb"), n_("One binary file with textures inside")),
    ("GLTF", n_("Separate .gltf"), n_("A .gltf with its buffers and textures beside it")),
]
ENGINE_FORMAT_ITEMS = [
    ("FBX", "FBX", ""),
    ("GLB", "glTF", ""),
]
IMAGE_FORMAT_ITEMS = [
    ("PNG", "PNG", ""),
    ("WEBP", "WebP", ""),
]
VIDEO_FORMAT_ITEMS = [
    ("MP4", "MP4", ""),
    ("WEBM", "WebM", ""),
]

# Options the sheet's chips and switches may set (`mixar.export_menu_option`).
CHOICE_OPTIONS = ("quality", "gltf_variant", "engine_format", "image_format", "video_format")
SWITCH_OPTIONS = ("selected_only", "strip_chat", "include_animation")

# Extension written for each (format, variant).
EXTENSIONS = {
    "BLEND": ".blend", "MIXAR": ".mixar", "FBX": ".fbx", "OBJ": ".obj",
    "GLB": ".glb", "GLTF": ".gltf", "PNG": ".png", "WEBP": ".webp",
    "MP4": ".mp4", "WEBM": ".webm",
}

TOAST_ID = "export-menu"
