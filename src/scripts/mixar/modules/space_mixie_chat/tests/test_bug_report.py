# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Help > Report a Bug: upload the diagnostics, then open the web form."""

import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from mixar.modules.space_mixie_chat.core import bug_report

ROOT = Path(__file__).resolve().parents[6]


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_form_url_carries_only_non_personal_fields():
    url = bug_report.bug_report_url(
        "https://www.mixar.app/", report_id="abc_DEF-123456789012345",
        version="4.2.0", os_name="macOS 26.5 arm64", bundle_bytes=300 * 1024)
    assert url.startswith("https://www.mixar.app/bug-report?")
    assert _query(url) == {"source": "desktop", "report": "abc_DEF-123456789012345",
                           "bundle_kb": "300", "app_version": "4.2.0",
                           "os": "macOS 26.5 arm64"}


def test_form_url_without_a_report_has_no_report_or_size():
    query = _query(bug_report.bug_report_url("https://x.test", version="4.2.0",
                                             bundle_bytes=999))
    assert "report" not in query and "bundle_kb" not in query
    assert query["source"] == "desktop"


def test_report_id_is_read_from_the_backend_envelope():
    ok = SimpleNamespace(data={"status": "success", "data": {"report_id": "r1"}})
    assert bug_report.report_id_from(ok) == "r1"
    assert bug_report.report_id_from(SimpleNamespace(data={"data": {}})) == ""
    assert bug_report.report_id_from(SimpleNamespace(data=None)) == ""


@pytest.fixture
def flow(monkeypatch, tmp_path):
    opened, notices, uploads = [], [], []
    monkeypatch.setattr(bug_report, "_open_form",
                        lambda report_id="", bundle_bytes=0: opened.append((report_id, bundle_bytes)))
    monkeypatch.setattr(bug_report, "_notify", lambda title, body="": notices.append(title))

    from mixar.modules.space_mixie_chat.core import support_bundle
    monkeypatch.setattr(support_bundle, "build_support_bundle",
                        lambda path: open(path, "wb").write(b"PK\x03\x04data"))

    class Service:
        def upload_bug_report_bundle_async(self, **kwargs):
            uploads.append(kwargs)

    from mixar.modules.common.api import services
    monkeypatch.setattr(services, "get_contact_service", lambda: Service())
    return SimpleNamespace(opened=opened, notices=notices, uploads=uploads)


def test_signed_out_opens_the_form_without_diagnostics(flow, monkeypatch):
    monkeypatch.setattr(bug_report, "_signed_in", lambda: False)
    assert bug_report.start_bug_report() is False
    assert flow.opened == [("", 0)] and flow.uploads == []
    assert flow.notices == ["Sign in to attach diagnostics"]


def test_upload_success_opens_the_form_with_the_report(flow, monkeypatch):
    monkeypatch.setattr(bug_report, "_signed_in", lambda: True)
    assert bug_report.start_bug_report() is True
    call = flow.uploads[0]
    assert call["body_factory"]() == b"PK\x03\x04data"
    assert call["content_length"] == 8
    assert flow.opened == []  # nothing opens until the upload answers
    call["on_success"](SimpleNamespace(data={"data": {"report_id": "rid"}}))
    assert flow.opened == [("rid", 8)] and flow.notices == []


def test_upload_failure_still_opens_the_form(flow, monkeypatch):
    from mixar.modules.common.api.exceptions import NotFoundError
    monkeypatch.setattr(bug_report, "_signed_in", lambda: True)
    bug_report.start_bug_report()
    flow.uploads[0]["on_error"](NotFoundError("no route", status_code=404))
    assert flow.opened == [("", 0)]
    assert flow.notices == ["Diagnostics were not attached"]


def test_the_temp_bundle_is_removed_before_the_upload(flow, monkeypatch, tmp_path):
    made = []
    import tempfile
    real = tempfile.mkstemp
    monkeypatch.setattr(bug_report.tempfile, "mkstemp",
                        lambda **kw: made.append(real(dir=tmp_path, **kw)) or made[-1])
    monkeypatch.setattr(bug_report, "_signed_in", lambda: True)
    bug_report.start_bug_report()
    assert made and not os.path.exists(made[0][1])


def test_every_report_a_bug_entry_point_uses_the_guarded_operator():
    """The operator when registered, the plain link otherwise: the entry must
    work while operators register and when the chat module failed to load."""
    topbar = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/topbar.py").read_text(
        encoding="utf-8")
    assert "draw_report_bug_entry(" in topbar and "mixar.app/bug-report" not in topbar
    # Drawn outside the chat module: an inline guard, no import from it.
    for site in ("src/scripts/startup/bl_ui/space_topbar.py",
                 "src/scripts/mixar/modules/common/job_queue/ui/lists/queue_uilist.py"):
        text = (ROOT / site).read_text(encoding="utf-8")
        assert 'hasattr(bpy.types, "MIXIE_CHAT_OT_report_bug")' in text, site
        assert '"mixie_chat.report_bug"' in text and "mixar.app/bug-report" in text, site
        assert "import space_mixie_chat" not in text and "space_mixie_chat." not in text, site


def test_the_entry_falls_back_to_the_link_when_the_operator_is_missing(monkeypatch):
    import bpy

    calls = []

    class Layout:
        def operator(self, op, **kwargs):
            calls.append(op)
            return SimpleNamespace()

    monkeypatch.setattr(bpy, "types", SimpleNamespace(), raising=False)
    bug_report.draw_report_bug_entry(Layout(), text="Report a Bug")
    monkeypatch.setattr(bpy, "types", SimpleNamespace(MIXIE_CHAT_OT_report_bug=object()),
                        raising=False)
    bug_report.draw_report_bug_entry(Layout(), text="Report a Bug")
    assert calls == ["wm.url_open", "mixie_chat.report_bug"]


def test_an_oversized_bundle_is_not_uploaded(flow, monkeypatch):
    monkeypatch.setattr(bug_report, "_signed_in", lambda: True)
    monkeypatch.setattr(bug_report, "MAX_UPLOAD_BYTES", 4)
    assert bug_report.start_bug_report() is False
    assert flow.uploads == [] and flow.opened == [("", 0)]
