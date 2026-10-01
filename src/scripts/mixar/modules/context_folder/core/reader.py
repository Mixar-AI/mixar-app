# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only folder operations behind the RPC: list, read, search, preview.

Pure file I/O — no ``bpy`` — so they run on an RPC worker thread. Every
path is folder-relative on the way in and on the way out.
"""

import base64
import io

from ..constants import (
    KIND_IMAGE,
    KIND_TEXT,
    KINDS,
    MAX_IMAGE_DIM,
    MAX_IMAGE_SOURCE_BYTES,
    MAX_LIST_PAGE,
    MAX_QUERY_CHARS,
    MAX_READ_CHARS,
    MAX_SEARCH_FILE_BYTES,
    MAX_SEARCH_LINE_CHARS,
    MAX_SEARCH_RESULTS,
    MAX_TEXT_FILE_BYTES,
    PREVIEWABLE_IMAGE_SUFFIXES,
)
from .errors import ContextFolderError
from .indexer import index_folder
from .paths import existing_file, file_kind, normalize_relative_path


def _int(value, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def list_files(root, subfolder="", kind=None, offset=0, limit=MAX_LIST_PAGE) -> dict:
    prefix = normalize_relative_path(subfolder, allow_empty=True)
    if kind not in (None, "", *KINDS):
        raise ContextFolderError("invalid_kind", f"kind must be one of: {', '.join(KINDS)}")
    index = index_folder(root)
    matches = [entry for entry in index.files
               if (not prefix or entry["path"].startswith(prefix + "/"))
               and (not kind or entry["kind"] == kind)]
    offset = _int(offset, 0, 0, len(matches))
    limit = _int(limit, MAX_LIST_PAGE, 1, MAX_LIST_PAGE)
    page = matches[offset:offset + limit]
    return {
        "success": True,
        "files": [{"path": e["path"], "kind": e["kind"], "size": e["size"]} for e in page],
        "total": len(matches),
        "next_offset": offset + len(page) if offset + len(page) < len(matches) else None,
        "index_truncated": index.truncated,
    }


def _decode(data: bytes) -> str:
    if b"\x00" in data[:8192]:
        raise ContextFolderError("binary_file", "That file is binary; it cannot be read as text")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def read_text(root, path, start_line=None, end_line=None) -> dict:
    relative = normalize_relative_path(path)
    target = existing_file(root, relative)
    if file_kind(relative) != KIND_TEXT:
        raise ContextFolderError(
            "not_text",
            "Only text files can be read; view images, import models, and ask the user about documents",
        )
    if target.stat().st_size > MAX_TEXT_FILE_BYTES:
        raise ContextFolderError("file_too_large", "That file is too large to read")
    lines = _decode(target.read_bytes()).splitlines()
    total = len(lines)
    if not total:
        return {"success": True, "path": relative, "text": "", "start_line": 0,
                "end_line": 0, "total_lines": 0, "truncated": False}
    first = _int(start_line, 1, 1, total)
    last = _int(end_line, total, first, max(total, first))
    out, size, end, clipped = [], 0, first - 1, False
    for number in range(first, last + 1):
        line = f"{number:>5}  {lines[number - 1]}"
        if size + len(line) + 1 > MAX_READ_CHARS and out:
            break
        out.append(line[:MAX_READ_CHARS])
        clipped = len(line) > MAX_READ_CHARS
        size += len(line) + 1
        end = number
    return {
        "success": True,
        "path": relative,
        "text": "\n".join(out),
        "start_line": first,
        "end_line": end,
        "total_lines": total,
        "truncated": clipped or end < last,
    }


def search(root, query, max_results=MAX_SEARCH_RESULTS) -> dict:
    """Case-insensitive substring search over file NAMES and text CONTENT."""
    needle = str(query or "").strip()
    if not needle or len(needle) > MAX_QUERY_CHARS:
        raise ContextFolderError("invalid_query", f"Give a search text of 1-{MAX_QUERY_CHARS} characters")
    needle = needle.lower()
    limit = _int(max_results, MAX_SEARCH_RESULTS, 1, MAX_SEARCH_RESULTS)
    index = index_folder(root)
    names = [{"path": e["path"], "kind": e["kind"]} for e in index.files if needle in e["path"].lower()]
    matches, truncated = [], index.truncated or len(names) > limit
    for entry in index.files:
        if entry["kind"] != KIND_TEXT or entry["size"] > MAX_SEARCH_FILE_BYTES:
            continue
        try:
            text = _decode(existing_file(root, entry["path"]).read_bytes())
        except (OSError, ContextFolderError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                if len(matches) >= limit:
                    truncated = True
                    break
                matches.append({"path": entry["path"], "line": number,
                                "text": line.strip()[:MAX_SEARCH_LINE_CHARS]})
        if truncated and len(matches) >= limit:
            break
    return {"success": True, "name_matches": names[:limit], "matches": matches, "truncated": truncated}


def preview_image(root, path, max_dim=MAX_IMAGE_DIM) -> dict:
    """A downscaled JPEG of a folder image, for the agent to look at."""
    relative = normalize_relative_path(path)
    target = existing_file(root, relative)
    if file_kind(relative) != KIND_IMAGE:
        raise ContextFolderError("not_image", "That file is not an image")
    if target.suffix.lower() not in PREVIEWABLE_IMAGE_SUFFIXES:
        raise ContextFolderError(
            "preview_unsupported",
            "HDR images cannot be previewed; import it as a Blender image instead",
        )
    if target.stat().st_size > MAX_IMAGE_SOURCE_BYTES:
        raise ContextFolderError("file_too_large", "That image is too large to preview")
    max_dim = _int(max_dim, MAX_IMAGE_DIM, 64, MAX_IMAGE_DIM)
    from PIL import Image

    try:
        with Image.open(target) as image:
            width, height = image.size
            image.thumbnail((max_dim, max_dim))
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                flat = Image.new("RGB", image.size, (255, 255, 255))
                flat.paste(image, mask=image.split()[-1])
                image = flat
            elif image.mode != "RGB":
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ContextFolderError("unreadable_image", "That image could not be decoded") from exc
    return {
        "success": True,
        "path": relative,
        "mime": "image/jpeg",
        "image_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "width": width,
        "height": height,
    }
