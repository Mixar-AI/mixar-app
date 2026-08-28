# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Assembly DSL vocabulary + program validation (no bpy import).

Single source of truth for the mate library, fit classes, and the AST
whitelist that decides whether a backend-spliced program is allowed to
execute. The backend mirrors the *vocabulary* (mate/fit names) in its own
schemas; the geometric constants live here because the compiler that
realizes them lives here.

Everything in this file must stay importable under a mocked ``bpy`` (the
repo test conftest) — keep it dependency-free.
"""

from __future__ import annotations

import ast

# ---------------------------------------------------------------------------
# Mate library (paper Fig. 4 + Sec. 3.1)
# ---------------------------------------------------------------------------

# Static mates fully locate the new part; the compiler emits the MALE half on
# the new part and CUTS the FEMALE half from the partner, both derived from
# the one shared nominal ``d`` plus the fit-class offset — never two literals.
STATIC_MATE_TYPES = (
    "seat_face",     # planar face-on-face seat (no added geometry)
    "bolt_pattern",  # ring of bolt studs / matching holes; d = bolt-circle dia
    "peg_socket",    # chamfered peg into a toleranced bore; d = peg dia
    "flange",        # disc flange + bolt ring into a recess; d = flange dia
    "tab_slot",      # rectangular tab into a slot; d = tab width
    "press_fit",     # straight interference peg; d = peg dia
    "snap_tab",      # lipped tab into an undercut slot; d = tab width
    "lip_rabbet",    # ring lip into a rabbet recess; d = lip dia
    "key",           # keyed shaft into a keyed bore; d = shaft dia
)

# Kinematic mates solve placement identically but emit NO geometry — they
# record the intended free motion (joint type / axis) in the mate graph so a
# future articulation pass has its input.
KINEMATIC_MATE_TYPES = ("revolute", "prismatic", "spherical")

MATE_TYPES = STATIC_MATE_TYPES + KINEMATIC_MATE_TYPES

# Fit class -> signed per-side offset in millimetres (paper: clearance /
# location / press / snap). Positive = gap (female opened up / male backed
# off along the mate axis), negative = interference.
FIT_OFFSET_MM = {
    "clearance": 0.25,
    "location": 0.05,
    "press": -0.05,
    "snap": -0.10,
}
FIT_CLASSES = tuple(FIT_OFFSET_MM)

# Max tolerated body-into-body penetration depth per fit class (metres) —
# the mate gate's delta_max(phi). Interference fits legitimately overlap a
# little; clearance fits should barely touch. A part that gouges past this
# is rejected with the measured value.
PENETRATION_MAX_M = {
    "clearance": 0.002,
    "location": 0.002,
    "press": 0.004,
    "snap": 0.004,
}

# Registration-area gate coefficient: a static mate must register at least
# TAU_AREA * d^2 of contact between the two bodies (paper Eq. 2). Kept
# deliberately below a full face (d^2) — curved seats register less.
TAU_AREA = 0.10

# Span-based connectivity gate (paper Eq. 3-4): a non-body component is a
# VISIBLE floater when its AABB span reaches this fraction of the model span.
FLOATER_SPAN_TAU = 0.01

# Surface-to-surface distance under which two parts count as CONNECTED for
# the union-find component analysis (metres). Covers clearance-fit gaps.
CONNECT_EPS_M = 0.003

# Part detail levels from the plan (advisory; carried onto the objects).
DETAIL_LEVELS = ("silhouette", "major_feature", "sub_feature")

# Compiler hard budgets — a program beyond these is refused, not truncated.
MAX_PARTS = 60
MAX_SOLIDS_PER_PART = 200
MAX_PROGRAM_CHARS = 200_000
MAX_AST_NODES = 20_000
MAX_SEGMENTS = 128


# ---------------------------------------------------------------------------
# Program validation (AST whitelist)
# ---------------------------------------------------------------------------

# Names a program may reference at module level. The exec namespace provides
# exactly these; helper functions the program defines extend it as it runs.
ALLOWED_GLOBAL_NAMES = frozenset({
    "asm", "P", "math", "True", "False", "None",
    "abs", "min", "max", "range", "len", "round", "float", "int", "bool",
    "enumerate", "zip", "sorted", "sum", "list", "dict", "tuple", "str",
})

_ALLOWED_NODES = (
    ast.Module, ast.Expr, ast.Call, ast.Name, ast.Attribute, ast.Constant,
    ast.keyword, ast.Load, ast.Store, ast.Del,
    ast.Assign, ast.AugAssign, ast.AnnAssign,
    ast.Tuple, ast.List, ast.Dict, ast.Set, ast.Subscript, ast.Slice,
    ast.Index if hasattr(ast, "Index") else ast.Slice,  # py<3.9 compat no-op
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Is, ast.IsNot,
    ast.If, ast.For, ast.Break, ast.Continue, ast.Pass,
    ast.With, ast.withitem,
    ast.FunctionDef, ast.Return, ast.arguments, ast.arg,
    ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp,
    ast.comprehension, ast.Starred, ast.JoinedStr, ast.FormattedValue,
    ast.Lambda,
)

# Deliberately ABSENT from the whitelist (validation fails on sight):
# Import/ImportFrom (no imports), While (unbounded loops), Try (no silent
# error swallowing — the compiler owns error reporting), Global/Nonlocal,
# ClassDef, Await/AsyncFor/AsyncWith, Delete of attributes, Yield.


def validate_program(source: str) -> str | None:
    """Return an error message when ``source`` is not a legal assembly
    program, else None. Structural only — semantic errors (unknown mate
    partner, bad dimensions) surface at execution with line context.
    """
    if not isinstance(source, str) or not source.strip():
        return "empty program"
    if len(source) > MAX_PROGRAM_CHARS:
        return f"program exceeds {MAX_PROGRAM_CHARS} chars ({len(source)})"
    try:
        tree = ast.parse(source, filename="<assembly_program>")
    except SyntaxError as exc:
        return f"syntax error at line {exc.lineno}: {exc.msg}"

    node_count = 0
    defined: set[str] = set()
    for node in ast.walk(tree):
        node_count += 1
        if node_count > MAX_AST_NODES:
            return f"program exceeds {MAX_AST_NODES} AST nodes"
        if not isinstance(node, _ALLOWED_NODES):
            return (
                f"disallowed construct {type(node).__name__} at line "
                f"{getattr(node, 'lineno', '?')} — the assembly DSL permits "
                "only parameter/helper definitions, part blocks, mates, and "
                "simple arithmetic/loops (no imports, while, try, or classes)"
            )
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                return f"dunder attribute access at line {node.lineno}"
        if isinstance(node, ast.Name):
            if node.id.startswith("__"):
                return f"dunder name at line {getattr(node, 'lineno', '?')}"
            if isinstance(node.ctx, ast.Store):
                defined.add(node.id)
        if isinstance(node, ast.FunctionDef):
            defined.add(node.name)
            for a in list(node.args.args) + list(node.args.kwonlyargs):
                defined.add(a.arg)
            if node.args.vararg:
                defined.add(node.args.vararg.arg)
            if node.args.kwarg:
                defined.add(node.args.kwarg.arg)
        if isinstance(node, ast.Lambda):
            for a in list(node.args.args) + list(node.args.kwonlyargs):
                defined.add(a.arg)
        if isinstance(node, (ast.For, ast.comprehension)):
            tgt = node.target
            for n in ast.walk(tgt):
                if isinstance(n, ast.Name):
                    defined.add(n.id)
        if isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    for n in ast.walk(item.optional_vars):
                        if isinstance(n, ast.Name):
                            defined.add(n.id)

    # Unknown free names — catches a model reaching for bpy/os/open/etc.
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in ALLOWED_GLOBAL_NAMES and node.id not in defined:
                return (
                    f"unknown name '{node.id}' at line {node.lineno} — only "
                    "the DSL namespace (asm, P, math, builtins subset) and "
                    "names the program itself defines are available"
                )
    return None
