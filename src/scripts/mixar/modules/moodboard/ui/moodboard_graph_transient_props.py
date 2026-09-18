# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene state the node canvas uses only while the user is mid-gesture.

Split out of ``moodboard_scene_registration.py`` (500-line rule). These differ
from the rest of the moodboard's scene data in kind, not just in file: every one
is ``SKIP_SAVE`` because it describes an interaction in flight -- where a noodle
was dropped, why the last connection was refused -- and none of it belongs in a
saved .blend or on the wire.

Registered through the caller's guarded ``_safe_scene_prop`` so a failure here
is reported and skipped rather than aborting the rest of the registration.
"""

from bpy.props import BoolProperty, FloatProperty, StringProperty

from mixar.modules.moodboard.constants import GRAPH_NOTICE_MAXLEN


def register_graph_transient_props(_safe_scene_prop) -> None:
    # Where a dragged noodle was released. The C++ graph modal sets these
    # before opening the continuation menu so the node the menu creates lands
    # under the cursor; every other entry point clears the flag, because the
    # output handle's own coordinates would spawn the node on its source.
    _safe_scene_prop(
        'mixie_moodboard_graph_notice',
        StringProperty(
            name="Graph Notice",
            description=(
                "Why the last connection was refused, shown briefly on the "
                "canvas beside the node it was aimed at. Cleared by a one-shot "
                "timer -- the status bar alone put the reason somewhere the "
                "user was not looking"
            ),
            default="",
            maxlen=GRAPH_NOTICE_MAXLEN,
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_moodboard_graph_notice_x',
        FloatProperty(name="Graph Notice X", default=0.0, options={'SKIP_SAVE'}),
    )
    _safe_scene_prop(
        'mixie_moodboard_graph_notice_y',
        FloatProperty(name="Graph Notice Y", default=0.0, options={'SKIP_SAVE'}),
    )
    _safe_scene_prop(
        'mixie_moodboard_link_drop_active',
        BoolProperty(
            name="Moodboard Link Drop Active",
            description="Whether a released link opened the continuation menu",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    for axis in ('x', 'y'):
        _safe_scene_prop(
            f'mixie_moodboard_link_drop_{axis}',
            FloatProperty(
                name=f"Moodboard Link Drop {axis.upper()}",
                description="Canvas position where the dragged link was released",
                default=0.0,
                options={'SKIP_SAVE'},
            ),
        )
