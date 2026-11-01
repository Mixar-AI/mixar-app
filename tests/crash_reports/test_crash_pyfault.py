# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Python stacks for native crashes: faulthandler's dump (``core/pyfault.py``),
its parser, pairing with the crash file, the wire fields, cleanup and the
422 fallback. Windows frame names and the re-raise trim: test_crash_parse.py."""

import faulthandler
import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from mixar.modules.common.crash_reports.core import harvest
from mixar.modules.common.crash_reports.core.parse_pyfault import matches, parse_pyfault
from mixar.modules.common.crash_reports.core.reporter import INVALID, LATER, REFUSED, SENT, Reporter
from mixar.modules.common.crash_reports.core.scrub import python_stack_file
from mixar.modules.common.crash_reports.core.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
WINDOWS_CTYPES = (FIXTURES / "windows_ctypes_access_violation.crashlog").read_text(encoding="utf-8")
REPO = Path(__file__).resolve().parents[2]
STATIC = {"platform": "windows", "os_version": "Windows 11", "cpu_arch": "x86_64"}
CURRENT = {"app_version": "4.3.9", "blender_version": "5.2.0"}
DEVICE = "0123456789abcdef0123456789abcdef"
LEAKS = ("/Users/", "jdoe", "Jane", "@example", "Client Work", "fileserver", "castle", "Personal", "Dropbox",
         "Program Files", "AppData")

# -- faulthandler's dump ------------------------------------------------------

def _crashing_frame(handle):
    faulthandler.dump_traceback(file=handle, all_threads=True)


def test_a_real_faulthandler_dump_parses_to_the_current_thread(tmp_path):
    gate = threading.Event()
    other = threading.Thread(target=gate.wait, name="Idle", daemon=True)
    other.start()
    path = tmp_path / "pyfault-1.txt"
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Fatal Python error: Segmentation fault\n\n")
            handle.flush()
            _crashing_frame(handle)
    finally:
        gate.set()
    text = path.read_text(encoding="utf-8")
    assert "Current thread 0x" in text and "\nThread 0x" in text
    dump = parse_pyfault(text, "SIGSEGV")
    stack = dump["python_stack"]
    assert stack[-1]["function"] == "_crashing_frame"  # innermost LAST
    assert stack[-2]["function"] == "test_a_real_faulthandler_dump_parses_to_the_current_thread"
    assert stack[-1]["file"] == "test_crash_pyfault.py"  # not ours: basename
    assert all(isinstance(frame["line"], int) and frame["line"] > 0 for frame in stack)
    assert all("Idle" not in frame["function"] and frame["function"] != "wait" for frame in stack[-2:])
    assert dump["python_thread"].startswith("0x")


SAMPLE = textwrap.dedent(r"""
    Windows fatal exception: code 0x8001010d

    Current thread 0x00001a2c (most recent call first):
      File "C:\Program Files\Mixar\4.3\scripts\mixar\modules\common\file_dialog.py", line 10 in pick

    Windows fatal exception: access violation

    Thread 0x00002b3c (most recent call first):
      File "C:\Users\Jane Smith\AppData\Roaming\Mixar\4.3\scripts\mixar\modules\common\api\client.py", line 88 in _poll
      File "C:\Program Files\Mixar\4.3\python\lib\threading.py", line 1012 in run

    Current thread 0x00001a2c [MainThread] (most recent call first):
      File "C:\Program Files\Mixar\4.3\python\lib\ctypes\__init__.py", line 525 in string_at
      File "\\fileserver\home$\Jane Smith\Client Work\helper_tools.py", line 7 in helper
      File "C:\Program Files\Mixar\4.3\scripts\mixar\modules\space_mixie_chat\core\preview_render.py", line 212 in render_preview
      File "C:\Program Files\Mixar\4.3\scripts\startup\bl_operators\wm.py", line ??? in execute

    Thread 0x00003c4d (most recent call first):
      <no Python frame>
    """).lstrip("\n")


def test_a_crafted_multithread_windows_dump_keeps_the_crashing_thread_of_the_last_dump():
    dump = parse_pyfault(SAMPLE, "EXCEPTION_ACCESS_VIOLATION")
    assert dump["header"] == "Windows fatal exception: access violation"
    assert dump["python_thread"] == "0x00001a2c [MainThread]"
    assert dump["python_stack"] == [
        {"file": "scripts/startup/bl_operators/wm.py", "line": 0, "function": "execute"},
        {"file": "mixar/modules/space_mixie_chat/core/preview_render.py", "line": 212, "function": "render_preview"},
        {"file": "helper_tools.py", "line": 7, "function": "helper"},
        {"file": "__init__.py", "line": 525, "function": "string_at"},
    ]


def test_a_dump_for_another_exception_is_not_this_crash():
    # The last dump is a handled first-chance exception, the crash (a C++
    # exception faulthandler ignores) has none.
    first_chance = "Windows fatal exception: code 0xc0000005\n\nCurrent thread 0x1 (most recent call first):\n"
    assert parse_pyfault(SAMPLE, "EXCEPTION_STACK_OVERFLOW") is None
    assert parse_pyfault(SAMPLE.split("\n\nWindows fatal exception: access")[0], "EXCEPTION_ACCESS_VIOLATION") is None
    assert matches("Windows fatal exception: code 0xc000001d", "EXCEPTION_ILLEGAL_INSTRUCTION")
    assert not matches("Windows fatal exception: code 0x8001010d", "EXCEPTION_ILLEGAL_INSTRUCTION")
    assert matches("Fatal Python error: Bus error", "SIGSEGV")  # crash.txt names SIGBUS SIGSEGV
    assert matches("Fatal Python error: Aborted", "SIGABRT")
    assert not matches("Fatal Python error: Aborted", "SIGSEGV")
    assert not matches("Fatal Python error: Segmentation fault", "EXCEPTION_ACCESS_VIOLATION")
    assert not matches(first_chance.splitlines()[0], "SIGSEGV")
    assert parse_pyfault("", "SIGSEGV") is None
    assert parse_pyfault("Fatal Python error: Segmentation fault\n\nThread 0x1 (most recent call first):\n", None) is None


def test_the_stack_is_capped_at_the_innermost_64_frames():
    frames = "".join(f'  File "/x/scripts/mixar/m.py", line {n} in f{n}\n' for n in range(100))
    dump = parse_pyfault("Fatal Python error: Segmentation fault\n\nCurrent thread 0x1 (most recent call first):\n"
                         + frames)
    assert len(dump["python_stack"]) == 64
    assert dump["python_stack"][-1]["function"] == "f0"  # faulthandler's first line is the innermost


@pytest.mark.parametrize(("raw", "expected"), [
    ("/Applications/Mixar.app/Contents/Resources/4.3/scripts/mixar/modules/a/b.py", "mixar/modules/a/b.py"),
    (r"C:\Program Files\Mixar\4.3\scripts\mixar\bootstrap\x.py", "mixar/bootstrap/x.py"),
    (r"C:\Users\Jane Smith\AppData\Roaming\Mixar\4.3\scripts\mixar\modules\c.py", "mixar/modules/c.py"),
    ("/opt/mixar/4.3/scripts/startup/bl_ui/space_view3d.py", "scripts/startup/bl_ui/space_view3d.py"),
    ("/opt/mixar/4.3/scripts/modules/bpy/utils/__init__.py", "scripts/modules/bpy/utils/__init__.py"),
    ("/opt/mixar/4.3/scripts/addons_core/node_wrangler/x.py", "scripts/addons_core/node_wrangler/x.py"),
    ("/Users/jdoe/Dropbox (Personal)/Client Work/tools/helper.py", "helper.py"),
    (r"\\fileserver\home$\Jane Smith\castle.py", "castle.py"),
    ("/opt/mixar/4.3/python/lib/python3.13/threading.py", "threading.py"),
    ("<frozen importlib._bootstrap>", "<frozen importlib._bootstrap>"),
    ("mixar/modules/a.py", "mixar/modules/a.py"),
])
def test_python_stack_files_keep_no_user_directory(raw, expected):
    assert python_stack_file(raw) == expected


# -- pairing with the crash file ---------------------------------------------

def _write(path: Path, text: str, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _build(tmp_path, temp, report_dirs=None, own_pid=1):
    return harvest.build_reports(temp_dirs=[str(temp)], report_dirs=report_dirs, store=Store(str(tmp_path / "state")),
                                 own_pid=own_pid, device_id=DEVICE, static=STATIC, current=CURRENT)


def test_an_app_crash_carries_the_dump_of_its_session(tmp_path):
    now = time.time()
    crash = _write(tmp_path / "T" / "mixar.crash.txt", WINDOWS_CTYPES, now)
    store = Store(str(tmp_path / "state"))
    store.write_session(777, {"pid": 777, "started_at": now - 600, "updated_at": now - 5})
    dump = _write(Path(store.pyfault_path(777)), SAMPLE, now - 1)
    _write(Path(store.pyfault_path(778)), SAMPLE, now - 1)  # another session: never this crash's
    report = _build(tmp_path, crash.parent)[0]
    assert report["python_stack"][-1] == {"file": "__init__.py", "line": 525, "function": "string_at"}
    assert report["python_thread"] == "0x00001a2c [MainThread]"
    assert report["_pyfault_path"] == str(dump)
    assert report["python_frames"] == []  # the crash log's own section was empty


def test_without_a_breadcrumb_the_dump_written_with_the_crash_is_used(tmp_path):
    now = time.time()
    crash = _write(tmp_path / "T" / "mixar.crash.txt", WINDOWS_CTYPES, now)
    store = Store(str(tmp_path / "state"))
    _write(Path(store.pyfault_path(900)), SAMPLE, now - 3600)  # an hour off: another crash
    near = _write(Path(store.pyfault_path(901)), SAMPLE, now - 2)
    report = _build(tmp_path, crash.parent)[0]
    assert report["_pyfault_path"] == str(near)
    os.unlink(near)
    assert "python_stack" not in _build(tmp_path, crash.parent)[0]


def test_the_running_sessions_own_dump_is_never_paired(tmp_path):
    now = time.time()
    crash = _write(tmp_path / "T" / "mixar.crash.txt", WINDOWS_CTYPES, now)
    _write(Path(Store(str(tmp_path / "state")).pyfault_path(4242)), SAMPLE, now)
    assert "python_stack" not in _build(tmp_path, crash.parent, own_pid=4242)[0]


POSIX_DUMP = textwrap.dedent("""\
    Fatal Python error: Aborted

    Current thread 0x000000020836c840 (most recent call first):
      File "/Applications/Mixar.app/Contents/Resources/4.3/scripts/mixar/modules/paint/bake.py", line 41 in bake
      File "/Applications/Mixar.app/Contents/Resources/4.3/scripts/mixar/modules/paint/ops.py", line 9 in execute

    Extension modules: numpy._core._multiarray_umath (total: 1)
    """)


def test_a_macos_abort_report_pairs_by_its_pid(tmp_path):
    reports_dir = tmp_path / "DiagnosticReports"
    first, rest = (FIXTURES / "macos_abort.ips.json").read_text(encoding="utf-8").split("\n", 1)
    body = json.loads(rest)
    body["pid"] = 5150
    ips = _write(reports_dir / "Mixar-2026-10-23-152401.ips", first + "\n" + json.dumps(body))
    store = Store(str(tmp_path / "state"))
    dump = _write(Path(store.pyfault_path(5150)), POSIX_DUMP, os.stat(ips).st_mtime - 8)
    temp = tmp_path / "T"
    temp.mkdir()
    report = _build(tmp_path, temp, report_dirs=[str(reports_dir)])[0]
    assert report["source"] == "macos_ips"
    assert [f["function"] for f in report["python_stack"]] == ["execute", "bake"]
    assert report["python_stack"][-1]["file"] == "mixar/modules/paint/bake.py"
    assert report["_pyfault_path"] == str(dump)


def test_a_moved_worker_crash_carries_its_sibling_dump(tmp_path):
    temp = tmp_path / "T"
    crash_dir = temp / "mixar_render_worker_crashes"
    log = (FIXTURES / "macos_render_v1.crashlog").read_text(encoding="utf-8")
    _write(crash_dir / "5150-preview-1.crash.txt", log)
    sibling = _write(crash_dir / "5150-preview-1.pyfault.txt",
                     POSIX_DUMP.replace("Aborted", "Segmentation fault"), time.time() - 86400)
    report = _build(tmp_path, temp)[0]
    assert report["kind"] == "worker_crash"
    assert report["python_stack"][-1]["function"] == "bake"
    assert report["_pyfault_path"] == str(sibling)


def test_a_worker_crash_left_in_its_temp_dir_reads_the_dump_beside_it(tmp_path):
    temp = tmp_path / "T"
    worker_tmp = temp / "mixar_render_worker" / "4242" / "worker-render" / "tmp"
    now = time.time()
    _write(worker_tmp / "snapshot.crash.txt", (FIXTURES / "macos_render_v1.crashlog").read_text(encoding="utf-8"), now)
    dump = _write(worker_tmp / "pyfault-6000.txt", POSIX_DUMP.replace("Aborted", "Bus error"), now)
    report = _build(tmp_path, temp)[0]
    assert report["python_stack"][-1]["function"] == "bake"
    assert "_pyfault_path" not in report  # read only: the supervisor's folder
    assert dump.exists()


def test_nothing_personal_leaves_in_the_python_stack(tmp_path):
    now = time.time()
    crash = _write(tmp_path / "T" / "mixar.crash.txt", WINDOWS_CTYPES, now)
    store = Store(str(tmp_path / "state"))
    leaky = SAMPLE.replace("render_preview", "jdoe@example.com").replace("[MainThread]", "[Jane Smith]")
    _write(Path(store.pyfault_path(777)), leaky, now)
    report = _build(tmp_path, crash.parent)[0]
    wire = json.dumps({k: v for k, v in report.items() if not k.startswith("_")})
    assert "python_stack" in wire
    for leak in LEAKS:
        assert leak not in wire, leak


# -- the reporter: cleanup, the 422 fallback -----------------------------------

class FakeServer:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(payload)
        return self.outcomes.pop(0) if self.outcomes else SENT


def _reporter(tmp_path, temp, server, own_pid=4242):
    reporter = Reporter(state_dir=str(tmp_path / "state"), temp_dirs=[str(temp)], static=STATIC, own_pid=own_pid,
                        gate=lambda: True, send=server, device_id=lambda: DEVICE)
    reporter.heartbeat(CURRENT)
    return reporter


def _crash_with_dump(tmp_path):
    now = time.time()
    crash = _write(tmp_path / "T" / "mixar.crash.txt", WINDOWS_CTYPES, now)
    store = Store(str(tmp_path / "state"))
    store.write_session(777, {"pid": 777, "started_at": now - 600, "updated_at": now - 5})
    return crash, _write(Path(store.pyfault_path(777)), SAMPLE, now)


def test_a_sent_report_deletes_its_dump_and_a_retry_keeps_it(tmp_path):
    crash, dump = _crash_with_dump(tmp_path)
    server = FakeServer([LATER])
    reporter = _reporter(tmp_path, crash.parent, server)
    reporter.tick()
    assert dump.exists() and not reporter.harvest_done
    assert "_pyfault_path" not in server.payloads[0] and server.payloads[0]["python_stack"]
    reporter.tick()
    assert not dump.exists() and reporter.harvest_done
    assert crash.exists()  # the app's crash log is never deleted


def test_a_422_is_sent_again_once_without_the_newer_fields(tmp_path):
    crash, dump = _crash_with_dump(tmp_path)
    server = FakeServer([INVALID, SENT])
    reporter = _reporter(tmp_path, crash.parent, server)
    reporter.tick()
    assert len(server.payloads) == 2
    assert "python_stack" in server.payloads[0] and "python_thread" in server.payloads[0]
    assert "python_stack" not in server.payloads[1] and "python_thread" not in server.payloads[1]
    assert server.payloads[1]["frames"] == server.payloads[0]["frames"]
    assert reporter.store.sent_ids()[server.payloads[0]["report_id"]]["outcome"] == SENT
    assert not dump.exists()


def test_a_422_without_the_newer_fields_is_refused_for_good(tmp_path):
    crash, dump = _crash_with_dump(tmp_path)
    os.unlink(dump)
    server = FakeServer([INVALID])
    reporter = _reporter(tmp_path, crash.parent, server)
    reporter.tick()
    assert len(server.payloads) == 1
    assert reporter.store.sent_ids()[server.payloads[0]["report_id"]]["outcome"] == REFUSED


def test_a_422_then_offline_retries_the_whole_report_later(tmp_path):
    crash, dump = _crash_with_dump(tmp_path)
    server = FakeServer([INVALID, LATER])
    reporter = _reporter(tmp_path, crash.parent, server)
    reporter.tick()
    assert not reporter.harvest_done and dump.exists()
    reporter.tick()
    assert "python_stack" in server.payloads[2] and not dump.exists()


def test_default_send_reads_422_as_invalid(monkeypatch):
    from mixar.modules.common.crash_reports.core import reporter as reporter_mod

    class Client:
        status = 422

        def post(self, *args, **kwargs):
            return type("R", (), {"status_code": self.status})()

    client = Client()
    monkeypatch.setitem(sys.modules, "mixar.modules.common.api.client",
                        type(sys)("client_stub"))
    sys.modules["mixar.modules.common.api.client"].get_http_client = lambda: client
    assert reporter_mod.default_send({}) == INVALID
    client.status = 400
    assert reporter_mod.default_send({}) == REFUSED


def test_a_clean_quit_removes_the_sessions_dump(tmp_path):
    temp = tmp_path / "T"
    temp.mkdir()
    reporter = _reporter(tmp_path, temp, FakeServer())
    reporter.tick()
    own = _write(Path(reporter.store.pyfault_path(4242)), "")
    reporter.stop(clean=True)
    assert not own.exists()
    assert not os.path.exists(reporter.store.session_path(4242))


def test_stale_dumps_go_with_their_breadcrumbs_or_when_none_is_left(tmp_path):
    temp = tmp_path / "T"
    temp.mkdir()
    reporter = _reporter(tmp_path, temp, FakeServer())
    store = reporter.store
    old = time.time() - 3600
    store.write_session(777, {"pid": 777, "started_at": old - 600, "updated_at": old})
    with_breadcrumb = _write(Path(store.pyfault_path(777)), "", old)
    orphan = _write(Path(store.pyfault_path(778)), "", old)
    fresh_orphan = _write(Path(store.pyfault_path(779)), "")  # another instance, starting up
    live = _write(Path(store.pyfault_path(780)), "", old)  # another instance, running
    store.write_session(780, {"pid": 780, "started_at": old, "updated_at": time.time()})
    reporter.tick()
    assert reporter.harvest_done
    assert not with_breadcrumb.exists() and not orphan.exists()
    assert fresh_orphan.exists() and live.exists()


def test_the_running_sessions_dump_is_emptied_past_its_cap(tmp_path, monkeypatch):
    from mixar.modules.common.crash_reports.core import reporter as reporter_mod
    monkeypatch.setattr(reporter_mod, "PYFAULT_MAX_BYTES", 100)
    temp = tmp_path / "T"
    temp.mkdir()
    reporter = _reporter(tmp_path, temp, FakeServer())
    own = _write(Path(reporter.store.pyfault_path(4242)), "x" * 50)
    reporter.tick()
    assert own.stat().st_size == 50
    own.write_text("x" * 500)
    reporter.tick()
    assert own.stat().st_size == 0


def test_a_handled_worker_crash_takes_its_dump_along(tmp_path):
    temp = tmp_path / "T"
    crash_dir = temp / "mixar_render_worker_crashes"
    log = _write(crash_dir / "5150-render-1.crash.txt", (FIXTURES / "macos_render_v1.crashlog").read_text("utf-8"))
    sibling = _write(crash_dir / "5150-render-1.pyfault.txt", "")  # no dump in it: still ours
    store = Store(str(tmp_path / "state"))
    store.mark_sent(harvest.report_id_for("crash_txt", log.read_text(encoding="utf-8")))
    harvest.remove_handled_worker_crashes([str(temp)], store)
    assert not log.exists() and not sibling.exists()


def test_old_lone_worker_dumps_are_pruned(tmp_path):
    temp = tmp_path / "T"
    crash_dir = temp / "mixar_render_worker_crashes"
    old = time.time() - 40 * 86400
    stale = _write(crash_dir / "5150-render-2.pyfault.txt", POSIX_DUMP, old)
    fresh = _write(crash_dir / "5150-render-3.pyfault.txt", POSIX_DUMP)
    harvest.worker_crash_files([str(temp)])
    assert not stale.exists() and fresh.exists()


# -- enabling faulthandler (subprocesses: pytest owns this one's) -------------

_PRELUDE = textwrap.dedent("""\
    import sys
    from unittest.mock import MagicMock
    for name in ("bpy", "bpy.types", "bpy.props", "bpy.utils", "bpy.app"):
        sys.modules[name] = MagicMock(name=name)
    sys.path.insert(0, {scripts!r})
    from mixar.modules.common.crash_reports.core import pyfault
    """)


def _run(tmp_path, body: str, *args) -> subprocess.CompletedProcess:
    script = tmp_path / "run.py"
    script.write_text(_PRELUDE.format(scripts=str(REPO / "src" / "scripts")) + textwrap.dedent(body))
    env = {key: value for key, value in os.environ.items() if key != "PYTHONFAULTHANDLER"}
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, env=env,
                          timeout=60)


def test_enable_writes_the_dump_file_and_a_clean_exit_removes_it(tmp_path):
    result = _run(tmp_path, """\
        import faulthandler, os
        path = pyfault.enable(sys.argv[1])
        print(path == os.path.join(sys.argv[1], "pyfault-%d.txt" % os.getpid()), os.path.exists(path),
              faulthandler.is_enabled())
        print(pyfault.enable(sys.argv[1]) == path)  # once
        pyfault.disable()
        print(os.path.exists(path), faulthandler.is_enabled(), pyfault.path())
        """, str(tmp_path / "state"))
    assert result.stdout.split() == ["True", "True", "True", "True", "False", "False", "None"], result.stderr


def test_faulthandler_someone_else_enabled_is_left_alone(tmp_path):
    result = _run(tmp_path, """\
        import faulthandler
        faulthandler.enable()
        print(pyfault.enable(sys.argv[1]))
        """, str(tmp_path / "state"))
    assert result.stdout.strip() == "None"
    assert not (tmp_path / "state").exists()


CRASHER = '''\
def render_preview():
    import ctypes
    ctypes.string_at(0)
'''


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal chaining")
def test_a_real_native_crash_dumps_the_python_stack_then_dies_by_the_signal(tmp_path):
    module = tmp_path / "install" / "scripts" / "mixar" / "modules" / "qa"
    module.mkdir(parents=True)
    (module / "crasher.py").write_text(CRASHER)
    result = _run(tmp_path, """\
        import importlib.util, threading
        spec = importlib.util.spec_from_file_location("crasher", sys.argv[2])
        crasher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(crasher)
        pyfault.enable(sys.argv[1])
        threading.Thread(target=threading.Event().wait, name="Idle", daemon=True).start()
        crasher.render_preview()
        """, str(tmp_path / "state"), str(module / "crasher.py"))
    # The previous handler (here SIG_DFL) ran after the dump: death by the signal.
    assert result.returncode in (-signal.SIGSEGV, -signal.SIGBUS), (result.returncode, result.stderr)
    (dump_file,) = (tmp_path / "state").glob("pyfault-*.txt")
    text = dump_file.read_text(encoding="utf-8")
    assert text.startswith(("Fatal Python error: Segmentation fault", "Fatal Python error: Bus error"))
    dump = parse_pyfault(text, "SIGSEGV")
    assert dump["python_stack"][-2:] == [
        {"file": "mixar/modules/qa/crasher.py", "line": 3, "function": "render_preview"},
        {"file": "__init__.py", "line": dump["python_stack"][-1]["line"], "function": "string_at"},
    ]
    assert str(tmp_path) not in json.dumps(dump)


@pytest.mark.skipif(sys.platform not in ("darwin", "linux"), reason="POSIX sigaction layout")
def test_a_siginfo_sigbus_handler_stays_in_front_and_no_alt_stack_is_left(tmp_path):
    result = _run(tmp_path, """\
        import ctypes, signal
        libc = ctypes.CDLL(None, use_errno=True)
        offset, siginfo = pyfault._sigaction_layout()
        # A stand-in for BLI_mmap's recovery handler (never called).
        action = ctypes.create_string_buffer(256)
        handler = ctypes.cast(libc.getpid, ctypes.c_void_p).value
        action.raw = handler.to_bytes(8, sys.byteorder) + action.raw[8:]
        flags = siginfo.to_bytes(4, sys.byteorder)
        action.raw = action.raw[:offset] + flags + action.raw[offset + 4:]
        assert libc.sigaction(signal.SIGBUS, action, None) == 0
        segv_before = ctypes.create_string_buffer(256)
        libc.sigaction(signal.SIGSEGV, None, segv_before)
        pyfault.enable(sys.argv[1])
        after = ctypes.create_string_buffer(256)
        libc.sigaction(signal.SIGBUS, None, after)
        segv_after = ctypes.create_string_buffer(256)
        libc.sigaction(signal.SIGSEGV, None, segv_after)
        print(after.raw[:8] == action.raw[:8], segv_after.raw[:8] != segv_before.raw[:8])
        stack = pyfault._alt_stack()
        _, disable = pyfault._stack_t()
        print(bool(stack.ss_flags & disable))
        """, str(tmp_path / "state"))
    # SIGBUS: still the SA_SIGINFO handler; SIGSEGV: faulthandler in front.
    assert result.stdout.split() == ["True", "True", "True"], result.stderr
