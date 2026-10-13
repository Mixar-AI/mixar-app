# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exact generated watch strap and six angled cutters, before the Boolean.

Replay fixture preserves the captured 220 x 48 grid and its winding defect.
"""
import math
import bpy
import bmesh
from mathutils import Vector


def build():
    root = bpy.data.objects.new('strap_Watch_Strap', None)
    bpy.context.scene.collection.objects.link(root)
    col = bpy.data.collections.new('strap_Watch_Strap')
    bpy.context.scene.collection.children.link(col)

    def mat(name, c, rough, metal=0):
        m = bpy.data.materials.new(name)
        m.diffuse_color = (*c, 1)
        m.use_nodes = True
        p = m.node_tree.nodes.get('Principled BSDF')
        p.inputs['Base Color'].default_value = (*c, 1)
        p.inputs['Roughness'].default_value = rough
        p.inputs['Metallic'].default_value = metal
        return m
    leather = mat('strap_Black_Alligator', (0.009, 0.011, 0.013), 0.34)
    n = leather.node_tree.nodes
    l = leather.node_tree.links
    p = n.get('Principled BSDF')
    tex = n.new('ShaderNodeTexNoise')
    tex.inputs['Scale'].default_value = 16000
    tex.inputs['Detail'].default_value = 3
    coord = n.new('ShaderNodeTexCoord')
    l.new(coord.outputs['Position'] if 'Position' in coord.outputs else coord.outputs['Object'], tex.inputs['Vector'])
    bump = n.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = 0.22
    bump.inputs['Distance'].default_value = 4.5e-05
    l.new(tex.outputs['Fac'], bump.inputs['Height'])
    l.new(bump.outputs['Normal'], p.inputs['Normal'])
    edge = mat('strap_Burnished_Black_Edges', (0.013, 0.014, 0.016), 0.42)
    thread = mat('strap_Charcoal_Waxed_Thread', (0.042, 0.044, 0.045), 0.63)
    lining = mat('strap_Black_Lining', (0.021, 0.018, 0.016), 0.68)
    steel = mat('strap_Polished_Steel', (0.65, 0.69, 0.73), 0.19, 1)

    def mesh(name, v, f, ma, loc=(0, 0, 0)):
        me = bpy.data.meshes.new(name)
        me.from_pydata(v, [], f)
        me.update()
        o = bpy.data.objects.new(name, me)
        col.objects.link(o)
        o.parent = root
        o.location = loc
        me.materials.append(ma)
        for p in me.polygons:
            p.use_smooth = True
        return o

    def path(t, sg):
        y = sg * (0.0255 * math.cos(t) + 0.043 * math.sin(t))
        z = 0.0045 - 0.03 * (1 - math.cos(t))
        dy = -0.0255 * math.sin(t) + 0.043 * math.cos(t)
        dz = -0.03 * math.sin(t)
        nn = math.hypot(dy, dz)
        return (Vector((0, y, z)), Vector((0, -sg * dz / nn, dy / nn)))

    def width(t):
        return 0.02 - 0.003 * min(t / 2.6, 1)

    def surf(t, u, sg, relief=True):
        c, no = path(t, sg)
        w = width(t)
        h = 0.00122 + 0.00048 * max(0, 1 - u * u) ** 1.8
        if relief:
            row = t / 0.245
            a = abs(math.sin(math.pi * (row + 0.035 * math.sin(u * 7 + row))))
            cross = (u + 1) * 1.6 + 0.13 * math.sin(row * 1.7) + 0.045 * math.sin(t * 34 + u * 9)
            b = abs(math.sin(math.pi * cross))
            h -= 0.00014 * math.exp(-(a / 0.065) ** 2) + 0.000115 * math.exp(-(b / 0.055) ** 2)
        return c + Vector((u * w / 2, 0, 0)) + no * h

    def curve(name, points, r, ma):
        cu = bpy.data.curves.new(name, 'CURVE')
        cu.dimensions = '3D'
        cu.resolution_u = 1
        cu.bevel_depth = r
        cu.bevel_resolution = 3
        sp = cu.splines.new('POLY')
        sp.points.add(len(points) - 1)
        center = Vector(points[0])
        for p, v in zip(sp.points, points):
            p.co = (*Vector(v) - center, 1)
        o = bpy.data.objects.new(name, cu)
        col.objects.link(o)
        o.location = center
        o.parent = root
        cu.materials.append(ma)
        return o
    for sg, label, end in [(1, 'Upper', 2.72), (-1, 'Lower', 2.93)]:
        N = 220
        M = 48
        v = []
        f = []
        for layer in [0, 1]:
            for i in range(N + 1):
                t = 0.037 + (end - 0.037) * i / N
                for j in range(M + 1):
                    u = -1 + 2 * j / M
                    c, no = path(t, sg)
                    p = surf(t, u, sg) if layer == 0 else c + Vector((u * width(t) / 2, 0, 0)) - no * 0.00125
                    v.append(tuple(p))
        stride = M + 1
        off = (N + 1) * stride
        for i in range(N):
            for j in range(M):
                a = i * stride + j
                f.append((a, a + 1, a + stride + 1, a + stride))
                a += off
                f.append((a + stride, a + stride + 1, a + 1, a))
        for i in range(N):
            for j in [0, M]:
                a = i * stride + j
                f.append((a, a + stride, a + stride + off, a + off))
        for i in [0, N]:
            for j in range(M):
                a = i * stride + j
                f.append((a, a + off, a + off + 1, a + 1))
        o = mesh('strap_' + label + '_Leather', v, f, leather)
        o.data.materials.append(lining)
        for poly in o.data.polygons:
            if poly.index % 2 == 1 and poly.index < N * M * 2:
                poly.material_index = 1
        for side in [-1, 1]:
            pts = [surf(0.037 + (end - 0.037) * i / 190, side, sg, False) - path(0.037 + (end - 0.037) * i / 190, sg)[1] * 0.00022 for i in range(191)]
            curve('strap_' + label + '_Edge_' + str(side), pts, 0.0002, edge)
            for k in range(82):
                t = 0.07 + (end - 0.13) * k / 82
                pts = [surf(t + d, side * 0.875, sg, False) + path(t + d, sg)[1] * (6e-05 + 2.5e-05 * math.sin(math.pi * j / 4)) for j, d in enumerate([0, 0.004, 0.008, 0.012, 0.016])]
                curve('strap_' + label + '_Stitch_' + str(side) + '_' + str(k).zfill(3), pts, 8.5e-05, thread)
        v = []
        f = []
        seg = 64
        for x in [-0.01, 0.01]:
            for r in [0.00072, 0.00172]:
                for j in range(seg):
                    a = 2 * math.pi * j / seg
                    v.append((x, sg * 0.0255 + r * math.cos(a), 0.0045 + r * math.sin(a)))
        for j in range(seg):
            k = (j + 1) % seg
            f.extend([(j, k, 64 + k, 64 + j), (128 + j, 192 + j, 192 + k, 128 + k), (j, 128 + j, 128 + k, k), (64 + j, 64 + k, 192 + k, 192 + j)])
        mesh('strap_' + label + '_Folded_Attachment', v, f, leather)
    col = bpy.data.collections['strap_Watch_Strap']
    root = bpy.data.objects['strap_Watch_Strap']

    def path(t, sg):
        c = Vector((0, sg * (0.0255 * math.cos(t) + 0.043 * math.sin(t)), 0.0045 - 0.03 * (1 - math.cos(t))))
        dy = -0.0255 * math.sin(t) + 0.043 * math.cos(t)
        dz = -0.03 * math.sin(t)
        nn = math.hypot(dy, dz)
        return (c, Vector((0, -sg * dz / nn, dy / nn)))

    def tube(name, pts, r, ma, cyclic=False):
        cu = bpy.data.curves.new(name, 'CURVE')
        cu.dimensions = '3D'
        cu.bevel_depth = r
        cu.bevel_resolution = 4
        sp = cu.splines.new('POLY')
        sp.points.add(len(pts) - 1)
        c = Vector(pts[0])
        for p, v in zip(sp.points, pts):
            p.co = (*Vector(v) - c, 1)
        sp.use_cyclic_u = cyclic
        o = bpy.data.objects.new(name, cu)
        col.objects.link(o)
        o.location = c
        o.parent = root
        cu.materials.append(bpy.data.materials[ma])
        return o
    cut = []
    for k in range(6):
        t = 1.94 + k * 0.145
        c, no = path(t, -1)
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=24, radius1=0.00075, radius2=0.00075, depth=0.01)
        me = bpy.data.meshes.new('strap_TempHole')
        bm.to_mesh(me)
        bm.free()
        o = bpy.data.objects.new('strap_TempHole', me)
        col.objects.link(o)
        o.location = c
        o.rotation_euler = no.to_track_quat('Z', 'Y').to_euler()
        cut.append(o)
    return bpy.data.objects['strap_Lower_Leather'], cut
