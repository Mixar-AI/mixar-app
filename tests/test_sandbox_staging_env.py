# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The parent hands its worker a staging directory; the worker reads it (v3)."""

import os
import sys
from unittest.mock import MagicMock

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.bootstrap import sandbox_supervisor as sup  # noqa: E402
from mixar.modules.common.agent_execution import paths, staging  # noqa: E402
from mixar.modules.common.agent_execution.identity import worker_identity_from_env  # noqa: E402


def test_spawn_passes_staging_dir_created_by_parent(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_AGENT_CACHE_DIR", str(tmp_path))
    captured = {}

    class Proc:
        pid = 1

        def poll(self):
            return None

    def fake_popen(argv, **kw):
        captured["env"] = kw["env"]
        return Proc()

    monkeypatch.setattr(sup, "_children", {})
    monkeypatch.setattr(sup, "_child_logs", {})
    monkeypatch.setattr(sup.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sup, "_headless_main_path", lambda: "/x/headless_main.py")
    monkeypatch.setitem(sys.modules, "mixar.modules.auth.core.auth",
                        MagicMock(get_access_token=lambda: "tok"))
    monkeypatch.setitem(sys.modules, "mixar.config.config",
                        MagicMock(get_server_url=lambda: "http://b"))
    out = sup.spawn_sandbox("inst-sbx-0", parent_instance_id="inst")
    assert out["success"]
    staging_dir = captured["env"]["MIXAR_SANDBOX_STAGING_DIR"]
    assert staging_dir == paths.staging_dir("inst") and os.path.isdir(staging_dir)
    assert captured["env"]["MIXAR_SANDBOX_PARENT_INSTANCE_ID"] == "inst"


def test_identity_reads_staging_dir_and_staging_root_validates(tmp_path, monkeypatch):
    ident = worker_identity_from_env({
        "MIXAR_SANDBOX_CONNECTION_ID": "inst-sbx-0",
        "MIXAR_SANDBOX_STAGING_DIR": str(tmp_path),
    })
    assert ident.staging_dir == str(tmp_path) and ident.parent_instance_id == "inst"
    monkeypatch.setenv("MIXAR_SANDBOX_STAGING_DIR", str(tmp_path))
    assert staging.staging_root() == str(tmp_path)
    monkeypatch.setenv("MIXAR_SANDBOX_STAGING_DIR", str(tmp_path / "missing"))
    try:
        staging.staging_root()
    except RuntimeError as exc:
        assert "staging" in str(exc)
    else:
        raise AssertionError("missing staging dir must be refused")
