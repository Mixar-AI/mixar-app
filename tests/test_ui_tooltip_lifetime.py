# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`uiBut::tip` is a NON-OWNING `blender::StringRef`.

`ui_def_but` stores it by reference (`but->tip = tip.value_or("")`), so a
tooltip built from an `EnumPropertyItem` array the caller then `MEM_freeN`s,
or from a local buffer, leaves the button pointing at dead memory. That is a
use-after-free, an undefined tooltip on hover, and — because the QA
introspection dump serializes every button's tip — freed bytes in
`wm.mixar_qa_ui_dump`, which broke the harness outright (`snapshot()`,
`snap`, semantic `click` and `drag` all raised `UnicodeDecodeError`).

A string LITERAL is fine and needs no help. Anything computed must go through
an owned-tooltip helper built on `UI_but_func_tooltip_set`, which owns its
argument and frees it with the button.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/source/blender/editors"
ISLAND = ROOT / "space_agent_bubble"
PANE_KIT_CC = (ISLAND / "agent_ui_pane_kit.cc").read_text()

SCANNED = sorted(ISLAND.glob("*.cc")) + [
    ROOT / "space_view3d" / name
    for name in (
        "view3d_director_popup_render.cc",
        "view3d_director_cinema_dock.cc",
        "view3d_director_cinema_paint.cc",
        "view3d_director_cinema_left.cc",
        "view3d_director_cinema_right.cc",
    )
]

# Shapes that are, by construction, not static storage: an entry of an
# EnumPropertyItem array (freed by the caller) or a field of a local struct
# array built during the draw.
DANGLING = re.compile(r"\bitems\[|\.label\b|\.description\b|\.name\b")

CALL = re.compile(r"\buiDef\w*But\w*\s*\(")


def _last_arg(source: str, open_paren: int) -> str:
    depth = 0
    for j in range(open_paren, len(source)):
        if source[j] == "(":
            depth += 1
        elif source[j] == ")":
            depth -= 1
            if depth == 0:
                break
    inner, depth, args, cur = source[open_paren + 1 : j], 0, [], ""
    for ch in inner:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            args.append(cur)
            cur = ""
        else:
            cur += ch
    args.append(cur)
    return re.sub(r"\s+", " ", args[-1]).strip()


def test_no_button_is_given_a_tooltip_that_dies_before_it_does():
    offenders = []
    for path in SCANNED:
        source = path.read_text()
        # Identifiers declared as a local char buffer anywhere in this file:
        # passing one as a tooltip dangles the moment the draw returns.
        local_buffers = set(re.findall(r"\bchar\s+(\w+)\s*\[", source))
        for match in CALL.finditer(source):
            arg = _last_arg(source, match.end() - 1)
            if arg.startswith('"') or arg in ("nullptr", "NULL", '""'):
                continue
            if DANGLING.search(arg) or arg in local_buffers:
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line} tooltip={arg}")
    assert not offenders, (
        "tooltip argument points at memory that dies before the button; "
        "pass nullptr and use the owned-tooltip helper instead:\n  "
        + "\n  ".join(offenders)
    )


def test_the_owned_tooltip_helper_actually_owns_its_string():
    """A copy plus `MEM_freeN` as the free func — anything else re-introduces
    the dangling reference in a new disguise."""
    body = PANE_KIT_CC[PANE_KIT_CC.index("void pane_but_tooltip_owned") :]
    body = body[: body.index("\n}\n")]
    assert "MEM_mallocN" in body
    assert "memcpy" in body
    assert "UI_but_func_tooltip_set" in body
    assert "MEM_freeN" in body


def test_the_panes_use_it_where_their_labels_are_dynamic():
    for name in ("agent_ui_tab3d_params.cc", "agent_ui_tabsplat.cc", "agent_ui_tabmedia.cc"):
        assert "pane_but_tooltip_owned(" in (ISLAND / name).read_text(), name


def test_the_qa_dump_is_not_filtered_on_block_active():
    """`block->active` means "rebuilt during the current free-inactive pass",
    NOT "on screen": every region that is not mid-redraw carries live blocks
    with it clear. Filtering on it dropped ~95% of the UI from the dump —
    measured at 11 widgets, with the whole topbar and island missing."""
    source = (ROOT / "interface" / "interface_qa_inspect.cc").read_text(encoding="utf-8")
    walk = source[source.index("for (const blender::ui::Block &block : region->runtime->uiblocks)") :][:900]
    assert "if (!block.active)" not in walk
    assert "if (!block->active)" not in walk
