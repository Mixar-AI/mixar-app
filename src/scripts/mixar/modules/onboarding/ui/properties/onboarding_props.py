# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding WindowManager Properties

Two session-scoped flags that drive the state machine:

* ``mixar_onboarding_step`` — current step ID (a string matching one
  of the constants in ``constants.py``). A StringProperty rather than
  an EnumProperty so we don't have to resync the enum items every time
  a step is added.
* ``mixar_onboarding_opted_out`` — True once the user has hit
  "Skip tour" or "I'll figure it out myself"; cleared on Blender
  restart or when Help → Welcome explicitly resets state.

These live on ``bpy.types.WindowManager`` precisely because that data
block is reset between Blender sessions. ``Scene`` would persist with
the .blend file (wrong for an onboarding flag); a Python singleton
would not survive script reloads.
"""

import bpy

from mixar.modules.onboarding.constants import (
    DEFAULT_STEP,
    WM_PROP_OPTED_OUT,
    WM_PROP_STEP,
)


def register():
    setattr(
        bpy.types.WindowManager,
        WM_PROP_STEP,
        bpy.props.StringProperty(
            name="Mixar Onboarding Step",
            description="Current step ID in the onboarding flow",
            # Default is an empty string, NOT ``DEFAULT_STEP``: the
            # dim film's ``_onboarding_is_active()`` reads this raw
            # value and treats an empty string as "tour not running"
            # so the screen isn't dimmed by default. ``state.begin()``
            # explicitly sets ``DEFAULT_STEP`` (= ``STEP_WELCOME``)
            # when the tour actually starts. Other readers go
            # through ``state.get_step_id()`` which falls back to
            # ``DEFAULT_STEP`` if the WM value is empty, so the
            # state machine continues to behave the same.
            default="",
            options={"SKIP_SAVE"},
        ),
    )
    setattr(
        bpy.types.WindowManager,
        WM_PROP_OPTED_OUT,
        bpy.props.BoolProperty(
            name="Mixar Onboarding Opted Out",
            description=(
                "True once the user has skipped the onboarding flow this "
                "session; cleared on restart or explicit reopen."
            ),
            default=False,
            options={"SKIP_SAVE"},
        ),
    )


def unregister():
    for attr in (WM_PROP_STEP, WM_PROP_OPTED_OUT):
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)
