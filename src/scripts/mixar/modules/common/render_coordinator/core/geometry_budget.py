# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared Cycles allocation protection for inspection and delivered renders."""


def downgrade_over_budget(scene, set_value, max_faces, eevee='BLENDER_EEVEE'):
    if max_faces <= 0 or str(scene.render.engine) != 'CYCLES':
        return None
    from mixar.modules.common.agent_execution.scene_cost import scene_geometry_cost
    faces = scene_geometry_cost(scene)['unique_faces']
    if faces <= max_faces:
        return None
    set_value(scene.render, 'engine', eevee)
    return {'from': 'CYCLES', 'to': eevee,
            'reason': f'{faces} unique faces over the {max_faces}-face budget for this machine'}
