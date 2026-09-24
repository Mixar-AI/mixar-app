# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Artifact registry: id validation, hash/size checks, cleanup (harness v3)."""

import hashlib
import os
import sys
import time
import uuid
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.common.agent_execution import artifacts, paths  # noqa: E402


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_AGENT_CACHE_DIR", str(tmp_path))
    return tmp_path


def _write(instance, aid, data=b"BLENDER-fake"):
    d = paths.staging_dir(instance)
    p = os.path.join(d, f"{aid}.blend")
    with open(p, "wb") as f:
        f.write(data)
    return p, hashlib.sha256(data).hexdigest()


def test_id_validation_refuses_paths(cache):
    for bad in ("../x", "abc", "0" * 36, "../../etc/passwd", None, 5):
        assert not artifacts.is_artifact_id(bad)
        with pytest.raises(artifacts.ArtifactError) as exc:
            artifacts.resolve("inst", bad)
        assert exc.value.error_type == "artifact_missing"
    with pytest.raises(ValueError):
        paths.staging_dir("../escape")


def test_resolve_checks_existence_hash_and_size(cache):
    aid = str(uuid.uuid4())
    with pytest.raises(artifacts.ArtifactError) as exc:
        artifacts.resolve("inst", aid)
    assert exc.value.error_type == "artifact_missing"
    path, digest = _write("inst", aid)
    assert artifacts.resolve("inst", aid) == path
    assert artifacts.resolve("inst", aid, expected_hash=digest) == path
    with pytest.raises(artifacts.ArtifactError) as exc:
        artifacts.resolve("inst", aid, expected_hash="0" * 64)
    assert exc.value.error_type == "hash_mismatch"
    with pytest.raises(artifacts.ArtifactError) as exc:
        artifacts.resolve("inst", aid, max_bytes=4)
    assert exc.value.error_type == "artifact_missing"


def test_list_and_cleanup_keep_referenced(cache):
    old, new = str(uuid.uuid4()), str(uuid.uuid4())
    p_old, _ = _write("inst", old)
    _write("inst", new)
    stale = time.time() - 10 * 86400
    os.utime(p_old, (stale, stale))
    ids = [a["artifact_id"] for a in artifacts.list_artifacts("inst")]
    assert set(ids) == {old, new}
    assert artifacts.cleanup("inst", keep_ids={old}) == 0
    assert artifacts.cleanup("inst") == 1
    assert [a["artifact_id"] for a in artifacts.list_artifacts("inst")] == [new]
    assert artifacts.list_artifacts("never") == []
