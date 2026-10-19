# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene lights for a ``game`` glTF export (game contract v1.4 §3).

When the game spec asks for the scene's own lights (``scene_lights``), the
lights named in the lane spec travel as ``KHR_lights_punctual``. glTF has
point, spot and sun lights only, and agent-built arenas are lit with AREA
lights, which the exporter would drop. ``staged_game_lights`` therefore
stands in a temporary SPOT for each area light, for the export only:

- same parent and world transform, so it points the way the area light faces
  (both emit along the object's local -Z);
- same colour and power (W). The fork normalizes imported light energy;
- a 120° cone with a 0.5 blend, approximating an area light's soft
  hemisphere. KHR spots cap the half-angle at 90°.

Each stand-in is named ``<area name>_spot``. The stand-ins and their light
data are removed on exit, and the area lights themselves are never changed.
Cameras stay out. Main thread only.
"""

from __future__ import annotations

from contextlib import contextmanager

import bpy

PUNCTUAL = ("POINT", "SPOT", "SUN")
AREA_SPOT_SIZE = 2.0944  # 120°
AREA_SPOT_BLEND = 0.5


@contextmanager
def staged_game_lights(names, scene):
    """Yields ``(light_objects, counts)``. ``light_objects`` are the
    punctual lights named in ``names`` plus the spot stand-ins for the named
    area lights; ``counts`` is ``{"lights", "from_area", "by_type"}``."""
    by_name = {obj.name: obj for obj in getattr(scene, "objects", ()) or ()}
    lights = [by_name[n] for n in names or () if getattr(by_name.get(n), "type", "") == 'LIGHT']
    staged, temps, by_type, from_area = [], [], {}, 0
    try:
        for obj in lights:
            kind = obj.data.type
            if kind in PUNCTUAL:
                staged.append(obj)
                by_type[kind] = by_type.get(kind, 0) + 1
                continue
            if kind != 'AREA':
                continue
            data = bpy.data.lights.new(f"{obj.data.name}_spot", 'SPOT')
            temp = bpy.data.objects.new(f"{obj.name}_spot", data)
            temps.append((temp, data))
            data.color, data.energy = tuple(obj.data.color), obj.data.energy
            data.spot_size, data.spot_blend = AREA_SPOT_SIZE, AREA_SPOT_BLEND
            data.use_shadow = obj.data.use_shadow
            scene.collection.objects.link(temp)
            temp.parent = obj.parent
            temp.matrix_world = obj.matrix_world.copy()
            staged.append(temp)
            from_area += 1
            by_type["SPOT"] = by_type.get("SPOT", 0) + 1
        yield staged, {"lights": len(staged), "from_area": from_area, "by_type": by_type}
    finally:
        for temp, data in temps:
            try:
                bpy.data.objects.remove(temp, do_unlink=True)
            except Exception:
                pass
            try:
                bpy.data.lights.remove(data)
            except Exception:
                pass
