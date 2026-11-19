# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins `src/source/blender/makesrna/intern/rna_wm_api.cc`, upstream's file plus
the hunk fenced by `/* MIXAR-2062 begin */ ... /* MIXAR-2062 end */`
(mixar-backend#2062).

`WindowManager.popup_menu`, `popover` and `popup_menu_pie` crashed the app
with bad_access in `ui::popup_menu_end` (or `popup_block_create` from
`ui::popover_end`) when the context window had no event state. Windows of a
`--background` process (the prod crash was a user's `-b --python` script;
the headless agent worker runs the same way) have no GHOST window, so `win->runtime->eventstate` is never allocated, and upstream's begin
wrappers only checked that a window exists. `rna_popup_context_ok_or_report`
now also refuses a window without event state, so begin raises `RuntimeError`
before anything is allocated and the Python helper never reaches end.

Delete the overlay once upstream checks the event state itself."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "source/blender/makesrna/intern/rna_wm_api.cc"
OVERLAY = ROOT / "src" / RELATIVE
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_CANDIDATES = (
    ROOT / "upstream" / RELATIVE,
    ROOT.parents[1] / "upstream" / RELATIVE,
)
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
MARKED = re.compile(r"[ \t]*/\* MIXAR-2062 begin \*/\n.*?[ \t]*/\* MIXAR-2062 end \*/\n", re.S)
CHECK = "rna_popup_context_ok_or_report(C, reports)"
BEGIN_WRAPPERS = {
    "rna_PopMenuBegin": "ui::popup_menu_begin(",
    "rna_PopoverBegin": "ui::popover_begin(",
    "rna_PieMenuBegin": "ui::pie_menu_begin(",
}


def _strip_comments(text: str) -> str:
    return re.sub(r"[ \t]*/\*.*?\*/\n?", "", text, flags=re.S)


def _function(text: str, name: str) -> str:
    start = text.index(f" {name}(")
    start = text.rindex("\n", 0, start) + 1
    return text[start:text.index("\n}\n", start) + 3]


def _overlay_function(name: str) -> str:
    return _strip_comments(_function(OVERLAY.read_text(encoding="utf-8"), name))


def _ordered(text: str, *parts: str) -> bool:
    """Each part occurs after the previous one (repeated parts are matched in turn)."""
    cursor = 0
    for part in parts:
        found = text.find(part, cursor)
        if found == -1:
            return False
        cursor = found + len(part)
    return True


def test_popup_check_refuses_a_window_without_event_state():
    body = _overlay_function("rna_popup_context_ok_or_report")
    assert _ordered(
        body,
        "if (CTX_wm_window(C) == nullptr) {",
        "return false;",
        "if (CTX_wm_window(C)->runtime->eventstate == nullptr) {",
        "BKE_report(reports,",
        "RPT_ERROR,",
        "has no event state",
        "return false;\n  }\n  return true;\n}",
    )


@pytest.mark.parametrize("name", sorted(BEGIN_WRAPPERS))
def test_every_begin_wrapper_checks_the_context_before_creating_a_popup(name):
    body = _overlay_function(name)
    assert body.count(CHECK) == 1
    assert _ordered(body, f"if (!{CHECK}) {{\n    return PointerRNA_NULL;\n  }}", BEGIN_WRAPPERS[name])


def test_the_overlay_is_upstream_plus_the_marked_hunk():
    """Keep the change fenced so an upstream bump is a re-copy plus re-apply."""
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        pytest.skip("upstream submodule not checked out")
    up = upstream.read_text(encoding="utf-8")
    if "eventstate" in _function(up, "rna_popup_context_ok_or_report"):
        pytest.fail(
            "upstream rna_popup_context_ok_or_report now checks the window's event state "
            "(mixar-backend#2062): delete the rna_wm_api.cc overlay and its CLAUDE.md entry",
            pytrace=False,
        )
    ov = OVERLAY.read_text(encoding="utf-8")
    assert ov.count("/* MIXAR-2062 begin */") == ov.count("/* MIXAR-2062 end */") == 1
    assert MIXAR_SPDX in ov
    unpatched = MARKED.sub("", ov.replace(MIXAR_SPDX, "", 1))
    if unpatched != up:
        old, new = unpatched.splitlines(), up.splitlines()
        line = next((i for i, pair in enumerate(zip(old, new)) if pair[0] != pair[1]), min(len(old), len(new)))
        pytest.fail(
            "upstream rna_wm_api.cc changed (first difference at upstream line "
            f"{line + 1}), or an overlay edit is not fenced: re-copy the upstream file and "
            "re-apply the MIXAR-2062 hunk (or delete the overlay if upstream now checks "
            "the window's event state)",
            pytrace=False,
        )
