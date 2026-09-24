# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — overlay painters.

Everything here is ``gpu``/``blf`` only. Every function takes WINDOW pixel
coordinates (bottom-left origin); the draw callback that calls them has
already translated the matrix by ``(-region.x, -region.y)``, so no painter
touches regions, ``bpy`` state or properties.

* ``cursor``      — the fake pointer: glide, orbit, click pulse, fades.
* ``scribble``    — hand-drawn ring + starburst marks, hint pills, dim film.
* ``card``        — the video card, its hover-revealed controls, hit testing, QA targets.
* ``exit_dialog`` — the "Leave the tour?" confirmation.
* ``text``        — blf measurement/drawing that survives the test mocks.
"""
