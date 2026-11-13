# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PDFs as agent context (``modules/context_folder/core/pdf.py``, mixar-backend#2010).

``context_folder.read`` returns a PDF's extracted text with a
``--- page N of P ---`` line before each page plus ``page_count``;
``context_folder.search`` matches that text in the same numbering;
``context_folder.view_pdf_pages`` renders 1-4 pages as JPEGs whose longest
edge is ``max_dim``. Real PDFium (``pypdfium2``) over raw-byte fixtures from
``pdf_fixtures.py``; a build without it advertises nothing and reads a PDF as
``not_text`` like before.
"""

import base64
import io
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

pytest.importorskip("pypdfium2")

from mixar.modules.context_folder import constants  # noqa: E402
from mixar.modules.context_folder.core import attach, grants, indexer, pdf, reader, rpc  # noqa: E402
from mixar.modules.context_folder.core.errors import ContextFolderError  # noqa: E402
from mixar.modules.context_folder.core.registry import FolderRegistry, set_registry_for_tests  # noqa: E402
from pdf_fixtures import IMAGE_ONLY, RED_RECT, build_pdf, mixed_pdf, text_page  # noqa: E402
from test_context_folder_video import _scene  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"


@pytest.fixture(autouse=True)
def _isolated(tmp_path):
    set_registry_for_tests(FolderRegistry(tmp_path / "registry" / "context_folders.json"))
    grants.clear()
    indexer.clear_cache()
    pdf.reset_for_tests()
    yield
    pdf.reset_for_tests()
    set_registry_for_tests(None)
    grants.clear()
    indexer.clear_cache()


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "Brief"
    root.mkdir()
    (root / "brief.pdf").write_bytes(mixed_pdf())
    (root / "scan.PDF").write_bytes(build_pdf([RED_RECT, IMAGE_ONLY]))
    (root / "locked.pdf").write_bytes(build_pdf([text_page("Secret plan")], user_password="hunter2"))
    (root / "broken.pdf").write_bytes(b"%PDF-1.4\n% not really a PDF\n%%EOF")
    (root / "notes.txt").write_text("the shield is round\nno pages here\n")
    return root


def _jpeg(entry):
    return Image.open(io.BytesIO(base64.b64decode(entry["image_base64"])))


def _code(fn, *args, **kwargs):
    with pytest.raises(ContextFolderError) as info:
        fn(*args, **kwargs)
    return info.value


# ── read ─────────────────────────────────────────────────────────────────

def test_read_returns_page_marked_text_and_the_page_count(folder):
    result = reader.read_text(folder, "brief.pdf")
    assert result["success"] and result["page_count"] == 3 and not result["truncated"]
    assert result["text"].splitlines() == [
        "    1  --- page 1 of 3 ---",
        "    2  Hello PDF world",
        "    3  Shield is round",
        "    4  --- page 2 of 3 ---",
        f"    5  {constants.PDF_NO_TEXT_PAGE}",
        "    6  --- page 3 of 3 ---",
        f"    7  {constants.PDF_NO_TEXT_PAGE}",
    ]
    assert (result["start_line"], result["end_line"], result["total_lines"]) == (1, 7, 7)
    assert set(result) == {"success", "path", "text", "start_line", "end_line", "total_lines",
                           "truncated", "page_count"}


def test_reads_page_by_line_like_a_text_file(folder, monkeypatch):
    middle = reader.read_text(folder, "brief.pdf", start_line=3, end_line=4)
    assert middle["text"] == "    3  Shield is round\n    4  --- page 2 of 3 ---"
    assert not middle["truncated"] and middle["page_count"] == 3  # the asked range came back whole
    monkeypatch.setattr(reader, "MAX_READ_CHARS", 60)  # the per-read character budget
    budgeted = reader.read_text(folder, "brief.pdf")
    assert budgeted["end_line"] < budgeted["total_lines"] and budgeted["truncated"]


def test_extraction_is_cached_by_path_size_and_mtime(folder, monkeypatch):
    calls = []
    real = pdf._extract
    monkeypatch.setattr(pdf, "_extract", lambda module, target: calls.append(target.name) or real(module, target))
    for start in (1, 3, 5):
        reader.read_text(folder, "brief.pdf", start_line=start)
    reader.search(folder, "shield")
    assert calls.count("brief.pdf") == 1
    (folder / "brief.pdf").write_bytes(build_pdf([text_page("Edited brief")]))
    edited = reader.read_text(folder, "brief.pdf")
    assert "Edited brief" in edited["text"] and edited["page_count"] == 1
    assert calls.count("brief.pdf") == 2


def test_the_cache_is_bounded(folder, monkeypatch):
    monkeypatch.setattr(pdf, "PDF_TEXT_CACHE_ENTRIES", 1)
    calls = []
    real = pdf._extract
    monkeypatch.setattr(pdf, "_extract", lambda module, target: calls.append(target.name) or real(module, target))
    (folder / "other.pdf").write_bytes(build_pdf([text_page("Other")]))
    for name in ("brief.pdf", "other.pdf", "brief.pdf"):
        reader.read_text(folder, name)
    assert calls == ["brief.pdf", "other.pdf", "brief.pdf"] and len(pdf._cache) == 1


def test_extraction_holds_the_pdfium_lock(folder, monkeypatch):
    seen = []
    real = pdf._extract

    def checked(module, target):
        seen.append(pdf._PDFIUM_LOCK.locked())
        return real(module, target)

    monkeypatch.setattr(pdf, "_extract", checked)
    reader.read_text(folder, "brief.pdf")
    assert seen == [True]


def test_a_pdf_without_text_is_pdf_no_text(folder):
    error = _code(reader.read_text, folder, "scan.PDF")  # the suffix is case-insensitive
    assert error.code == "pdf_no_text"
    assert error.message == ("This PDF has no text layer (scanned or image-only); "
                             "look at its pages with view_folder_pdf_pages")


def test_encrypted_and_corrupt_pdfs_are_refused_without_the_path(folder):
    locked = _code(reader.read_text, folder, "locked.pdf")
    assert (locked.code, locked.message) == (
        "pdf_encrypted", "That PDF is password-protected; ask the user for an unlocked copy")
    assert _code(reader.read_text, folder, "broken.pdf").code == "pdf_unreadable"
    assert _code(pdf.view_pages, folder, "locked.pdf", [1]).code == "pdf_encrypted"
    assert _code(pdf.view_pages, folder, "broken.pdf", [1]).code == "pdf_unreadable"


def test_the_encrypted_fixture_is_a_real_encrypted_pdf(folder):
    import pypdfium2

    document = pypdfium2.PdfDocument(str(folder / "locked.pdf"), password="hunter2")
    try:
        assert "Secret plan" in document[0].get_textpage().get_text_range()
    finally:
        document.close()


def test_a_pdf_over_the_size_cap_is_file_too_large(folder, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_PDF_BYTES", 100)
    assert _code(reader.read_text, folder, "brief.pdf").code == "file_too_large"
    assert _code(pdf.view_pages, folder, "brief.pdf", [1]).code == "file_too_large"


def test_pages_past_the_text_cap_are_named_not_extracted(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_PDF_TEXT_PAGES", 2)
    (tmp_path / "long.pdf").write_bytes(build_pdf([text_page(f"Page {n}") for n in range(1, 6)]))
    lines = reader.read_text(tmp_path, "long.pdf")["text"].splitlines()
    assert lines[-1].endswith("--- pages 3-5 of 5 are not read as text (only the first 2 are); "
                              "look at them with view_folder_pdf_pages ---")
    assert "Page 3" not in "\n".join(lines) and "--- page 2 of 5 ---" in lines[2]


def test_a_very_long_line_is_wrapped_so_every_part_is_readable(tmp_path):
    (tmp_path / "wide.pdf").write_bytes(build_pdf([text_page("x" * 2500)]))
    lines = pdf.read_pdf_text(tmp_path / "wide.pdf").lines
    assert [len(line) for line in lines[1:]] == [1000, 1000, 500]


# ── search ───────────────────────────────────────────────────────────────

def test_search_matches_pdf_text_in_read_numbering(folder):
    found = reader.search(folder, "shield")
    by_path = {match["path"]: match for match in found["matches"]}
    assert by_path["brief.pdf"] == {"path": "brief.pdf", "line": 3, "text": "Shield is round"}
    assert by_path["notes.txt"]["line"] == 1  # text files are searched as before
    read = reader.read_text(folder, "brief.pdf", start_line=3, end_line=3)
    assert read["text"].endswith("Shield is round")
    assert not found["truncated"]  # locked/broken/textless PDFs are skipped, not failures


def test_page_markers_and_notes_never_match(folder):
    assert reader.search(folder, "page")["matches"] == [
        {"path": "notes.txt", "line": 2, "text": "no pages here"}]
    assert reader.search(folder, "view_folder_pdf_pages")["matches"] == []


def test_search_stops_extracting_when_its_budget_is_spent(folder, monkeypatch):
    reader.read_text(folder, "brief.pdf")  # cached: still searched
    (folder / "late.pdf").write_bytes(build_pdf([text_page("Shield on page one")]))
    monkeypatch.setattr(reader, "PDF_SEARCH_EXTRACT_S", -1.0)
    found = reader.search(folder, "shield")
    assert {m["path"] for m in found["matches"]} == {"brief.pdf", "notes.txt"}
    assert found["truncated"]


# ── view_pdf_pages ───────────────────────────────────────────────────────

def test_view_renders_the_asked_pages_at_max_dim(folder):
    result = pdf.view_pages(folder, "brief.pdf", [3, 1, 2])
    assert result["success"] and result["page_count"] == 3
    assert [entry["page"] for entry in result["pages"]] == [3, 1, 2]
    for entry in result["pages"]:
        image = _jpeg(entry)
        assert entry["mime"] == "image/jpeg" and image.format == "JPEG"
        assert image.size == (entry["width"], entry["height"])
        assert max(image.size) == constants.DEFAULT_PDF_PAGE_DIM == 1568
    portrait, landscape = result["pages"][1], result["pages"][2]
    assert (portrait["width"], portrait["height"]) == (1212, 1568)  # 612 x 792 pt
    assert (landscape["width"], landscape["height"]) == (1568, 1212)  # /Rotate 90


def test_view_draws_the_page_on_white(folder):
    pages = pdf.view_pages(folder, "brief.pdf", [2, 3], max_dim=400)["pages"]
    red = _jpeg(pages[0]).convert("RGB")
    data = red.tobytes()
    pixels = [data[i:i + 3] for i in range(0, len(data), 3)]
    share = sum(1 for r, g, b in pixels if r > 200 and g < 70 and b < 70) / len(pixels)
    assert 0.09 < share < 0.16, share  # 300 x 200 pt of a 612 x 792 pt page
    assert red.getpixel((2, 2))[0] > 240 and min(red.getpixel((2, 2))) > 240  # white paper
    image_page = _jpeg(pages[1]).convert("RGB")
    assert min(image_page.getpixel((2, 2))) > 240
    assert max(image_page.size) == 400


@pytest.mark.parametrize("asked, expected", [(5000, constants.MAX_PDF_PAGE_DIM), (1, 64), ("x", 1568)])
def test_max_dim_is_clamped(folder, asked, expected):
    entry = pdf.view_pages(folder, "brief.pdf", [1], max_dim=asked)["pages"][0]
    assert max(entry["width"], entry["height"]) == expected


def test_out_of_range_pages_name_the_valid_range(folder):
    for pages in ([4], [0, 1], [-1]):
        error = _code(pdf.view_pages, folder, "brief.pdf", pages)
        assert (error.code, error.message) == ("pdf_page_range", "pages must be within 1-3")


@pytest.mark.parametrize("pages", [[], [1, 2, 3, 4, 1, 2, 3, 4, 5], [True], ["1"], [1.5], None])
def test_malformed_page_lists_are_refused(folder, pages):
    assert _code(pdf.view_pages, folder, "brief.pdf", pages).code == "pdf_page_range"


def test_duplicate_pages_render_once(folder):
    result = pdf.view_pages(folder, "brief.pdf", [1, 1, 2.0])
    assert [entry["page"] for entry in result["pages"]] == [1, 2]


def test_only_pdfs_are_viewed(folder):
    assert _code(pdf.view_pages, folder, "notes.txt", [1]).code == "not_pdf"
    assert _code(pdf.view_pages, folder, "missing.pdf", [1]).code == "not_found"


def test_render_holds_the_lock_and_returns_a_copy(folder, monkeypatch):
    seen = []
    real = pdf._render

    def checked(document, index, max_dim):
        seen.append(pdf._PDFIUM_LOCK.locked())
        return real(document, index, max_dim)

    monkeypatch.setattr(pdf, "_render", checked)
    pdf.view_pages(folder, "brief.pdf", [1, 2])
    assert seen == [True, True] and not pdf._PDFIUM_LOCK.locked()


def test_concurrent_reads_and_renders_agree(folder):
    results, errors = [], []

    def work(index):
        try:
            if index % 2:
                results.append(reader.read_text(folder, "brief.pdf")["total_lines"])
            else:
                results.append(pdf.view_pages(folder, "brief.pdf", [1], max_dim=200)["pages"][0]["height"])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not errors and sorted(set(results)) == [7, 200]


# ── RPC wiring, grant and capability ─────────────────────────────────────

def test_rpcs_go_through_the_grant(folder):
    scene = _scene()
    attached = attach.attach_folder(scene, str(folder))
    attach.folder_context_for_send(scene, "session-1")
    base = {"session_id": "session-1", "folder_id": attached["folder_id"]}
    viewed = rpc.dispatch(constants.RPC_VIEW_PDF_PAGES, {**base, "path": "brief.pdf", "pages": [1, 2],
                                                         "max_dim": 1568})
    assert viewed["success"] and [p["page"] for p in viewed["pages"]] == [1, 2]
    read = rpc.dispatch(constants.RPC_READ, {**base, "path": "brief.pdf"})
    assert read["success"] and read["page_count"] == 3
    searched = rpc.dispatch(constants.RPC_SEARCH, {**base, "query": "hello"})
    assert searched["matches"] == [{"path": "brief.pdf", "line": 2, "text": "Hello PDF world"}]
    ranged = rpc.dispatch(constants.RPC_VIEW_PDF_PAGES, {**base, "path": "brief.pdf", "pages": [9]})
    assert ranged["error"] == {"code": "pdf_page_range", "message": "pages must be within 1-3"}
    foreign = rpc.dispatch(constants.RPC_VIEW_PDF_PAGES, {**base, "session_id": "session-2",
                                                          "path": "brief.pdf", "pages": [1]})
    assert foreign["error"]["code"] == "folder_not_attached"
    for name in ("locked.pdf", "broken.pdf", "scan.PDF"):
        refused = rpc.dispatch(constants.RPC_READ, {**base, "path": name})
        assert refused["error"]["code"] in ("pdf_encrypted", "pdf_unreadable", "pdf_no_text")
        assert str(folder) not in json.dumps(refused)


def test_the_method_and_capability_are_wired():
    assert constants.RPC_VIEW_PDF_PAGES == "context_folder.view_pdf_pages"
    assert constants.RPC_VIEW_PDF_PAGES in constants.RPC_METHODS
    assert constants.PDF_CAPABILITY == "context_folder_pdf_v1"
    assert constants.MAX_PDF_VIEW_PAGES == 4
    handshake = (CHAT / "core/socket_connection.py").read_text()
    assert "PDF_CAPABILITY as CONTEXT_FOLDER_PDF_CAPABILITY" in handshake
    assert "[CONTEXT_FOLDER_PDF_CAPABILITY] if context_folder_pdf.available()" in handshake


def _handshake_capabilities(monkeypatch):
    from mixar.modules.space_mixie_chat.core import machine_info, socket_connection
    from mixar.modules.space_mixie_chat.core.socket_diagnostics import SocketDiagnostics

    monkeypatch.setattr(machine_info, "machine_block", lambda: {})
    monkeypatch.setattr(socket_connection, "wait_for_handshake",
                        lambda *a, **kw: (socket_connection.HANDSHAKE_OK, None))
    client = SimpleNamespace(_next_request_id=lambda: "pdf", _blender_version=None,
                             _addon_version=None, _role="", _device_id="", _parent_instance_id="parent",
                             _ws=MagicMock(), _set_server_capabilities=lambda result: None,
                             _diag=SocketDiagnostics(), _note_server_close=lambda *a, **kw: None)
    assert socket_connection.SocketConnection._perform_handshake(client) == socket_connection.HANDSHAKE_OK
    return json.loads(client._ws.send.call_args.args[0])["params"]["capabilities"]


def test_the_handshake_advertises_pdf_only_when_pypdfium2_imports(monkeypatch):
    assert pdf.available()
    assert constants.PDF_CAPABILITY in _handshake_capabilities(monkeypatch)
    pdf.reset_for_tests()
    monkeypatch.setitem(sys.modules, "pypdfium2", None)  # import fails like a build without it
    assert not pdf.available()
    capabilities = _handshake_capabilities(monkeypatch)
    assert constants.PDF_CAPABILITY not in capabilities
    assert constants.CAPABILITY in capabilities and constants.VIDEO_CAPABILITY in capabilities


def test_a_build_without_pdfium_reads_pdfs_as_before(folder):
    pdf.set_pdfium_for_tests(None)
    error = _code(reader.read_text, folder, "brief.pdf")
    assert error.code == "not_text" and "ask the user about documents" in error.message
    assert _code(pdf.view_pages, folder, "brief.pdf", [1]).code == "pdf_unavailable"
    assert {m["path"] for m in reader.search(folder, "shield")["matches"]} == {"notes.txt"}


def test_other_documents_stay_unreadable(folder):
    (folder / "deck.pptx").write_bytes(b"PK\x03\x04")
    error = _code(reader.read_text, folder, "deck.pptx")
    assert error.code == "not_text" and "text files and PDFs" in error.message
