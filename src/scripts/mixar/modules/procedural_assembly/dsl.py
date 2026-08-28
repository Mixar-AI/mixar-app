# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The assembly DSL surface the program executes against (no bpy import).

Executing a program is a pure RECORDING pass: ``asm``/``P`` collect parts,
solids, frames, mates, and adjustments into plain data. The compiler then
realizes the recording with Blender geometry. Keeping recording bpy-free
means program errors surface with clean line numbers before any scene
mutation, and the whole layer unit-tests outside Blender.

Program-facing API (see the backend lane prompt for the authored contract):

    P.define("wheel_dia", 0.62)            # first definition wins
    with asm.part("front_left_wheel", detail="major_feature") as part:
        part.cylinder(d=P["wheel_dia"], h=0.24, axis="Y", block="tread")
        part.cylinder(d=0.10, h=0.30, axis="Y", op="cut")
        part.frame("hub", origin=(0, -0.12, 0), z=(0, -1, 0))
    asm.mate("front_left_wheel.hub", "axle.hub_left",
             type="revolute", d=P["axle_dia"], fit="clearance")
"""

from __future__ import annotations

from . import spec


class AssemblyError(ValueError):
    """Program-level semantic error (bad name, unknown partner, bad dims)."""


class Params:
    """Named parameter store. ``define`` is first-wins so a later part
    re-declaring a shared nominal can never silently retune an earlier one
    (the splicer also de-duplicates, this is the runtime backstop)."""

    def __init__(self):
        self._values: dict[str, float] = {}

    def define(self, name: str, value):
        if not isinstance(name, str) or not name.isidentifier():
            raise AssemblyError(f"invalid parameter name {name!r}")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise AssemblyError(f"parameter {name!r} must be a number")
        if name not in self._values:
            self._values[name] = float(value)
        return self._values[name]

    def __getitem__(self, name: str) -> float:
        try:
            return self._values[name]
        except KeyError:
            raise AssemblyError(f"parameter {name!r} is not defined") from None

    def __contains__(self, name: str) -> bool:
        return name in self._values

    def get(self, name: str, default=None):
        return self._values.get(name, default)

    def as_dict(self) -> dict:
        return dict(self._values)


def _vec3(v, what: str):
    try:
        x, y, z = v
        return (float(x), float(y), float(z))
    except Exception:
        raise AssemblyError(f"{what} must be a 3-tuple of numbers") from None


def _positive(value, what: str) -> float:
    try:
        f = float(value)
    except Exception:
        raise AssemblyError(f"{what} must be a number") from None
    if f <= 0:
        raise AssemblyError(f"{what} must be > 0 (got {f})")
    return f


class PartRecord:
    __slots__ = ("name", "detail", "solids", "frames", "chamfer", "scale", "index")

    def __init__(self, name: str, detail: str, index: int):
        self.name = name
        self.detail = detail
        self.index = index
        self.solids: list[dict] = []
        self.frames: dict[str, dict] = {}
        self.chamfer: dict | None = None
        self.scale: float = 1.0


class PartBuilder:
    """Recording proxy handed to a ``with asm.part(...) as part:`` block."""

    def __init__(self, record: PartRecord):
        self._r = record

    # -- solids -----------------------------------------------------------
    def _push(self, kind: str, op: str, block, at, rot, axis, dims: dict):
        if len(self._r.solids) >= spec.MAX_SOLIDS_PER_PART:
            raise AssemblyError(
                f"part '{self._r.name}' exceeds {spec.MAX_SOLIDS_PER_PART} solids"
            )
        if op not in ("add", "cut", "intersect"):
            raise AssemblyError(f"unknown solid op {op!r}")
        solid = {"kind": kind, "op": op}
        if at is not None:
            solid["at"] = _vec3(at, "at")
        if rot is not None:
            solid["rot"] = _vec3(rot, "rot")
        if axis is not None:
            ax = str(axis).upper()
            if ax not in ("X", "Y", "Z"):
                raise AssemblyError(f"axis must be X/Y/Z (got {axis!r})")
            solid["axis"] = ax
        if block is not None:
            if not isinstance(block, str) or not block.isidentifier():
                raise AssemblyError(f"color block must be an identifier (got {block!r})")
            solid["color_block"] = block
        solid.update(dims)
        self._r.solids.append(solid)
        return solid

    def box(self, size, at=None, rot=None, op="add", block=None):
        sx, sy, sz = (_positive(s, "box size") for s in _vec3(size, "size"))
        return self._push("box", op, block, at, rot, None, {"size": (sx, sy, sz)})

    def wedge(self, size, at=None, rot=None, op="add", block=None):
        sx, sy, sz = (_positive(s, "wedge size") for s in _vec3(size, "size"))
        return self._push("wedge", op, block, at, rot, None, {"size": (sx, sy, sz)})

    def cylinder(self, d, h, at=None, rot=None, axis="Z", segments=48,
                 op="add", block=None):
        return self._push("cylinder", op, block, at, rot, axis, {
            "d": _positive(d, "cylinder d"), "h": _positive(h, "cylinder h"),
            "segments": min(int(segments), spec.MAX_SEGMENTS),
        })

    def cone(self, d1, h, d2=0.0, at=None, rot=None, axis="Z", segments=48,
             op="add", block=None):
        if float(d2) < 0:
            raise AssemblyError("cone d2 must be >= 0")
        return self._push("cone", op, block, at, rot, axis, {
            "d1": _positive(d1, "cone d1"), "d2": float(d2),
            "h": _positive(h, "cone h"),
            "segments": min(int(segments), spec.MAX_SEGMENTS),
        })

    def tube(self, d_outer, d_inner, h, at=None, rot=None, axis="Z",
             segments=48, op="add", block=None):
        do = _positive(d_outer, "tube d_outer")
        di = _positive(d_inner, "tube d_inner")
        if di >= do:
            raise AssemblyError("tube d_inner must be < d_outer")
        return self._push("tube", op, block, at, rot, axis, {
            "d_outer": do, "d_inner": di, "h": _positive(h, "tube h"),
            "segments": min(int(segments), spec.MAX_SEGMENTS),
        })

    def sphere(self, d, at=None, op="add", block=None, segments=32):
        return self._push("sphere", op, block, at, None, None, {
            "d": _positive(d, "sphere d"),
            "segments": min(int(segments), spec.MAX_SEGMENTS),
            "rings": min(max(int(segments) // 2, 8), spec.MAX_SEGMENTS // 2),
        })

    def torus(self, d_major, d_minor, at=None, rot=None, axis="Z",
              op="add", block=None, segments=48):
        dM = _positive(d_major, "torus d_major")
        dm = _positive(d_minor, "torus d_minor")
        if dm >= dM:
            raise AssemblyError("torus d_minor must be < d_major")
        return self._push("torus", op, block, at, rot, axis, {
            "d_major": dM, "d_minor": dm,
            "segments": min(int(segments), spec.MAX_SEGMENTS),
            "minor_segments": 16,
        })

    # -- finishing / frames ----------------------------------------------
    def chamfer(self, width, angle_deg=30.0):
        """Machined chamfer over the whole part's sharp edges (one bevel
        segment, angle-limited). At most one per part; last call wins."""
        self._r.chamfer = {
            "width": _positive(width, "chamfer width"),
            "angle_deg": max(5.0, min(float(angle_deg), 80.0)),
        }

    def frame(self, name: str, origin, z, x=None):
        """Publish a mate frame in PART-LOCAL coordinates. +Z must point OUT
        of this part toward where its partner sits."""
        if not isinstance(name, str) or not name.isidentifier():
            raise AssemblyError(f"invalid frame name {name!r}")
        if name in self._r.frames:
            raise AssemblyError(
                f"frame '{self._r.name}.{name}' is already published"
            )
        self._r.frames[name] = {
            "origin": _vec3(origin, "frame origin"),
            "z": _vec3(z, "frame z"),
            "x": _vec3(x, "frame x") if x is not None else None,
        }


class _PartContext:
    def __init__(self, asm: "AssemblyRecorder", record: PartRecord):
        self._asm = asm
        self._record = record

    def __enter__(self) -> PartBuilder:
        self._asm._open_part = self._record
        return PartBuilder(self._record)

    def __exit__(self, exc_type, exc, tb):
        self._asm._open_part = None
        if exc_type is None and not self._record.solids:
            raise AssemblyError(
                f"part '{self._record.name}' declared no solids"
            )
        return False


class AssemblyRecorder:
    """``asm`` — the ordered recording of parts, mates, and adjustments."""

    def __init__(self, object_name: str = "assembly"):
        self.object_name = object_name
        self.parts: list[PartRecord] = []
        self.mates: list[dict] = []
        self.nudges: list[dict] = []
        self._by_name: dict[str, PartRecord] = {}
        self._open_part: PartRecord | None = None

    # -- parts ------------------------------------------------------------
    def part(self, name: str, detail: str = "major_feature") -> _PartContext:
        if self._open_part is not None:
            raise AssemblyError(
                f"part '{name}' opened inside part '{self._open_part.name}' — "
                "part blocks cannot nest"
            )
        if not isinstance(name, str) or not name.isidentifier():
            raise AssemblyError(f"invalid part name {name!r} (snake_case required)")
        if name in self._by_name:
            raise AssemblyError(f"part '{name}' is already defined")
        if len(self.parts) >= spec.MAX_PARTS:
            raise AssemblyError(f"assembly exceeds {spec.MAX_PARTS} parts")
        if detail not in spec.DETAIL_LEVELS:
            detail = "major_feature"
        record = PartRecord(name, detail, len(self.parts))
        self.parts.append(record)
        self._by_name[name] = record
        return _PartContext(self, record)

    def _resolve_frame_ref(self, ref: str) -> tuple[PartRecord, str]:
        if not isinstance(ref, str) or ref.count(".") != 1:
            raise AssemblyError(
                f"frame reference {ref!r} must be 'part_name.frame_name'"
            )
        part_name, frame_name = ref.split(".")
        record = self._by_name.get(part_name)
        if record is None:
            raise AssemblyError(f"unknown part '{part_name}' in mate")
        if frame_name not in record.frames:
            raise AssemblyError(
                f"part '{part_name}' publishes no frame '{frame_name}'"
            )
        return record, frame_name

    # -- mates -------------------------------------------------------------
    def mate(self, new_frame: str, partner_frame: str, type: str,
             d, fit: str = "location"):
        """Typed mate joining the NEW part (first ref) to an EARLIER part
        (second ref). Placement is solved from the frames; the compiler emits
        both halves of a static mate from the shared nominal ``d``."""
        if type not in spec.MATE_TYPES:
            raise AssemblyError(
                f"unknown mate type {type!r}; choose from {', '.join(spec.MATE_TYPES)}"
            )
        if fit not in spec.FIT_CLASSES:
            raise AssemblyError(
                f"unknown fit class {fit!r}; choose from {', '.join(spec.FIT_CLASSES)}"
            )
        new_rec, new_frame_name = self._resolve_frame_ref(new_frame)
        partner_rec, partner_frame_name = self._resolve_frame_ref(partner_frame)
        if new_rec is partner_rec:
            raise AssemblyError(f"part '{new_rec.name}' cannot mate to itself")
        if partner_rec.index > new_rec.index:
            raise AssemblyError(
                f"mate partner '{partner_rec.name}' comes AFTER '{new_rec.name}' — "
                "every part must mate to a part placed earlier (topological order)"
            )
        self.mates.append({
            "new_part": new_rec.name, "new_frame": new_frame_name,
            "partner": partner_rec.name, "partner_frame": partner_frame_name,
            "type": type, "d": _positive(d, "mate nominal d"), "fit": fit,
        })

    # -- machine-managed adjustments (refine stage) ------------------------
    def nudge(self, part_name: str, delta):
        """Post-placement translation, appended by the refine stage's
        deterministic snap_floaters fix — not for hand-authored placement."""
        if part_name not in self._by_name:
            raise AssemblyError(f"nudge names unknown part '{part_name}'")
        self.nudges.append({"part": part_name, "delta": _vec3(delta, "nudge delta")})

    def scale_part(self, part_name: str, factor):
        """Uniform scale of one part about its own origin (refine-stage fix)."""
        rec = self._by_name.get(part_name)
        if rec is None:
            raise AssemblyError(f"scale_part names unknown part '{part_name}'")
        rec.scale *= _positive(factor, "scale factor")

    # -- queries -----------------------------------------------------------
    def mates_of(self, part_name: str) -> list[dict]:
        return [m for m in self.mates if m["new_part"] == part_name]


def execute_program(source: str, object_name: str = "assembly") -> AssemblyRecorder:
    """Validate + run a program, returning the completed recording.

    Raises AssemblyError with program line context on any failure.
    """
    import math as _math

    err = spec.validate_program(source)
    if err:
        raise AssemblyError(err)
    asm = AssemblyRecorder(object_name)
    namespace = {
        "asm": asm, "P": Params(), "math": _math,
        "abs": abs, "min": min, "max": max, "range": range, "len": len,
        "round": round, "float": float, "int": int, "bool": bool,
        "enumerate": enumerate, "zip": zip, "sorted": sorted, "sum": sum,
        "list": list, "dict": dict, "tuple": tuple, "str": str,
        "__builtins__": {},
    }
    code = compile(source, "<assembly_program>", "exec")
    try:
        exec(code, namespace)  # noqa: S102 — validated DSL, empty builtins
    except AssemblyError as exc:
        line = _program_line(exc)
        if line:
            raise AssemblyError(f"{exc} (line {line})") from exc
        raise
    except Exception as exc:
        line = _program_line(exc)
        where = f" (line {line})" if line else ""
        raise AssemblyError(f"{type(exc).__name__}: {exc}{where}") from exc
    asm.params = namespace["P"]  # type: ignore[attr-defined]
    return asm


def _program_line(exc: BaseException) -> int | None:
    tb = exc.__traceback__
    line = None
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<assembly_program>":
            line = tb.tb_lineno
        tb = tb.tb_next
    return line
