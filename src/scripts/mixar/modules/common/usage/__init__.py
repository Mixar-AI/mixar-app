# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Credit/quota figures behind the top-bar account card.

``core.state`` holds the cached billing snapshot (pure Python — no
``bpy`` — so the percentage and threshold logic is unit-testable),
``core.poller`` decides when to refresh it and mirrors it onto
WindowManager RNA, ``core.account`` derives the greeting name, and
``ui/`` owns the mirrored properties plus the card's CTA operators.

The card itself is drawn natively (``interface_mixar_profile_card.cc``)
inside ``MIXAR_PT_profile``; RNA is the only channel between this module
and that drawing, because C++ cannot read a Python module cache.
"""
