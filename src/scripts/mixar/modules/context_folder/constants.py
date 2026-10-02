# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Wire, limit and file-kind constants for context folders."""

PROTOCOL_VERSION = 1
# Advertised in the WebSocket handshake; the backend sends no
# ``context_folder.*`` request to a client that never advertised it.
CAPABILITY = "context_folder_v1"

RPC_PREFIX = "context_folder."
RPC_LIST = "context_folder.list"
RPC_READ = "context_folder.read"
RPC_SEARCH = "context_folder.search"
RPC_VIEW_IMAGE = "context_folder.view_image"
RPC_METHODS = frozenset({RPC_LIST, RPC_READ, RPC_SEARCH, RPC_VIEW_IMAGE})

# Folders one chat may carry at once.
MAX_FOLDERS = 5
# Files indexed per folder; a larger folder is indexed up to this many and
# reported ``truncated`` so the agent knows the listing is partial.
MAX_INDEXED_FILES = 2000
MAX_DEPTH = 8
# Files the per-turn manifest lists; the rest stay reachable through list.
MAX_MANIFEST_FILES = 150
# Key documents (README, notes, briefs) quoted in the manifest.
MAX_MANIFEST_NOTES = 3
NOTE_EXCERPT_CHARS = 1200
NOTE_MAX_BYTES = 256 * 1024
# A re-send within this window reuses the folder's last index.
INDEX_TTL_S = 15.0

MAX_LIST_PAGE = 200
MAX_READ_CHARS = 24000
MAX_TEXT_FILE_BYTES = 8 * 1024 * 1024
MAX_SEARCH_RESULTS = 60
MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024
MAX_SEARCH_LINE_CHARS = 240
MAX_QUERY_CHARS = 200
MAX_IMAGE_DIM = 1024
MAX_IMAGE_SOURCE_BYTES = 64 * 1024 * 1024
MAX_IMPORT_NAMES = 20

# Directory names never indexed: VCS metadata, dependency trees, caches.
# Any name starting with "." is skipped as well.
IGNORED_DIRS = frozenset({
    "node_modules", "__pycache__", "venv", "env", "site-packages",
    "__MACOSX", "$RECYCLE.BIN", "System Volume Information",
})

KIND_TEXT = "text"
KIND_IMAGE = "image"
KIND_MODEL = "model"
KIND_DOCUMENT = "document"
KIND_VIDEO = "video"
KIND_AUDIO = "audio"
KIND_OTHER = "other"
KINDS = (KIND_TEXT, KIND_IMAGE, KIND_MODEL, KIND_DOCUMENT, KIND_VIDEO, KIND_AUDIO, KIND_OTHER)

TEXT_SUFFIXES = frozenset({
    ".txt", ".md", ".markdown", ".rst", ".json", ".csv", ".tsv", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".xml", ".html", ".htm", ".py", ".js",
    ".ts", ".glsl", ".osl", ".lua", ".log", ".srt", ".mtl", ".svg",
})
# Every suffix Pillow can decode for a preview, plus Blender-only HDR formats
# (importable as Blender images; previewed only when Pillow can read them).
IMAGE_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga", ".tif", ".tiff",
    ".gif", ".exr", ".hdr",
})
PREVIEWABLE_IMAGE_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga", ".tif", ".tiff", ".gif",
})
MODEL_SUFFIXES = frozenset({
    ".obj", ".fbx", ".glb", ".gltf", ".usd", ".usda", ".usdc", ".usdz",
    ".stl", ".ply", ".abc", ".blend",
})
DOCUMENT_SUFFIXES = frozenset({".pdf", ".doc", ".docx", ".odt", ".pages", ".ppt", ".pptx", ".key"})
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v"})
AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".ogg", ".flac", ".aac", ".m4a"})

# Basenames (lower case, without suffix) the manifest quotes first: the files a
# person leaves in a folder to explain it.
NOTE_STEMS = ("readme", "brief", "notes", "spec", "instructions", "description", "todo")
