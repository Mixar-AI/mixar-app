# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The checkpoint disk budget ACROSS sessions.

Per-session pruning bounds one chat at 20 snapshots, but nothing retired a
session directory, and every snapshot is a whole document -- so a few dozen
chats multiplied into tens of gigabytes in a folder the user never sees."""

import os

def _age(path, days):
    old = os.path.getmtime(path) - days * 86400.0
    for root, _dirs, files in os.walk(path):
        for name in files:
            os.utime(os.path.join(root, name), (old, old))
    os.utime(path, (old, old))


def test_stale_session_directories_are_retired(tc, monkeypatch):
    """Per-session pruning bounded ONE chat at 20 snapshots; nothing ever
    retired a session directory, and each snapshot is a whole document."""
    root = tc.m.checkpoints_root()
    for name in ("old-a", "old-b", "fresh"):
        d = tc.m.session_dir(name)
        with open(os.path.join(d, "x.mixar"), "w") as f:
            f.write("blend")
    _age(os.path.join(root, "old-a"), tc.m.MAX_AGE_DAYS + 1)
    _age(os.path.join(root, "old-b"), tc.m.MAX_AGE_DAYS + 1)

    assert tc.m.prune_sessions("live") == 2
    assert sorted(os.listdir(root)) == ["fresh"]


def test_the_live_session_is_never_retired(tc, monkeypatch):
    root = tc.m.checkpoints_root()
    d = tc.m.session_dir("live")
    with open(os.path.join(d, "x.mixar"), "w") as f:
        f.write("blend")
    _age(d, tc.m.MAX_AGE_DAYS + 5)

    assert tc.m.prune_sessions("live") == 0
    assert os.listdir(root) == ["live"]


def test_session_directories_are_capped_by_count_too(tc, monkeypatch):
    """Age alone does not bound the multiplication: a burst of chats in one
    week is exactly the case that fills the disk."""
    monkeypatch.setattr(tc.m, "MAX_SESSIONS", 3)
    root = tc.m.checkpoints_root()
    for i in range(6):
        d = tc.m.session_dir(f"chat-{i}")
        with open(os.path.join(d, "x.mixar"), "w") as f:
            f.write("blend")
        _age(d, 6 - i)          # chat-0 oldest, chat-5 newest

    removed = tc.m.prune_sessions("live")
    survivors = sorted(os.listdir(root))
    assert len(survivors) == 3 and removed == 3
    assert survivors == ["chat-3", "chat-4", "chat-5"]


def test_the_session_prune_runs_at_most_once_a_day(tc, monkeypatch):
    calls = []
    monkeypatch.setattr(tc.m, "prune_sessions", lambda keep="": calls.append(keep))
    tc.m._last_cleanup_day = -1
    tc.m._prune_sessions_once_per_day("sess-1")
    tc.m._prune_sessions_once_per_day("sess-1")
    assert calls == ["sess-1"]


def test_a_failing_session_prune_never_blocks_a_capture(tc, monkeypatch):
    def boom(keep=""):
        raise OSError("disk gone")
    monkeypatch.setattr(tc.m, "prune_sessions", boom)
    tc.m._last_cleanup_day = -1
    tc.m._prune_sessions_once_per_day("sess-1")     # must not raise


def test_the_open_document_is_never_retired_by_age(tc):
    """Older builds parked a restored UNTITLED project at <session>/working.mixar
    and that became bpy.data.filepath -- with the session id cleared, so
    `keep_session_id` stopped protecting the directory. Such a document may
    still be open somewhere; retiring its directory would delete it."""
    root = tc.m.checkpoints_root()
    live = tc.m.session_dir("orphaned")
    document = os.path.join(live, "working.mixar")
    with open(document, "w") as f:
        f.write("blend")
    tc.bpy.data.filepath = document
    _age(live, tc.m.MAX_AGE_DAYS + 30)

    assert tc.m.prune_sessions("some-other-session") == 0
    assert os.listdir(root) == ["orphaned"] and os.path.exists(document)


def test_the_open_document_is_never_retired_by_the_count_cap(tc, monkeypatch):
    """The age cutoff is not the only way in: the count cap retires by mtime
    rank, and a document nobody has saved for a while ranks last."""
    monkeypatch.setattr(tc.m, "MAX_SESSIONS", 2)
    root = tc.m.checkpoints_root()
    live = tc.m.session_dir("orphaned")
    document = os.path.join(live, "working.mixar")
    with open(document, "w") as f:
        f.write("blend")
    tc.bpy.data.filepath = document
    _age(live, 30)                      # oldest by mtime: last in line
    for i in range(4):
        d = tc.m.session_dir(f"chat-{i}")
        with open(os.path.join(d, "x.mixar"), "w") as f:
            f.write("blend")
        _age(d, 4 - i)                  # chat-0 oldest, chat-3 newest

    tc.m.prune_sessions("some-other-session")

    assert sorted(os.listdir(root)) == ["chat-3", "orphaned"]
    assert os.path.exists(document)


def test_a_document_outside_the_checkpoint_root_protects_nothing(tc):
    """A titled project keeps its own path, so the exemption must not fire and
    silently spare a stale directory that happens to sort first."""
    root = tc.m.checkpoints_root()
    d = tc.m.session_dir("stale")
    with open(os.path.join(d, "x.mixar"), "w") as f:
        f.write("blend")
    _age(d, tc.m.MAX_AGE_DAYS + 1)      # tc.bpy.data.filepath is the real .mixar

    assert tc.m.prune_sessions("live") == 1
    assert os.listdir(root) == []
