# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PDF text and page images for the agent, through ``pypdfium2``.

The PDF never leaves this machine: ``context_folder.read`` returns its
extracted text with a ``--- page N of P ---`` line before each page, and
``context_folder.view_pdf_pages`` renders up to four pages as JPEGs.
``pypdfium2`` (Apache-2.0 / BSD-3-Clause, bundled through
``scripts/python_requirements.txt``) is imported lazily; a build without it
does not advertise ``context_folder_pdf_v1`` and reads a PDF as before
(``not_text``).

Thread model: this runs on ``MixarContextFolderRPC`` worker threads and
PDFium is not thread-safe, so every call into it — open, text, render, close —
holds ``_PDFIUM_LOCK``. Every PDFium object is closed explicitly inside that
lock, so no ``pypdfium2`` finalizer ever runs PDFium later on another thread.
Pixels are copied out of a bitmap before it is closed.
"""

import base64
import io
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath

from ..constants import (
    DEFAULT_PDF_PAGE_DIM,
    MAX_PDF_BYTES,
    MAX_PDF_LINE_CHARS,
    MAX_PDF_PAGE_DIM,
    MAX_PDF_TEXT_PAGES,
    MAX_PDF_VIEW_PAGES,
    PDF_NO_TEXT_PAGE,
    PDF_PAGE_MARKER,
    PDF_PAGES_NOT_EXTRACTED,
    PDF_SUFFIX,
    PDF_TEXT_CACHE_ENTRIES,
    PDF_UNREAD_PAGE,
)
from .errors import ContextFolderError
from .paths import existing_file, normalize_relative_path

_PDFIUM_LOCK = threading.Lock()
_IMPORT_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()
_UNSET = object()
_pdfium = _UNSET  # the pypdfium2 module once imported, None when it cannot be
_cache: "OrderedDict[tuple, PdfText]" = OrderedDict()
# C0 controls PDFium can leave in extracted text (tab kept; line breaks split).
_CONTROL = dict.fromkeys(c for c in range(32) if c != 9)


@dataclass(frozen=True)
class PdfText:
    lines: tuple  # marker lines included; numbered from 1 like a text file
    page_count: int
    has_text: bool
    synthetic: frozenset  # 0-based indexes of the lines this module wrote


def is_pdf(name) -> bool:
    return PurePosixPath(str(name)).suffix.lower() == PDF_SUFFIX


def _load():
    """``pypdfium2``, imported once; ``None`` when this build lacks it. The
    import initialises PDFium, which nothing else can be using yet."""
    global _pdfium
    with _IMPORT_LOCK:
        if _pdfium is _UNSET:
            try:
                import pypdfium2
            except Exception as exc:  # noqa: BLE001 — ImportError or a library load failure
                print(f"[ContextFolder] PDF support unavailable: {type(exc).__name__}: {exc}")
                pypdfium2 = None
            _pdfium = pypdfium2
        return _pdfium


def available() -> bool:
    """True when this build can open PDFs (gates ``context_folder_pdf_v1``)."""
    return _load() is not None


def set_pdfium_for_tests(module) -> None:
    """Swap the PDFium binding (``None`` = a build without it)."""
    global _pdfium
    with _IMPORT_LOCK:
        _pdfium = module
    clear_cache()


def reset_for_tests() -> None:
    global _pdfium
    with _IMPORT_LOCK:
        _pdfium = _UNSET
    clear_cache()


def clear_cache() -> None:
    with _CACHE_LOCK:
        _cache.clear()


def _require():
    module = _load()
    if module is None:
        raise ContextFolderError("pdf_unavailable", "This Mixar build cannot open PDFs; update Mixar")
    return module


def _check_size(target) -> tuple:
    stat = target.stat()
    if stat.st_size > MAX_PDF_BYTES:
        raise ContextFolderError(
            "file_too_large", f"That PDF is too large to open (over {MAX_PDF_BYTES // 1024**2} MB)")
    return str(target), stat.st_size, stat.st_mtime_ns


@contextmanager
def _document(pdfium, target):
    """An open document; the caller holds ``_PDFIUM_LOCK``. PDFium reads the
    file through the handle, so memory does not grow with the file."""
    try:
        handle = open(target, "rb")
    except OSError as exc:
        raise ContextFolderError("pdf_unreadable", "That PDF could not be opened") from exc
    document = None
    try:
        try:
            document = pdfium.PdfDocument(handle)
        except pdfium.PdfiumError as exc:
            code = getattr(exc, "err_code", None)
            if code in (pdfium.raw.FPDF_ERR_PASSWORD, pdfium.raw.FPDF_ERR_SECURITY):
                raise ContextFolderError(
                    "pdf_encrypted", "That PDF is password-protected; ask the user for an unlocked copy",
                ) from exc
            raise ContextFolderError(
                "pdf_unreadable", "That PDF could not be opened (damaged, or not a PDF)") from exc
        yield document
    finally:
        if document is not None:
            document.close()
        handle.close()


def _page_text(document, index: int) -> str:
    page = document[index]
    try:
        textpage = page.get_textpage()
        try:
            return textpage.get_text_range()
        finally:
            textpage.close()
    finally:
        page.close()


def _wrap(line: str) -> list:
    if len(line) <= MAX_PDF_LINE_CHARS:
        return [line]
    return [line[i:i + MAX_PDF_LINE_CHARS] for i in range(0, len(line), MAX_PDF_LINE_CHARS)]


def _extract(pdfium, target) -> PdfText:
    lines, synthetic, has_text = [], set(), False

    def note(text):
        synthetic.add(len(lines))
        lines.append(text)

    with _document(pdfium, target) as document:
        page_count = len(document)
        for index in range(min(page_count, MAX_PDF_TEXT_PAGES)):
            note(PDF_PAGE_MARKER.format(page=index + 1, pages=page_count))
            try:
                raw = _page_text(document, index)
            except pdfium.PdfiumError:
                note(PDF_UNREAD_PAGE)
                continue
            page_lines = [line.translate(_CONTROL).rstrip() for line in raw.splitlines()]
            while page_lines and not page_lines[-1]:
                page_lines.pop()
            while page_lines and not page_lines[0]:
                page_lines.pop(0)
            if not page_lines:
                note(PDF_NO_TEXT_PAGE)
                continue
            has_text = True
            for line in page_lines:
                lines.extend(_wrap(line))
        if page_count > MAX_PDF_TEXT_PAGES:
            note(PDF_PAGES_NOT_EXTRACTED.format(first=MAX_PDF_TEXT_PAGES + 1, last=page_count,
                                                pages=page_count, limit=MAX_PDF_TEXT_PAGES))
    return PdfText(tuple(lines), page_count, has_text, frozenset(synthetic))


def _cached(key):
    with _CACHE_LOCK:
        text = _cache.get(key)
        if text is not None:
            _cache.move_to_end(key)
        return text


def _remember(key, text: PdfText) -> None:
    with _CACHE_LOCK:
        _cache[key] = text
        _cache.move_to_end(key)
        while len(_cache) > PDF_TEXT_CACHE_ENTRIES:
            _cache.popitem(last=False)


def pdf_text(target, *, deadline=None):
    """The extracted text of a PDF, cached by (path, size, mtime) so paged
    reads and searches extract once. With ``deadline`` (a ``time.monotonic``
    value) an uncached PDF past it is not extracted: returns ``None``."""
    key = _check_size(target)
    text = _cached(key)
    if text is not None:
        return text
    pdfium = _require()
    if deadline is not None and time.monotonic() > deadline:
        return None
    with _PDFIUM_LOCK:
        text = _cached(key)  # another worker may have extracted it while this one waited
        if text is None:
            text = _extract(pdfium, target)
            _remember(key, text)
    return text


def read_pdf_text(target) -> PdfText:
    """``pdf_text`` for ``context_folder.read``: a PDF without any text is
    an error the model can act on."""
    text = pdf_text(target)
    if not text.has_text:
        raise ContextFolderError(
            "pdf_no_text",
            "This PDF has no text layer (scanned or image-only); look at its pages with view_folder_pdf_pages",
        )
    return text


def _page_numbers(pages) -> list:
    if not isinstance(pages, (list, tuple)):
        pages = [pages]
    numbers = []
    for value in pages:
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int):
            numbers = []
            break
        if value not in numbers:
            numbers.append(value)
    if not 1 <= len(numbers) <= MAX_PDF_VIEW_PAGES:
        raise ContextFolderError("pdf_page_range", f"Give 1-{MAX_PDF_VIEW_PAGES} page numbers")
    return numbers


def _render(document, index: int, max_dim: int):
    """An RGB copy of one page, its longest edge ``max_dim`` px, on white."""
    page = document[index]
    try:
        width, height = page.get_size()
        longest = max(width, height)
        if not longest > 0:
            raise ContextFolderError("pdf_unreadable", f"Page {index + 1} of that PDF has no size")
        # pypdfium2 sizes the bitmap as ceil(edge * scale): just under max_dim
        # rounds up to exactly max_dim on the longest edge.
        bitmap = page.render(scale=(max_dim - 0.01) / longest, fill_color=(255, 255, 255, 255))
        try:
            return bitmap.to_pil().convert("RGB")  # a copy: the bitmap is freed below
        finally:
            bitmap.close()
    finally:
        page.close()


def view_pages(root, path, pages, max_dim=DEFAULT_PDF_PAGE_DIM) -> dict:
    """Up to ``MAX_PDF_VIEW_PAGES`` pages of a folder PDF as JPEGs."""
    relative = normalize_relative_path(path)
    target = existing_file(root, relative)
    if not is_pdf(relative):
        raise ContextFolderError("not_pdf", "That file is not a PDF")
    _check_size(target)
    numbers = _page_numbers(pages)
    try:
        max_dim = max(64, min(MAX_PDF_PAGE_DIM, int(max_dim)))
    except (TypeError, ValueError):
        max_dim = DEFAULT_PDF_PAGE_DIM
    pdfium = _require()
    with _PDFIUM_LOCK:
        with _document(pdfium, target) as document:
            page_count = len(document)
            if any(not 1 <= number <= page_count for number in numbers):
                raise ContextFolderError("pdf_page_range", f"pages must be within 1-{page_count}")
            try:
                images = [(number, _render(document, number - 1, max_dim)) for number in numbers]
            except pdfium.PdfiumError as exc:
                raise ContextFolderError("pdf_unreadable", "A page of that PDF could not be rendered") from exc
    rendered = []
    for number, image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        rendered.append({
            "page": number,
            "image_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "mime": "image/jpeg",
            "width": image.width,
            "height": image.height,
        })
    return {"success": True, "page_count": page_count, "pages": rendered}
