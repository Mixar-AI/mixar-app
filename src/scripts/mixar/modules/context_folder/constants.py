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
RPC_VIEW_VIDEO = "context_folder.view_video"
RPC_VIEW_PDF_PAGES = "context_folder.view_pdf_pages"
RPC_METHODS = frozenset({RPC_LIST, RPC_READ, RPC_SEARCH, RPC_VIEW_IMAGE, RPC_VIEW_VIDEO,
                         RPC_VIEW_PDF_PAGES})
# Advertised separately from CAPABILITY so an older client (which decodes no
# video) gets a precise "update Mixar" error from the backend tool instead of
# an unknown-method failure.
VIDEO_CAPABILITY = "context_folder_video_v1"
# context_folder.read extracts PDF text and context_folder.view_pdf_pages
# renders PDF pages. Advertised only when this build imports pypdfium2.
PDF_CAPABILITY = "context_folder_pdf_v1"

# Folders one chat may carry at once.
MAX_FOLDERS = 5
# Single files attached as context (videos, documents, anything that is not
# an image pill or an imported model); they travel as ONE synthetic folder.
MAX_CONTEXT_FILES = 20
# Wire label of that synthetic folder — the name the agent types as a path
# prefix, so it is never translated.
ATTACHED_FILES_LABEL = "Attached files"
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
# Frames per view_video call: equals the backend's fresh-tool-image window, so
# every sampled frame is actually shown to the model.
MAX_VIDEO_FRAMES = 8
DEFAULT_VIDEO_FRAMES = 6
MAX_VIDEO_FRAME_DIM = 1024
DEFAULT_VIDEO_FRAME_DIM = 768
# Decoding streams from disk; this only stops absurd inputs.
MAX_VIDEO_SOURCE_BYTES = 4 * 1024**3

PDF_SUFFIX = ".pdf"
# PDFs are big because of their images; PDFium reads the file in place.
MAX_PDF_BYTES = 256 * 1024**2
# Pages whose text one read extracts (cached per file); later pages are only
# viewable. Keeps the first read of a huge PDF inside the RPC timeout.
MAX_PDF_TEXT_PAGES = 1000
# Extracted PDFs kept in memory, keyed by (path, size, mtime).
PDF_TEXT_CACHE_ENTRIES = 8
# A longer extracted line is wrapped, so every part stays readable by line.
MAX_PDF_LINE_CHARS = 1000
# A search extracts uncached PDFs only until this budget is spent; later
# uncached PDFs are skipped and the result is ``truncated``.
PDF_SEARCH_EXTRACT_S = 10.0
# view_pdf_pages: pages per call and the rendered longest edge.
MAX_PDF_VIEW_PAGES = 4
DEFAULT_PDF_PAGE_DIM = 1568
MAX_PDF_PAGE_DIM = 2048
# Wire text the model reads: the line before each page's extracted text, and
# the stand-ins for a page without text or past MAX_PDF_TEXT_PAGES.
PDF_PAGE_MARKER = "--- page {page} of {pages} ---"
PDF_NO_TEXT_PAGE = "[no text on this page; look at it with view_folder_pdf_pages]"
PDF_UNREAD_PAGE = "[this page could not be read as text]"
PDF_PAGES_NOT_EXTRACTED = ("--- pages {first}-{last} of {pages} are not read as text "
                           "(only the first {limit} are); look at them with view_folder_pdf_pages ---")
# Copied files (Finder / Explorer / a Linux file manager) that a chat paste
# attaches as context files. The OS also offers such a file's ICON as image
# data, which must never become the attachment.
PASTE_FILE_SUFFIXES = frozenset({PDF_SUFFIX})
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
