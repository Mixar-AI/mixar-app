# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

from types import SimpleNamespace

import pytest

from mixar.modules.project_versioning.core.models import (
    ProjectRecord,
    RemoteConflict,
    RemoteHeads,
    RemoteSession,
)
from mixar.modules.project_versioning.core.sdk_adapter import (
    LoreRemoteConflict,
    LoreSdkAdapter,
)


class Args:
    def __init__(self, **values):
        self.__dict__.update(values)


class PushEvent:
    def __init__(self, revision: bytes):
        self.local_revision = revision


class SyncEvent:
    def __init__(self, revision: bytes, *, merge=False, conflict=False):
        self.revision = revision
        self.flag_merge = merge
        self.flag_conflict = conflict


class Executor:
    def __init__(self, events):
        self.events = events

    def collect(self):
        return self.events


def _project(tmp_path):
    return ProjectRecord(
        "project", "repository", "identity", str(tmp_path),
        str(tmp_path / "scene.blend"), "main",
    )


def _session():
    return RemoteSession(
        repository_url="lore://example.test/project",
        auth_url="https://auth.example.test",
        token="short-lived-token",
    )


def _adapter(fake_lore):
    adapter = LoreSdkAdapter()
    adapter._loaded = True
    adapter._lore = fake_lore
    adapter._types = {
        "global": Args,
        "auth_login": Args,
        "branch_push": Args,
        "sync": Args,
        "push_event": PushEvent,
        "sync_event": SyncEvent,
    }
    return adapter


def test_authenticate_uses_direct_lore_token_without_exchange_url(tmp_path) -> None:
    calls = []

    class Lore:
        @staticmethod
        def auth_login_with_token(globals_, args):
            calls.append((globals_, args))
            return Executor([])

    adapter = _adapter(Lore)
    session = RemoteSession(
        repository_url="lore://project.example:41337/projects/a",
        token="short-lived-token",
    )
    adapter.authenticate(str(tmp_path), session)

    assert calls[0][1].remote_url == session.repository_url
    assert calls[0][1].token == "short-lived-token"
    assert calls[0][1].token_type == "lore"
    assert calls[0][1].auth_url == ""


def test_push_disables_implicit_fast_forward_merge(tmp_path) -> None:
    calls = []

    class Lore:
        @staticmethod
        def branch_push(globals_, args):
            calls.append(args)
            return Executor([PushEvent(bytes.fromhex("ab" * 32))])

    adapter = _adapter(Lore)
    adapter.remote_heads = lambda *args, **kwargs: RemoteHeads(
        "main", "aa", "aa", True, False
    )

    outcome = adapter.push(_project(tmp_path), _session(), branch="main")

    assert outcome.changed is True
    assert outcome.revision == "ab" * 32
    assert calls[0].branch == "main"
    assert calls[0].fast_forward_merge is False


def test_push_rejects_a_stale_remote_before_writing(tmp_path) -> None:
    lore = SimpleNamespace(branch_push=lambda *args: pytest.fail("must not push"))
    adapter = _adapter(lore)
    adapter.remote_heads = lambda *args, **kwargs: RemoteHeads(
        "main", "aa", "bb", False, True
    )

    with pytest.raises(LoreRemoteConflict) as raised:
        adapter.push(_project(tmp_path), _session(), branch="main")

    assert raised.value.reason == RemoteConflict.STALE_REMOTE_HEAD


def test_sync_pins_observed_remote_revision_without_merge_or_reset(tmp_path) -> None:
    calls = []

    class Lore:
        @staticmethod
        def revision_sync(globals_, args):
            calls.append(args)
            return Executor([SyncEvent(bytes.fromhex("cd" * 32))])

    adapter = _adapter(Lore)
    adapter.remote_heads = lambda *args, **kwargs: RemoteHeads(
        "main", "aa", "cd" * 32, False, True
    )

    outcome = adapter.sync(_project(tmp_path), _session(), branch="main")

    assert outcome.changed is True
    assert outcome.revision == "cd" * 32
    assert calls[0].revision == "cd" * 32
    assert calls[0].forward_changes is False
    assert calls[0].reset is False
