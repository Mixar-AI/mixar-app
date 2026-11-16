# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pasting a copied PDF FILE attaches the PDF as a context file.

A file copied in Finder (or Explorer, or a Linux file manager) is offered
on the clipboard as a file reference AND as image data — on macOS that image
is the file's icon. ``paste_image`` used to attach the icon. Now
``read_clipboard_paste`` reports the copied PDF's path first and the
operator attaches the original file through ``attach_file``, the Files
picker's route, while image paste stays exactly as it was (mixar-backend#2010).
"""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.space_mixie_chat.core import clipboard_image as CI  # noqa: E402
from mixar.modules.space_mixie_chat.ui.operators import clipboard_ops  # noqa: E402


@pytest.fixture
def copied(tmp_path, monkeypatch):
    """A real PDF and PNG on disk; image reads are recorded, never run."""
    brief = tmp_path / "Brief.PDF"
    brief.write_bytes(b"%PDF-1.4")
    still = tmp_path / "still.png"
    still.write_bytes(b"png")
    calls = []
    monkeypatch.setattr(CI, "get_mixar_screenshots_dir", lambda: str(tmp_path))
    monkeypatch.setattr(CI, "_paste_macos", lambda temp, path: calls.append(("mac", path)) or temp)
    monkeypatch.setattr(CI, "_paste_windows", lambda temp: calls.append(("win",)) or temp)
    monkeypatch.setattr(CI, "_paste_linux", lambda temp: calls.append(("linux",)) or None)
    return SimpleNamespace(pdf=str(brief), png=str(still), calls=calls)


def _on(monkeypatch, system, copied_path):
    monkeypatch.setattr(CI.platform, "system", lambda: system)
    reader = {"Darwin": "_macos_get_file_url", "Windows": "_win_copied_file", "Linux": "_linux_copied_file"}
    monkeypatch.setattr(CI, reader[system], lambda: copied_path)


@pytest.mark.parametrize("system", ["Darwin", "Windows", "Linux"])
def test_a_copied_pdf_is_a_file_paste_not_its_icon(monkeypatch, copied, system):
    _on(monkeypatch, system, copied.pdf)
    assert CI.read_clipboard_paste() == (CI.PASTE_FILE, copied.pdf)
    assert copied.calls == []  # no image data was read: the icon never becomes the attachment


def test_macos_image_paste_reuses_the_file_url_it_read(monkeypatch, copied):
    _on(monkeypatch, "Darwin", copied.png)
    kind, temp = CI.read_clipboard_paste()
    assert kind == CI.PASTE_IMAGE and temp.endswith(".png")
    assert copied.calls == [("mac", copied.png)]  # one osascript for the URL, not two


@pytest.mark.parametrize("system, call", [("Darwin", ("mac", None)), ("Windows", ("win",))])
def test_without_a_copied_file_image_paste_is_unchanged(monkeypatch, copied, system, call):
    _on(monkeypatch, system, None)
    kind, _ = CI.read_clipboard_paste()
    assert kind == CI.PASTE_IMAGE and copied.calls == [call]


def test_a_vanished_or_non_pdf_file_falls_back_to_image_paste(monkeypatch, copied, tmp_path):
    _on(monkeypatch, "Linux", str(tmp_path / "gone.pdf"))
    assert CI.read_clipboard_paste() is None and copied.calls == [("linux",)]
    _on(monkeypatch, "Windows", copied.png)
    assert CI.read_clipboard_paste()[0] == CI.PASTE_IMAGE


def test_the_pasteable_suffixes_are_pdf_only():
    from mixar.modules.context_folder.constants import PASTE_FILE_SUFFIXES

    assert PASTE_FILE_SUFFIXES == frozenset({".pdf"})


# ── Linux: text/uri-list from the file manager ───────────────────────────

def _fake_run(calls, answers):
    def run(cmd, **kwargs):
        calls.append(cmd[0])
        answer = answers[cmd[0]]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(returncode=0 if answer else 1, stdout=answer or b"")
    return run


def test_linux_reads_the_uri_list_and_decodes_the_path(monkeypatch):
    calls = []
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(CI.subprocess, "run", _fake_run(
        calls, {"xclip": b"# comment\r\nfile:///home/me/My%20Brief.pdf\r\nfile:///home/me/b.pdf\r\n"}))
    assert CI._linux_copied_file() == "/home/me/My Brief.pdf"
    assert calls == ["xclip"]


def test_wayland_tries_wl_paste_then_xclip(monkeypatch):
    calls = []
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(CI.subprocess, "run", _fake_run(
        calls, {"wl-paste": FileNotFoundError(), "xclip": b"file://localhost/tmp/a.pdf\n"}))
    assert CI._linux_copied_file() == "/tmp/a.pdf"
    assert calls == ["wl-paste", "xclip"]


@pytest.mark.parametrize("answer", [None, b"https://example.com/a.pdf\n", b"file://server/share/a.pdf\n",
                                    subprocess.TimeoutExpired("xclip", 3)])
def test_linux_ignores_anything_but_a_local_file(monkeypatch, answer):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(CI.subprocess, "run", _fake_run([], {"xclip": answer}))
    assert CI._linux_copied_file() is None


def test_windows_file_read_never_raises_off_windows():
    assert CI._win_copied_file() is None or os.name == "nt"


# ── the operator ─────────────────────────────────────────────────────────

class _Op(clipboard_ops.MIXIE_CHAT_OT_paste_image):
    def __init__(self):
        self.reports = []

    def report(self, kind, message):
        self.reports.append((next(iter(kind)), message))


@pytest.fixture
def operator(monkeypatch):
    attached = []
    monkeypatch.setattr(clipboard_ops, "redraw_chat_areas", lambda: None)
    monkeypatch.setattr(clipboard_ops, "sync_bubble_attachment_size_deferred", lambda **kw: None)
    monkeypatch.setattr(clipboard_ops, "attach_file",
                        lambda scene, path: attached.append(path) or {
                            "success": True, "already": False, "file_id": "f", "name": "Brief.PDF",
                            "kind": "document"})
    context = SimpleNamespace(scene=SimpleNamespace(mixie_chat_pending_attachments=[]),
                              screen=SimpleNamespace(areas=[]), area=None,
                              window_manager=SimpleNamespace(mixar_bubble_tab="AGENT"))
    return SimpleNamespace(op=_Op(), context=context, attached=attached)


def test_paste_image_attaches_a_copied_pdf_as_a_context_file(monkeypatch, operator):
    monkeypatch.setattr(clipboard_ops, "read_clipboard_paste", lambda: (CI.PASTE_FILE, "/docs/Brief.PDF"))
    assert operator.op.execute(operator.context) == {'FINISHED'}
    assert operator.attached == ["/docs/Brief.PDF"]
    assert operator.context.scene.mixie_chat_pending_attachments == []  # never an image pill
    assert operator.op.reports == [('INFO', "Attached 1 file(s) as context")]


@pytest.mark.parametrize("tab", ["IMAGE", "THREE_D"])
def test_a_pdf_pasted_on_a_pane_tab_still_joins_the_agent_chat(monkeypatch, operator, tab):
    operator.context.area = SimpleNamespace(type='AGENT_BUBBLE')
    operator.context.window_manager.mixar_bubble_tab = tab
    monkeypatch.setattr(clipboard_ops, "read_clipboard_paste", lambda: (CI.PASTE_FILE, "/docs/a.pdf"))
    assert operator.op.execute(operator.context) == {'FINISHED'} and operator.attached == ["/docs/a.pdf"]


def test_a_refused_pdf_reports_and_still_swallows_the_paste(monkeypatch, operator):
    monkeypatch.setattr(clipboard_ops, "read_clipboard_paste", lambda: (CI.PASTE_FILE, "/docs/a.pdf"))
    monkeypatch.setattr(clipboard_ops, "attach_file", lambda scene, path: {
        "success": False, "error": "At most {count} files can be attached to a chat",
        "error_args": {"count": 20}})
    # FINISHED: the C++ text-edit hook would otherwise paste the file NAME as text.
    assert operator.op.execute(operator.context) == {'FINISHED'}
    assert operator.op.reports == [('WARNING', "Cannot add a.pdf: At most 20 files can be attached to a chat")]


def test_an_empty_clipboard_still_cancels_for_the_text_fallback(monkeypatch, operator):
    monkeypatch.setattr(clipboard_ops, "read_clipboard_paste", lambda: None)
    assert operator.op.execute(operator.context) == {'CANCELLED'} and operator.attached == []
