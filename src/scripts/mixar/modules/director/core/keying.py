# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The one place a Director camera pose becomes keyframes.

Every keyed pose — a captured beat, a re-keyed beat, a recorded take frame —
writes the SAME three channels into the same group, because a beat and the
native keys under it are one thing. The Speed retime moves a beat by
finding the keys sitting on its frame (`core/timeline.py`,
`_director_keyframes`), so a beat whose pose is only partly keyed is a beat
that comes apart the first time it is retimed: the channels that had keys
move and the ones that did not stay behind.

That coupling is also why Blender's three keying preferences are deliberately
NOT honoured here. Each of them is right for Blender's model and wrong for
this one, and the reasons are recorded so the next reader does not "fix" it:

- **`key_insert_channels`** (the user's default channels) — a Director beat
  is a camera POSE. Dropping rotation because a user's preference excludes it
  leaves a beat that cannot describe a shot and cannot be retimed.
- **`use_auto_keyframe_insert_needed` / `use_keyframe_insert_needed`** — this
  skips per CHANNEL, so a camera that moved in X only would key location and
  not rotation, and the beat would split on the next retime. Director's
  analogue is coarser and lives in `core/auto_key.py`: it compares the whole
  POSE against the one it last keyed and declines to capture the beat at all,
  which is the same intent at the granularity this model can hold. A recorded
  take additionally has to key a held pose (`core/record.py`), since a gap in
  a performance curve is the camera drifting.
- **`use_visual_keying`** — it bakes a constraint's result into the channel.
  `core/tracking.py` aims a tracked camera with a Track To constraint and
  states the opposite contract on purpose: the captured rotation keys stay
  underneath it, so clearing the target returns the take to its keyed
  framing. Visual keying would freeze the camera at whatever it was last
  aimed at.
"""

from __future__ import annotations

from .rotation_curves import rotation_data_path

#: Every Director key lands in one action group, so a director scanning the
#: Dope Sheet sees the shot's channels together and apart from their own.
KEY_GROUP = "Director"


def key_camera_pose(camera, frame: int, *, keytype: str = 'KEYFRAME') -> None:
    """Key the pose a beat or a recorded frame is made of.

    Location, rotation in whatever mode the camera is in, and the lens —
    the lens because a focal length IS the framing, and a take that keys
    where the camera stood without keying what it saw is half a shot.
    """
    camera.keyframe_insert(data_path="location", frame=frame, group=KEY_GROUP, keytype=keytype)
    camera.keyframe_insert(
        data_path=rotation_data_path(camera), frame=frame, group=KEY_GROUP, keytype=keytype
    )
    camera.data.keyframe_insert(data_path="lens", frame=frame, group=KEY_GROUP, keytype=keytype)
