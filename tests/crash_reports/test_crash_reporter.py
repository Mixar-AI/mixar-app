# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The reporter: harvest, consent/sign-in gate, never resend, never delete."""

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from mixar.modules.common.crash_reports.core import harvest
from mixar.modules.common.crash_reports.core.reporter import LATER, REFUSED, SENT, Reporter
from mixar.modules.common.crash_reports.core.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
STATIC = {"platform": "darwin", "os_version": "macOS 26.2", "cpu_arch": "arm64", "cpu_count": 12, "ram_gb": 32}
CURRENT = {"app_version": "4.3.7", "blender_version": "5.2.0", "gpu_vendor": "Apple", "open_tabs": 1}
DEVICE = "0123456789abcdef0123456789abcdef"
LEAKS = ("/Users/", "jdoe", "Jane", "@example", "Sample prompt", "Client Work", "fileserver", "castle")


@pytest.fixture
def temp_dir(tmp_path):
    folder = tmp_path / "T"
    folder.mkdir()
    for name in ("macos_render.crash.txt", "upstream_blender.crash.txt"):
        shutil.copy(FIXTURES / name, folder / ("mixar.crash.txt" if name.startswith("macos") else "blender.crash.txt"))
    shutil.copy(FIXTURES / "windows_access_violation.crash.txt", folder / "castle.crash.txt")
    return folder


class FakeServer:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(payload)
        return self.outcomes.pop(0) if self.outcomes else SENT


def _reporter(tmp_path, temp_dir, *, gate=True, server=None, device=DEVICE):
    reporter = Reporter(
        state_dir=str(tmp_path / "state"), temp_dirs=[str(temp_dir)], static=STATIC, own_pid=4242,
        gate=lambda: gate if not callable(gate) else gate(), send=server or FakeServer(), device_id=lambda: device,
    )
    reporter.heartbeat(CURRENT)
    return reporter


def test_reports_are_built_from_mixar_crash_files_only(tmp_path, temp_dir):
    reports = harvest.build_reports(
        temp_dirs=[str(temp_dir)], store=Store(str(tmp_path / "s")), own_pid=1,
        device_id=DEVICE, static=STATIC, current=CURRENT,
    )
    sources = sorted(report["crash_type"] for report in reports)
    assert sources == ["EXCEPTION_ACCESS_VIOLATION", "SIGSEGV"]  # the vanilla Blender log is skipped
    for report in reports:
        assert report["device_id"] == DEVICE and report["kind"] == "native" and report["source"] == "crash_txt"
        assert len(report["report_id"]) == 32
        assert report["context"]["reporter_app_version"] == "4.3.7"
        assert report["context"]["context_source"] == "reporter"


def test_nothing_personal_leaves_the_machine(tmp_path, temp_dir):
    reports = harvest.build_reports(
        temp_dirs=[str(temp_dir)], store=Store(str(tmp_path / "s")), own_pid=1,
        device_id=DEVICE, static=STATIC, current=CURRENT,
    )
    wire = json.dumps(reports)
    for leak in LEAKS:
        assert leak not in wire, leak
    assert "_ZN7blender22DEG_id_type_any_existsEPKNS_9DepsgraphEs" in wire


def test_crash_inherits_the_crashed_sessions_breadcrumb(tmp_path, temp_dir):
    store = Store(str(tmp_path / "s"))
    crash_time = os.path.getmtime(temp_dir / "mixar.crash.txt")
    store.write_session(777, {"pid": 777, "started_at": crash_time - 3600, "updated_at": crash_time - 20,
                              "context": {"app_version": "4.3.5", "cycles_device": "METAL",
                                          "agent_session_id": "sess-1", "agent_run_id": "run-9", "open_tabs": 3}})
    reports = harvest.build_reports(temp_dirs=[str(temp_dir)], store=store, own_pid=1,
                                    device_id=DEVICE, static=STATIC, current=CURRENT)
    mac = next(r for r in reports if r["crash_type"] == "SIGSEGV")
    assert mac["app_version"] == "4.3.5"
    assert mac["context"]["agent_run_id"] == "run-9" and mac["context"]["open_tabs"] == 3
    assert mac["context"]["context_source"] == "session"


def test_signed_out_or_opted_out_sends_nothing_and_keeps_files(tmp_path, temp_dir):
    server = FakeServer()
    reporter = _reporter(tmp_path, temp_dir, gate=False, server=server)
    reporter.tick()
    assert server.payloads == []
    assert reporter.harvest_done is False
    assert sorted(os.listdir(temp_dir)) == ["blender.crash.txt", "castle.crash.txt", "mixar.crash.txt"]


def test_sent_reports_are_never_resent(tmp_path, temp_dir):
    server = FakeServer()
    reporter = _reporter(tmp_path, temp_dir, server=server)
    reporter.tick()
    assert len(server.payloads) == 2 and reporter.harvest_done
    again = _reporter(tmp_path, temp_dir, server=server)  # next launch
    again.tick()
    assert len(server.payloads) == 2
    assert (temp_dir / "mixar.crash.txt").exists()  # sent, still not deleted


def test_a_retryable_failure_is_sent_again_later(tmp_path, temp_dir):
    server = FakeServer([LATER])
    reporter = _reporter(tmp_path, temp_dir, server=server)
    reporter.tick()
    assert len(server.payloads) == 1 and not reporter.harvest_done
    reporter.tick()
    assert len(server.payloads) == 3 and reporter.harvest_done
    assert server.payloads[0]["report_id"] == server.payloads[1]["report_id"]


def test_a_refused_report_is_not_retried(tmp_path, temp_dir):
    server = FakeServer([REFUSED, SENT])
    _reporter(tmp_path, temp_dir, server=server).tick()
    _reporter(tmp_path, temp_dir, server=server).tick()
    assert len(server.payloads) == 2
    ledger = Store(str(tmp_path / "state")).sent_ids()
    assert sorted(entry["outcome"] for entry in ledger.values()) == ["refused", "sent"]


def test_no_device_id_sends_nothing(tmp_path, temp_dir):
    server = FakeServer()
    _reporter(tmp_path, temp_dir, server=server, device=None).tick()
    assert server.payloads == []


def test_exceptions_wait_for_sign_in_then_send_once(tmp_path, temp_dir):
    signed_in = {"value": False}
    server = FakeServer()
    reporter = _reporter(tmp_path, temp_dir, gate=lambda: signed_in["value"], server=server)
    reporter.enqueue_exception({"report_id": "py-1", "device_id": "", "kind": "python",
                                "source": "excepthook", "_dedup_key": "k"})
    reporter.tick()
    assert server.payloads == [] and len(reporter.store.pending()) == 1
    signed_in["value"] = True
    reporter.tick()
    python = [p for p in server.payloads if p["kind"] == "python"]
    assert len(python) == 1 and python[0]["device_id"] == DEVICE and "_dedup_key" not in python[0]
    assert reporter.store.pending() == []
    reporter.tick()
    assert len([p for p in server.payloads if p["kind"] == "python"]) == 1


def test_breadcrumb_is_written_and_removed_on_a_clean_quit(tmp_path, temp_dir):
    reporter = _reporter(tmp_path, temp_dir, gate=False)
    reporter.tick()
    path = Path(reporter.store.session_path(4242))
    data = json.loads(path.read_text())
    assert data["pid"] == 4242 and data["context"]["app_version"] == "4.3.7"
    assert data["context"]["platform"] == "darwin"
    reporter.stop(clean=False)
    assert path.exists()
    reporter.stop(clean=True)
    assert not path.exists()


def test_stale_breadcrumbs_are_pruned(tmp_path):
    store = Store(str(tmp_path / "s"))
    store.write_session(1, {"pid": 1, "started_at": 0, "updated_at": time.time() - 30 * 86400})
    store.write_session(2, {"pid": 2, "started_at": 0, "updated_at": time.time()})
    assert [s["pid"] for s in store.sessions(own_pid=99)] == [2]
    assert not os.path.exists(store.session_path(1))


def test_macos_reports_are_read_from_the_given_folder(tmp_path, temp_dir):
    reports_dir = tmp_path / "DiagnosticReports"
    reports_dir.mkdir()
    shutil.copy(FIXTURES / "macos_abort.ips.json", reports_dir / "Mixar-2026-10-23-152401.ips")
    shutil.copy(FIXTURES / "macos_segv_handled.ips.json", reports_dir / "Mixar-2026-10-26-183129.ips")
    reports = harvest.build_reports(temp_dirs=[], report_dirs=[str(reports_dir)], store=Store(str(tmp_path / "s")),
                                    own_pid=1, device_id=DEVICE, static=STATIC, current=CURRENT)
    assert [r["source"] for r in reports] == ["macos_ips"]  # the handled SIGSEGV is crash.txt's
    assert reports[0]["crash_type"] == "SIGABRT" and reports[0]["app_version"] == "4.3.5"
    assert "/Users/" not in json.dumps(reports)


def test_old_crash_files_are_ignored(tmp_path, temp_dir):
    old = time.time() - 40 * 86400
    for name in os.listdir(temp_dir):
        os.utime(temp_dir / name, (old, old))
    assert harvest.candidate_files([str(temp_dir)], [str(temp_dir)]) == []


def test_new_crash_logs_carry_build_images_and_addresses(tmp_path):
    folder = tmp_path / "T"
    folder.mkdir()
    shutil.copy(FIXTURES / "macos_render_v1.crash.txt", folder / "mixar.crash.txt")
    reports = harvest.build_reports(temp_dirs=[str(folder)], store=Store(str(tmp_path / "s")), own_pid=1,
                                    device_id=DEVICE, static=STATIC, current=CURRENT)
    report = reports[0]
    assert report["app_version"] == "4.3.8"  # from the crash log, not the reporting session
    assert report["git_sha"] == "0123456789abcdef0123456789abcdef01234567" and report["arch"] == "arm64"
    assert report["images"][0]["id"] == "8061b8de1ba9340fa6af312e3b71dbc5"
    assert all("address" in frame for frame in report["frames"])
    assert "# mixar symbolication v1" in report["raw_text"]
