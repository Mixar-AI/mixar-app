# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Start and stop an isolated QA Mixar app on macOS, Windows or Linux.

A Python port of the harness's ``run_qa_app_parallel.sh`` (bash only): same
isolated profile, same in-memory keyring (``MIXAR_QA=1``), same QA server on a
local port. One app per port; ``stop`` only touches the process this module
started.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

READY_PATTERN = re.compile(r"qa_server. listening")


def default_build(repo: Path, env: str = "Dev") -> Path:
    if sys.platform == "darwin":
        return repo / "build" / env / "bin" / "Mixar.app"
    return repo / "build" / env / "bin"


def executable(build: Path) -> Path:
    if sys.platform == "darwin":
        return build / "Contents" / "MacOS" / "Mixar"
    if sys.platform == "win32":
        return build / "mixar.exe"
    for name in ("mixar", "Mixar", "blender"):
        if (build / name).exists():
            return build / name
    return build / "mixar"


def config_file(build: Path) -> Path:
    root = build / "Contents" / "Resources" if sys.platform == "darwin" else build
    found = sorted(root.glob("*/config/mixar.json"))
    if not found:
        raise FileNotFoundError(f"no */config/mixar.json under {root}")
    return found[0]


def port_busy(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


@dataclass
class QAApp:
    process: subprocess.Popen
    port: int
    out: Path
    profile: Path
    mixed: bool

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def stall_log(self) -> Path:
        return self.profile / "config" / "mixar" / "stalls.jsonl"

    def stop(self, harness: Path) -> None:
        subprocess.run([sys.executable, str(harness / "driver" / "qa_client.py"), "--port", str(self.port), "quit"],
                       capture_output=True, timeout=30)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


def start(harness: Path, build: Path, port: int, out_root: Path, *, mixed: bool = False,
          extra_env: dict | None = None, timeout: float = 60.0) -> QAApp:
    """Launch the app with the QA server and wait until it listens."""
    exe = executable(build)
    if not exe.exists():
        raise FileNotFoundError(f"no Mixar executable at {exe}")
    if port_busy(port):
        raise RuntimeError(f"port {port} already serving; stop that app first")
    cfg = json.loads(config_file(build).read_text())
    out = out_root / f"qa-p{port}-{time.strftime('%Y%m%d-%H%M%S')}"
    profile = out / "profile"
    for sub in ("scripts/startup", "datafiles/mixar", "config"):
        (profile / sub).mkdir(parents=True, exist_ok=True)
    (profile / "scripts/startup/qa_boot.py").write_text((harness / "qa_boot_startup.py").read_text())
    email = cfg["dev_bypass"]["username"].strip().lower()
    # Guest builds have no bypass email. Mark the isolated device as seen too,
    # otherwise the first-run tour can intercept this scenario's input.
    (profile / "datafiles/mixar/onboarding_seen.json").write_text(
        json.dumps({"seen": True, "users_seen": [email]}))
    env = dict(os.environ,
               MIXAR_QA="1", MIXAR_USER_RESOURCES=str(profile), MIXAR_QA_OUT=str(out),
               MIXAR_QA_PORT=str(port), MIXAR_QA_RECORD="0",
               MIXAR_OPERATION_HISTORY_DIR=str(out / "ophistory"), MIXAR_QA_MIXED="1" if mixed else "0")
    env.update(extra_env or {})
    args = [str(exe), "-p", "60", "60", "1680", "1050"]
    if not mixed:
        args.append("--enable-event-simulate")
    args += ["--python", str(harness / "driver" / "qa_server.py")]
    log = open(out / "app.log", "wb")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    process = subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"app exited during startup ({process.returncode}); see {out / 'app.log'}")
        text = (out / "app.log").read_text(errors="replace")
        if READY_PATTERN.search(text):
            return QAApp(process, port, out, profile, mixed)
        time.sleep(0.5)
    process.kill()
    raise RuntimeError(f"QA server never came up; see {out / 'app.log'}")
