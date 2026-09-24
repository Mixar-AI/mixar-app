# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every acquired `ImBuf` is handed back to `BKE_image_release_ibuf`.

`BKE_image_acquire_ibuf` takes a REFERENCE on the buffer it returns.
`BKE_image_release_ibuf(image, ibuf, lock)` drops that reference only when its
`ibuf` argument is non-null -- pass `nullptr` and the lock is released while the
reference leaks, silently, once per call.

`mixie_moodboard_ops_preview_window.cc` did exactly that: it acquired the buffer
inside an `if` condition, so the pointer was out of scope by the time the release
ran, and every media preview the user opened leaked one buffer. It was the only
one of ~20 call sites in the directory that passed anything but the acquired
buffer, which is what makes this cheap to pin.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"

# `BKE_image_release_ibuf(image, <second arg>, lock)` -- capture the second arg.
RELEASE = re.compile(r"BKE_image_release_ibuf\s*\(\s*[^,]+,\s*([^,]+?)\s*,")


def _sources():
    return sorted(SPACE_MIXIE.glob("*.cc"))


def test_no_release_call_discards_the_buffer():
    offenders = []
    for path in _sources():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for handed_back in RELEASE.findall(line):
                if handed_back.strip() in {"nullptr", "NULL", "0"}:
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == [], (
        "BKE_image_release_ibuf must be handed the buffer that "
        "BKE_image_acquire_ibuf returned, or its reference leaks:\n  "
        + "\n  ".join(offenders)
    )


def test_the_preview_window_still_releases_what_it_acquired():
    """The regression's own file, pinned by name: it must acquire into a
    variable that outlives the size check, then release THAT."""
    source = (SPACE_MIXIE / "mixie_moodboard_ops_preview_window.cc").read_text(
        encoding="utf-8"
    )
    assert "ImBuf *ibuf = BKE_image_acquire_ibuf(" in source, (
        "the buffer must be acquired into a variable, not an `if` condition "
        "whose scope ends before the release"
    )
    assert "BKE_image_release_ibuf(image, ibuf, lock);" in source


def test_every_acquire_in_this_directory_has_a_release():
    """A file that acquires and never releases is the same leak, one step out."""
    missing = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        if "BKE_image_acquire_ibuf" in text and "BKE_image_release_ibuf" not in text:
            missing.append(path.name)
    assert missing == [], f"acquires an ImBuf and never releases it: {missing}"
