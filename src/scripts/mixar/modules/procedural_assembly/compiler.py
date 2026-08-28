# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Assembly compiler: program -> placed Blender objects -> measured report.

Runs in the ROUTED scene (the backend pins agent-lane scripts to the lane
scene via ``mixie_session_id``). A compile is a FULL deterministic rebuild:
previously built objects of this assembly are wiped (tag-scoped, membership-
safe) and the program re-executes, so the program text is always the single
source of truth for the geometry — exactly the paper's contract.

Placement is solved, never guessed: each part's primary mate places it via
``frames.solve_placement`` (Eq. 1); its remaining static mates are measured
as residuals. Static mates emit both halves (male union'd into the new part
in part-local space BEFORE placement; female cut from the partner in world
space AFTER), so the build stays connected by construction.
"""

from __future__ import annotations

import colorsys
import json
import time

import bpy
from mathutils import Matrix

from . import dsl, frames, geometry, mates, measure, spec
from .report import cap_report

_TAG = "mixar_asm"
_PART_TAG = "mixar_asm_part"


def part_color(index: int) -> tuple:
    h = (index * 0.61803398875) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.65, 0.95)
    return (r, g, b, 1.0)


def _hex(color) -> str:
    return "#%02X%02X%02X" % tuple(int(round(c * 255)) for c in color[:3])


def _wipe_previous(scene, object_name: str) -> int:
    """Remove this assembly's previous build from the scene. Membership-safe:
    an object also linked in ANY other scene is only unlinked here, never
    removed from bpy.data (bpy.data is file-scoped; sibling lanes share it)."""
    outside = set()
    for s in bpy.data.scenes:
        if s is not scene:
            for o in s.collection.all_objects:
                outside.add(o.name)
    removed = 0
    for o in list(scene.collection.all_objects):
        if o.get(_TAG) != object_name:
            continue
        if o.name in outside:
            try:
                scene.collection.objects.unlink(o)
            except RuntimeError:
                pass
            continue
        mesh = o.data if o.type == "MESH" else None
        bpy.data.objects.remove(o, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        removed += 1
    return removed


def _frame_matrix_local(fr: dict) -> Matrix:
    return Matrix(frames.frame_matrix(fr["origin"], fr["z"], fr.get("x")))


def _world_frame(obj, fr: dict) -> Matrix:
    return obj.matrix_world @ _frame_matrix_local(fr)


class _Budget:
    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds

    def check(self, what: str):
        if time.monotonic() > self.deadline:
            raise TimeoutError(f"compile budget exhausted during {what}")


def compile_assembly(params: dict) -> dict:
    """Compile + measure. See the backend bridge template for the contract.

    params:
        program (str)         — the assembly program source
        object_name (str)     — assembly identity (object/tag/text names)
        measure (bool)        — run the measurement suite (default True)
        check_mates_for (list)— restrict mate measurement to these new parts
                                (None = every static mate)
        solver (str)          — boolean solver id (default "EXACT")
        write_text (bool)     — persist the program to bpy.data.texts
        time_budget_s (float) — soft wall-clock budget (default 90)
    """
    t0 = time.monotonic()
    program = params.get("program") or ""
    object_name = str(params.get("object_name") or "assembly")
    do_measure = bool(params.get("measure", True))
    check_for = params.get("check_mates_for")
    solver = str(params.get("solver") or "EXACT")
    budget = _Budget(float(params.get("time_budget_s") or 90.0))
    scene = bpy.context.scene
    scene_sid = getattr(scene, "mixie_session_id", "") or (
        scene.get("mixie_session_id") or ""
    )

    # ---- 1. execute (record) --------------------------------------------
    try:
        asm = dsl.execute_program(program, object_name)
    except dsl.AssemblyError as exc:
        return {"success": False, "stage": "compile", "error": str(exc),
                "scene_session": scene_sid}

    # ---- 2. rebuild ------------------------------------------------------
    _wipe_previous(scene, object_name)
    objs: dict[str, object] = {}
    blocks_by_part: dict[str, list[str]] = {}
    try:
        for rec in asm.parts:
            budget.check(f"part '{rec.name}'")
            # Ordered unique color blocks; index 0 = the part's default block.
            blocks = [""]
            for s in rec.solids:
                b = s.get("color_block")
                if b and b not in blocks:
                    blocks.append(b)
            blocks_by_part[rec.name] = blocks

            def _block_index(b, _blocks=blocks):
                return _blocks.index(b) if b and b in _blocks else 0

            obj = geometry.realize_part_object(
                rec.name, rec.solids, scene, solver=solver,
                material_index_for_block=_block_index,
            )
            # Male halves of this part's static mates, in part-local space
            # (the part is still at identity — placement comes after).
            for m in asm.mates_of(rec.name):
                fl = _frame_matrix_local(rec.frames[m["new_frame"]])
                for solid in mates.male_solids(m["type"], m["d"], m["fit"]):
                    mesh = geometry.mesh_from_solid(f"{rec.name}_mate", solid)
                    mesh.transform(fl)
                    geometry.boolean_with_mesh(obj, mesh, "add", scene, solver=solver)
            if rec.scale != 1.0:
                obj.data.transform(Matrix.Scale(rec.scale, 4))
                for fr in rec.frames.values():
                    fr["origin"] = tuple(c * rec.scale for c in fr["origin"])
            if rec.chamfer:
                budget.check(f"chamfer '{rec.name}'")
                geometry.chamfer_object(
                    obj, rec.chamfer["width"], rec.chamfer["angle_deg"], scene
                )

            # ---- solved placement (paper Eq. 1) -------------------------
            part_mates = asm.mates_of(rec.name)
            if part_mates:
                primary = part_mates[0]
                partner = objs[primary["partner"]]
                partner_rec = asm._by_name[primary["partner"]]
                f_i_world = _world_frame(
                    partner, partner_rec.frames[primary["partner_frame"]]
                )
                t = frames.solve_placement(
                    tuple(tuple(row) for row in f_i_world),
                    tuple(tuple(row) for row in _frame_matrix_local(
                        rec.frames[primary["new_frame"]]
                    )),
                    mates.fit_offset_m(primary["fit"]),
                )
                obj.matrix_world = Matrix(t)

            # ---- female halves cut from the partners --------------------
            for m in part_mates:
                cutters = mates.female_solids(m["type"], m["d"], m["fit"])
                if not cutters:
                    continue
                partner = objs[m["partner"]]
                partner_rec = asm._by_name[m["partner"]]
                f_i_world = _world_frame(
                    partner, partner_rec.frames[m["partner_frame"]]
                )
                for solid in cutters:
                    mesh = geometry.mesh_from_solid(f"{m['partner']}_bore", solid)
                    mesh.transform(f_i_world)  # world coords; tool obj = identity
                    geometry.boolean_with_mesh(partner, mesh, "cut", scene, solver=solver)

            obj[_TAG] = object_name
            obj[_PART_TAG] = rec.name
            obj["mixar_asm_detail"] = rec.detail
            obj.color = part_color(rec.index)
            objs[rec.name] = obj

        # refine-stage snap fixes
        for nd in asm.nudges:
            o = objs[nd["part"]]
            o.matrix_world = (
                Matrix.Translation(nd["delta"]) @ o.matrix_world
            )
    except TimeoutError as exc:
        return {"success": False, "stage": "build", "error": str(exc),
                "built_parts": list(objs), "scene_session": scene_sid}
    except Exception as exc:  # noqa: BLE001 — reported, never raised to RPC
        return {"success": False, "stage": "build",
                "error": f"{type(exc).__name__}: {exc}",
                "built_parts": list(objs), "scene_session": scene_sid}

    bpy.context.view_layer.update()

    # ---- 3. persist the program (the editable deliverable) --------------
    if params.get("write_text", True):
        text_name = f"mixar_assembly_{object_name}.py"
        text = bpy.data.texts.get(text_name) or bpy.data.texts.new(text_name)
        text.clear()
        text.write(program)

    # ---- 4. measure ------------------------------------------------------
    report: dict = {
        "success": True,
        "scene_session": scene_sid,
        "object_name": object_name,
        "parts": {},
        "part_colors": {
            rec.name: _hex(part_color(rec.index)) for rec in asm.parts
        },
        "blocks": {k: v[1:] for k, v in blocks_by_part.items() if len(v) > 1},
        "mate_graph": [
            {k: m[k] for k in ("new_part", "partner", "type", "d", "fit")}
            for m in asm.mates
        ],
    }
    if do_measure:
        try:
            caches = {}
            for name, obj in objs.items():
                budget.check("measurement")
                caches[name] = {
                    "bvh": measure.world_bvh(obj),
                    "verts": measure.world_verts(obj),
                }
                stats = measure.part_stats(obj)
                caches[name]["volume"] = stats["volume_m3"]
                caches[name]["aabb"] = stats["aabb"]
                report["parts"][name] = stats

            mate_reports = []
            for m in asm.mates:
                if m["type"] not in spec.STATIC_MATE_TYPES:
                    continue
                if check_for and m["new_part"] not in check_for:
                    continue
                budget.check("mate gate")
                new_c, par_c = caches[m["new_part"]], caches[m["partner"]]
                partner_rec = asm._by_name[m["partner"]]
                f_i_world = _world_frame(
                    objs[m["partner"]], partner_rec.frames[m["partner_frame"]]
                )
                fw = tuple(tuple(row) for row in f_i_world)
                area = measure.registration_area(
                    new_c["bvh"], par_c["bvh"], fw, m["d"], m["fit"]
                )
                pen = measure.penetration(
                    new_c["bvh"], par_c["verts"], par_c["bvh"], new_c["verts"]
                )
                required = spec.TAU_AREA * m["d"] * m["d"]
                allowed = spec.PENETRATION_MAX_M[m["fit"]]
                mate_reports.append({
                    "new_part": m["new_part"], "partner": m["partner"],
                    "type": m["type"], "fit": m["fit"], "d": m["d"],
                    "area_m2": round(area, 6),
                    "area_required_m2": round(required, 6),
                    "area_ok": area >= required,
                    "penetration_m": round(pen, 5),
                    "penetration_max_m": allowed,
                    "penetration_ok": pen <= allowed,
                })
            report["mates"] = mate_reports
            report["connectivity"] = measure.connectivity(
                [objs[r.name] for r in asm.parts], caches
            )
        except TimeoutError as exc:
            report["measure_error"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            report["measure_error"] = f"{type(exc).__name__}: {exc}"

    report["created_objects"] = [o.name for o in objs.values()]
    report["elapsed_s"] = round(time.monotonic() - t0, 2)
    return cap_report(report)


def compile_assembly_json(params_json: str) -> str:
    """String-in/string-out convenience for bridge scripts."""
    try:
        params = json.loads(params_json)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"success": False, "error": f"bad params: {exc}"})
    return json.dumps(compile_assembly(params))
