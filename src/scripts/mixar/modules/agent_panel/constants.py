# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parallel Agents panel constants.

The panel is drawn in C++ (``view3d_agent_panel_*.cc``), which reads the
WindowManager card mirror this module's ``core/cards.py`` maintains. Every
string maxlen here is paired with a strictly larger C++ stack buffer
(``AGENT_PANEL_*_BUF`` in ``view3d_agent_panel.hh``) — ``StringProperty``
registers maxlength ``maxlen + 1``, so a buffer of exactly ``maxlen`` bytes
is an off-by-one on read.
"""

#: Agent display name ("Back window", derived from the task label).
AGENT_NAME_MAXLEN = 96
#: The full task label the agent was given.
AGENT_TASK_MAXLEN = 256
#: Backend task id — the identity the diff-update matches on.
AGENT_TASK_ID_MAXLEN = 64

#: Below this many tasks the turn is not a parallel fan-out and the panel
#: stays closed: one task is just the chat's own todo line repeated.
MIN_CARDS_FOR_PANEL = 2

#: Cards visible before the stack scrolls (the reference design's three).
VISIBLE_CARDS = 3

#: Longest agent name we derive from a task label before eliding.
AGENT_NAME_TARGET_CHARS = 34

#: How long a finished card stays on screen before it slides out, and how long
#: the slide takes. A completed agent has nothing left to say, so its card
#: leaves rather than accumulating over the viewport — but not so fast that the
#: check mark never registers.
#:
#: **These are duplicated in `view3d_agent_panel.hh` and must agree.** Python
#: owns WHEN the card is removed from the mirror; C++ owns the animation, timed
#: from its own first sighting of the DONE status. If the C++ half outlasts the
#: Python half the card vanishes mid-slide. Pinned by
#: `tests/agent_panel/test_agent_panel_contracts.py`.
DONE_CARD_DWELL_S = 1.2
DONE_CARD_EXIT_S = 0.35

#: A card that FAILED never slides out on its own — a failure is the one thing
#: on this surface the user may still need to act on.
