# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Every chat attachment also lands on the moodboard.

``bpy`` is a MagicMock in this suite, so operator ``execute()`` bodies cannot
be driven end to end (see the root ``conftest.py``). These are source-level
contracts pinning that each attachment-creating path calls the shared
mirroring helper, and that the helper keeps the invariants that stop the
mirror from fighting the reverse ``moodboard.core.chat_sync`` sync.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"

BRIDGE = CHAT / "core/attachment_board_sync.py"

# Every module that appends to ``scene.mixie_chat_pending_attachments``.
# ``moodboard/core/chat_sync.py`` is deliberately absent: it mirrors the board
# INTO the composer, so its images are on the board already.
ATTACHMENT_WRITERS = (
    CHAT / "ui/operators/image_ops.py",
    CHAT / "ui/operators/clipboard_ops.py",
    CHAT / "ui/operators/screenshot_ops.py",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_every_attachment_writer_mirrors_to_the_moodboard():
    for path in ATTACHMENT_WRITERS:
        source = _read(path)
        assert "mirror_attachment_to_moodboard" in source, path


def test_each_attachment_add_site_is_covered():
    """One mirror call per ``attachments.add()`` / ``pending.add()`` site."""
    expected = {
        # file picker + blend-data picker
        CHAT / "ui/operators/image_ops.py": 2,
        # clipboard paste
        CHAT / "ui/operators/clipboard_ops.py": 1,
        # viewport capture + region snip
        CHAT / "ui/operators/screenshot_ops.py": 2,
    }
    for path, count in expected.items():
        source = _read(path)
        # Subtract the import line itself.
        calls = source.count("mirror_attachment_to_moodboard(")
        assert calls == count, f"{path}: {calls} mirror calls, expected {count}"


def test_boarded_attachments_are_not_selected():
    """A selected board item is mirrored straight back into the composer by
    ``chat_sync``, which would show a second pill for the same image."""
    bridge = _read(BRIDGE)

    assert "selected=False" in bridge
    assert "selected=True" not in bridge


def test_moodboard_origin_attachments_are_skipped():
    bridge = _read(BRIDGE)

    assert 'getattr(attachment, "is_moodboard", False)' in bridge


def test_mirroring_never_blocks_the_attach():
    """The attach is what the user asked for; boarding is best-effort."""
    bridge = _read(BRIDGE)

    assert "except Exception:" in bridge
    assert "return False" in bridge


def test_the_bridge_reuses_the_moodboards_own_import_path():
    """No second definition of "put a media file on the board"."""
    bridge = _read(BRIDGE)
    media_import = _read(MOODBOARD / "core/media_import.py")

    assert "load_media_file_to_board" in bridge
    assert "def load_media_file_to_board(" in media_import
    assert "add_packed_image_to_board" in bridge
    # Packing keeps a temp-dir paste/screenshot valid after a save + reload.
    assert "img.pack()" in media_import


def test_the_bridge_dedupes_against_the_existing_board():
    bridge = _read(BRIDGE)

    assert "_find_on_board" in bridge
    assert "is not None:\n        return None" in bridge
