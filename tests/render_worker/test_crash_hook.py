# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The worker's QA crash hook (``supervisor.crash_next`` -> ``worker_jobs._crash_now``).

It must be a real native fault on every platform, so the crash path (faulthandler
dump, Blender's crash log, one retry on a fresh worker) can be tested anywhere. A
ctypes foreign call (``string_at``) is wrapped in SEH on Windows and only raises
``OSError``; ``faulthandler._sigsegv()`` is a CRT ``raise()`` there that exits
without reaching Blender's unhandled-exception filter.
"""

import ast
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKER_JOBS = REPO / "src" / "scripts" / "mixar" / "modules" / "common" / "render_worker" / "worker_jobs.py"


def _crash_now_source() -> str:
    source = WORKER_JOBS.read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == "_crash_now":
            return ast.get_source_segment(source, node)
    raise AssertionError("worker_jobs._crash_now is missing")


def test_crash_hook_is_no_foreign_call_or_raised_signal():
    names = {node.attr for node in ast.walk(ast.parse(_crash_now_source())) if isinstance(node, ast.Attribute)}
    assert not names & {"string_at", "memmove", "memset", "_sigsegv", "kill", "raise_signal"}, names
    assert "from_address" in names


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal chaining")
def test_crash_hook_dies_by_the_signal_after_the_faulthandler_dump(tmp_path):
    script = tmp_path / "run.py"
    script.write_text(textwrap.dedent("""\
        import sys
        from unittest.mock import MagicMock
        for name in ("bpy", "bpy.types", "bpy.props", "bpy.utils", "bpy.app"):
            sys.modules[name] = MagicMock(name=name)
        sys.path.insert(0, {scripts!r})
        from mixar.modules.common.crash_reports.core import pyfault
        pyfault.enable(sys.argv[1])
        """).format(scripts=str(REPO / "src" / "scripts")) + _crash_now_source() + "\n\n_crash_now()\n")
    env = {key: value for key, value in os.environ.items() if key != "PYTHONFAULTHANDLER"}
    result = subprocess.run([sys.executable, str(script), str(tmp_path / "state")], capture_output=True,
                            text=True, env=env, timeout=60)
    assert result.returncode in (-signal.SIGSEGV, -signal.SIGBUS), (result.returncode, result.stderr)
    (dump_file,) = (tmp_path / "state").glob("pyfault-*.txt")
    assert "_crash_now" in dump_file.read_text(encoding="utf-8")
