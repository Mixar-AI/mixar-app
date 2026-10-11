# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Attribute validation + idiom normalization for agent scripts.

Ported from ``rag/mixar-rag-server.py`` (the RAG server's Gate-2/normalize
pair) so scripts are checked against the Mixar truth table IN THE APP,
right before the main thread executes them.

Two public entry points, mirroring the RAG server:

    normalize_mixar_script(script) -> (script, notes)
    validate_bpy_properties(script) -> list of issue strings

and one convenience wrapper used by the executor:

    report = prepare_script(script)      # -> GateReport, never raises

SOFT GATE — THIS MODULE HAS NO VETO POWER
-----------------------------------------
``prepare_script`` reports; it never blocks. There is deliberately no ``ok``
flag in its result, because every previous caller of a boolean here ended up
treating "an attribute could not be confirmed" as "do not run the script" —
and the truth table is a *reference*, not the language spec. It cannot see
custom properties (``obj["foo"]``), ID-property keys, ``get()`` lookups,
addon-injected attributes or anything else added after the table was dumped,
so a confirmed-looking miss is not proof of a broken script.

A script that really is wrong fails at runtime instead, and the resulting
traceback already travels back to the model over the RPC result, which is
what drives its self-correction loop. The gate's job is to make that loop
cheaper, not to interrupt it: normalization rewrites known-bad idioms for
free, and the issue list rides along on the result as advisory warnings so
the model learns the valid property names without spending a round trip.

GATE_MODE exists only as a documented dial for experiments. "soft" is the
only supported shipped value; nothing in the app may act on ``issues`` in a
way that changes whether a script runs.

The truth table (binary-dumped attribute/type/socket reference) is read
lazily from the module's bundled ``data/mixar_truth`` folder, falling back
to a dev checkout's ``rag/`` folder. When the files are absent or an older
format, validation degrades to "blind" (no issues) exactly like the RAG
server does — a missing table never blocks a script either.
"""

import ast
import json
import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path
from typing import Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------
# TRUTH TABLE (cached JSON dumped from the Mixar binary)
# ------------------------------------------------------------
TRUTH_VERSION = 7   # must match rag/mixar_meta.json


def _truth_folder() -> Path:
    """Locate the folder holding the dumped truth tables.

    The app-side bundled copy (space_mixie_chat/data/mixar_truth) wins —
    it is the only copy present in a packaged build. In a dev checkout
    the canonical table lives in the repo rag/ folder.
    """
    here = Path(__file__).resolve().parent
    bundled = here.parent / "data" / "mixar_truth"
    if bundled.is_dir():
        return bundled
    for parent in here.parents:
        cand = parent / "rag"
        if cand.is_dir():
            return cand
    return here.parents[4].parent / "rag"


REF_DIR = _truth_folder()
REF_JSON = REF_DIR / "mixar_props.json"        # v2: full dir()-based attribute sets
REF_TYPES_JSON = REF_DIR / "mixar_types.json"   # per-property type/min/max/enum
REF_SOCK_JSON = REF_DIR / "mixar_sockets.json"  # per-node-class socket names
REF_OPS_JSON = REF_DIR / "mixar_ops.json"        # bpy.ops categories -> operator names
REF_META_JSON = REF_DIR / "mixar_meta.json"     # cache format version

BPy_ATTRS = {}     # lower-class-name -> sorted full attribute list (props + methods)
BPy_ATTR_SETS = {} # lower-class-name -> set(...) for O(1) checks
BPy_NAMES = {}     # lower-class-name -> canonical class name
BPy_TYPES = {}     # lower-class-name -> {prop: {"type","min","max","enum":[...]}}
BPy_SOCKETS = {}   # lower-node-class -> {"inputs": [names], "outputs": [names],
                   #                      "input_types": {name: cls}, "output_types": {name: cls}}
BPy_OPS = {}       # operator category -> set of operator names (bpy.ops, dumped)
_BPy_REF_LOADED = False


# The type table is by far the largest: 38 MB of JSON that becomes ~150 MB of
# Python objects, held for the process lifetime, in service of an advisory
# check. Measured on the shipped tables: existence/socket/operator data costs
# 25 MB, the per-property type maps that value and enum checks need add ~155 MB.
# That is a poor trade on a machine already short of memory while a scene is
# open, so the expensive half is skipped there. The gate is advisory — losing
# value-range advice must never cost memory the scene needs.
MAX_TRUTH_LOAD_MB = 1536


def _available_mb():
    """Best-effort free physical memory in MB, or None when it cannot be told."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.ullAvailPhys / 1e6
    except Exception:  # noqa: BLE001 — no ctypes/no kernel32: assume there is room
        return None


def _load_from_cache():
    with open(REF_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    for name, alist in data.items():
        key = name.lower()
        BPy_ATTRS[key] = alist
        BPy_ATTR_SETS[key] = set(alist)
        BPy_NAMES[key] = name

    avail = _available_mb()
    if avail is not None and avail < MAX_TRUTH_LOAD_MB:
        logger.warning("Only %.0f MB of memory free (<%d MB) — loading the "
                       "attribute table without the per-property type maps. "
                       "Value and enum checks are OFF; attribute names are "
                       "checked against the dir() table only.",
                       avail, MAX_TRUTH_LOAD_MB)
    elif REF_TYPES_JSON.is_file():
        try:
            with open(REF_TYPES_JSON, "r", encoding="utf-8") as f:
                tdata = json.load(f)
            for name, tmap in tdata.items():
                BPy_TYPES[name.lower()] = tmap
            # The v2 dir() table already carries the real property identifiers
            # (verified: the type maps add no names the dir() list lacks), so
            # this merge is a safety net for older/partial caches only.
            for key, tmap in BPy_TYPES.items():
                if not tmap:
                    continue
                merged = sorted(set(BPy_ATTRS.get(key, [])) | set(tmap.keys()))
                BPy_ATTRS[key] = merged
                BPy_ATTR_SETS[key] = set(merged)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read %s (%s) — value-type checks OFF.",
                           REF_TYPES_JSON.name, e)
    if REF_SOCK_JSON.is_file():
        try:
            with open(REF_SOCK_JSON, "r", encoding="utf-8") as f:
                sdata = json.load(f)
            for name, smap in sdata.items():
                BPy_SOCKETS[name.lower()] = smap
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read %s (%s) — socket checks OFF.",
                           REF_SOCK_JSON.name, e)
    if REF_OPS_JSON.is_file():
        try:
            with open(REF_OPS_JSON, "r", encoding="utf-8") as f:
                odata = json.load(f)
            for category, names in odata.items():
                BPy_OPS[category] = set(names)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read %s (%s) — operator checks OFF.",
                           REF_OPS_JSON.name, e)
    logger.info("Attribute reference from cache: %d classes "
                "(%d attributes total).",
                len(BPy_ATTRS), sum(len(v) for v in BPy_ATTR_SETS.values()))


def _load_property_reference():
    """One-time: full attribute + type + socket truth table (cache only).

    The RAG server had three layers (cache -> pip bpy -> Mixar binary
    dump); the app has no access to the binary, so only the cached
    table is used. Lazy: the 40 MB types file is parsed once, on the
    first validated script, not at import time.
    """
    global _BPy_REF_LOADED
    if _BPy_REF_LOADED:
        return
    _BPy_REF_LOADED = True
    try:
        if REF_JSON.is_file() and REF_META_JSON.is_file():
            with open(REF_META_JSON, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("version") == TRUTH_VERSION:
                _load_from_cache()
                return
            logger.warning("Truth table cache is an older format "
                           "(version %s, expected %d) — attribute validation "
                           "will be blind. Re-dump with: "
                           "python rag/mixar-rag-server.py --refresh-truth",
                           meta.get("version"), TRUTH_VERSION)
        else:
            logger.warning("Truth table not found at %s — attribute "
                           "validation will be blind.", REF_DIR)
    except Exception as e:  # noqa: BLE001
        logger.warning("Truth table load failed (%s) — attribute validation "
                       "will be blind.", e)


def _resolve_bpy_class(candidate):
    """Case-insensitive lookup against every known bpy.types class."""
    _load_property_reference()
    return BPy_NAMES.get((candidate or "").lower())


# ============================================================
# AST + CHAIN-WALKING TYPE RESOLVER
#
# Every attribute access in the script is resolved to a concrete
# bpy.types class by walking the expression left-to-right:
#
#   root          : variable (tracked) | bpy.data.<coll> | bpy.context.<m>
#                   | a call (x.modifiers.new(...), x.nodes.new(...),
#                             bpy.data.<coll>.new(...))
#   hops          : attribute / subscript steps
#
#   STRUCT_MAP      : (class, member) -> sub-struct class   (scene.render -> RenderSettings)
#   COLLECTION_MAP  : (class, member) -> element class of a
#                     subscript/iteration                    (Mesh.materials -> Material)
#
# The resolved (cls, pending_member) is then checked:
#   * attribute access  -> attr must be in the dir(cls) truth set
#   * socket subscript  -> name must be in the socket table for that node class
#   * constant RHS      -> value must fit the declared type/range/enum
# ============================================================
def _chain_names(node):
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
    return list(reversed(names))


BPy_DATA_CLASSES = {
    "objects": "Object", "meshes": "Mesh", "materials": "Material",
    "lights": "Light", "cameras": "Camera", "images": "Image",
    "textures": "Texture", "node_groups": "NodeTree", "curves": "Curve",
    "fonts": "Font", "armatures": "Armature", "actions": "Action",
    "scenes": "Scene", "worlds": "World", "sounds": "Sound",
    "collections": "Collection", "brushes": "Brush", "libraries": "Library",
    "masks": "Mask", "grease_pencils": "GreasePencil", "particles": "ParticleSettings",
}

# (class, member) -> class of the sub-struct you get by reading the member
STRUCT_MAP = {
    ("Object", "data"): "Mesh",               # best-effort (mesh is the common case)
    ("Object", "active_material"): "MaterialSlot",
    ("MaterialSlot", "material"): "Material",
    ("Scene", "render"): "RenderSettings",
    ("Scene", "display"): "SceneDisplay",
    ("Scene", "view_settings"): "ColorManagedViewSettings",
    ("Scene", "camera"): "Camera",
    ("Scene", "world"): "World",
    ("Scene", "collection"): "Collection",
    ("Camera", "data"): "Camera",
    ("Light", "data"): "Light",
    ("Material", "node_tree"): "NodeTree",
    ("World", "node_tree"): "NodeTree",
    ("Node", "node_tree"): "NodeTree",
    ("PoseBone", "bone"): "Bone",
    ("ParticleSystem", "settings"): "ParticleSettings",
    ("Window", "screen"): "Screen",
}

# (class, member) -> class of ELEMENTS when subscripting/iterating the member
COLLECTION_MAP = {
    ("Object", "modifiers"): "Modifier",
    ("Object", "constraints"): "Constraint",
    ("Object", "material_slots"): "MaterialSlot",
    ("Object", "pose_bones"): "PoseBone",
    ("Object", "particle_systems"): "ParticleSystem",
    ("Object", "vertex_groups"): "VertexGroup",
    ("Mesh", "materials"): "Material",
    # This Mixar build RENAMEs the element classes (verified against the
    # binary-dumped truth table): Vertex/Edge/Face/Loop/UVMap do NOT exist.
    ("Mesh", "vertices"): "MeshVertex",
    ("Mesh", "edges"): "MeshEdge",
    ("Mesh", "loops"): "MeshLoop",
    # MeshPolygon IS in the truth table (42 attrs) — mapping it makes
    # per-polygon loop variables (for p in mesh.polygons) verifiable
    # instead of silently unchecked (that hole let a runtime-fatal
    # "for face in mesh.polygons: face.normal_update()" through the gate).
    ("Mesh", "polygons"): "MeshPolygon",
    ("Scene", "objects"): "Object",
    ("Scene", "view_layers"): "ViewLayer",
    ("Collection", "all_objects"): "Object",
    ("Collection", "objects"): "Object",
    ("Collection", "children"): "Collection",
    ("ViewLayer", "objects"): "Object",
    ("Armature", "bones"): "Bone",
    ("NodeTree", "nodes"): "Node",
    ("Node", "inputs"): "NodeSocket",
    ("Node", "outputs"): "NodeSocket",
    ("WindowManager", "windows"): "Window",
}

# bpy.context.<member> -> class of the single value / element of a collection
CONTEXT_MAP = {
    "scene": "Scene", "object": "Object", "active_object": "Object",
    "camera": "Camera", "active_camera": "Camera",
    "selected_objects": "Object", "object_data": "Mesh",
    "active_object_data": "Mesh",
    "mesh": "Mesh", "material": "Material", "texture": "Texture",
    "image": "Image", "node": "Node",
    "bone": "Bone", "active_bone": "Bone",
    "pose_bone": "PoseBone", "active_pose_bone": "PoseBone",
    "armature": "Armature", "action": "Action", "world": "World",
    "area": "Area", "region": "Region",
    "window": "Window", "screen": "Screen",
    "view_layer": "ViewLayer", "render_layer": "RenderLayer",
    "tool_settings": "ToolSettings", "window_manager": "WindowManager",
}

# non-bpy classes we must never flag (mathutils & co.)
TRUSTED_CLASSES = {
    "vector", "floatvector", "intvector", "matrix", "quat", "euler",
    "color", "floatarray", "intarray", "string",
}


def _ops_issue(category: str, op: str):
    """Is  bpy.ops.<category>.<op>(...)  a real operator in this build?

    The operator tree is dynamic, so the chain walker deliberately
    never checks it (see _state_of) — this is the ONLY place operator
    names are validated, against mixar_ops.json (bpy.ops dumped from
    the Mixar binary). Returns an issue string, or None when the call
    is legal / the table is absent (blind, not false)."""
    if not BPy_OPS:
        return None
    ops_in_cat = BPy_OPS.get(category)
    if ops_in_cat is None:
        close = get_close_matches(category, list(BPy_OPS), n=3, cutoff=0.4)
        return (f"- bpy.ops.{category}.{op}: no such operator category in this "
                f"Mixar build."
                + (f" Did you mean: {', '.join(close)}?" if close
                   else f" Categories: {', '.join(sorted(BPy_OPS))[:80]}.")
                + " Delete the call or replace it with a real operator.")
    if op in ops_in_cat:
        return None
    close = get_close_matches(op, sorted(ops_in_cat), n=3, cutoff=0.45)
    return (f"- bpy.ops.{category}.{op}: no such operator in this Mixar build "
            f"(the engine kills the call with AttributeError)."
            + (f" Did you mean: {', '.join(close)}?" if close
               else f" Available: {', '.join(sorted(ops_in_cat)[:12])}."))

_COLLECTED = "__collection__"   # sentinel: expression is a bare collection
_GENERIC_SOCKET = "__generic_socket__"  # sentinel: socket slot whose node class is not in the socket table


# bpy.data collections that do NOT support .new() in this Mixar build
# (verified by probe against mixar.exe -b: "bpy_prop_collection: attribute 'new' not found").
NO_NEW_COLLECTIONS = {"sounds"}


def _parse_parent(expr):
    """Split an expression into (root, parts) where parts is a left->right
    list of ("attr", name) / ("sub", slice_node) steps above the root.
    root = Name id, a Call node, or None."""
    parts = []
    node = expr
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        if isinstance(node, ast.Attribute):
            parts.append(("attr", node.attr))
        else:
            parts.append(("sub", node.slice))
        node = node.value
    parts.reverse()
    if isinstance(node, ast.Name):
        return node.id, parts
    if isinstance(node, ast.Call):
        return node, parts
    return None, parts


def _socket_elem_type(node_cls, side, slice_node):
    """CONCRETE socket class for  <node>.inputs['x'] / .outputs['x']  (or None).

    side is 'inputs' or 'outputs'. Resolves through the socket-type truth
    table (dumped with the concrete bpy class of every socket); None when
    the node class or that socket has no recorded type, in which case the
    caller falls back to the generic NodeSocket base class."""
    smap = BPy_SOCKETS.get(node_cls.lower())
    if not smap:
        return None
    if not (isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str)):
        return None
    stype = (smap.get(side[:-1] + "_types") or {}).get(slice_node.value)
    if stype and _resolve_bpy_class(stype):
        return stype
    return None


def _walk_members(cls, parts):
    """Walk hops on top of a known class. Returns (cls, pending_member):
    pending None  -> expression yields a value of class cls;
    pending 'm'   -> expression is cls.<member> read (property/collection)."""
    last = None
    for kind, val in parts:
        if kind == "attr":
            s = STRUCT_MAP.get((cls, val))
            if s is not None:
                cls, last = s, None      # struct hop: class advanced
            else:
                last = val                # property or collection member: pending
        else:  # subscript
            if last is None:
                return None, None
            el = COLLECTION_MAP.get((cls, last))
            if el is None and last in ("inputs", "outputs") and cls.lower() in BPy_SOCKETS:
                # concrete socket type when known (lets .default_value /
                # .hide_value etc. check against the REAL socket class, not
                # just the NodeSocket base)
                el = _socket_elem_type(cls, last, val) or "NodeSocket"
            if el is None:
                return None, None
            if el == "NodeSocket" and cls.lower() not in BPy_SOCKETS:
                # The node class was NOT in the socket table, so this
                # "NodeSocket" is a fallback guess — the concrete slot
                # type is unknowable. Property checks on the sentinel
                # defer to the whole-socket-family check.
                el = _GENERIC_SOCKET
            cls, last = el, None
    return cls, last


def _string_kw_or_arg(call, kw_name, positional_index):
    """Extract a string argument: keyword first, then Nth positional.
    SAFE: returns None for any non-Call node."""
    if not isinstance(call, ast.Call):
        return None
    for kw in call.keywords:
        if kw.arg == kw_name and isinstance(kw.value, ast.Constant) \
                and isinstance(kw.value.value, str):
            return kw.value.value
    if len(call.args) > positional_index \
            and isinstance(call.args[positional_index], ast.Constant) \
            and isinstance(call.args[positional_index].value, str):
        return call.args[positional_index].value
    return None


def _infer_call_class(call):
    """What bpy.types class does this call RETURN? (or None)"""
    if not isinstance(call, ast.Call):
        return None
    chain = _chain_names(call.func)
    if not chain:
        return None
    if chain[0] == "bpy" and "ops" in chain:
        return None
    # bpy.data.<collection>.new(...) -> element of that collection
    if chain[:2] == ["bpy", "data"] and len(chain) >= 3:
        return BPy_DATA_CLASSES.get(chain[2])
    # x.modifiers.new(type='<TYPE>') -> <Type>Modifier
    if "modifiers" in chain and chain[-1] in ("new", "append"):
        type_val = _string_kw_or_arg(call, "type", 1)
        if type_val:
            t = re.sub(r"[-_ ]", "_", type_val.strip().upper())
            cand = "".join(w[:1].upper() + w[1:].lower() for w in t.split("_") if w) + "Modifier"
            return _resolve_bpy_class(cand) or cand
        return None
    # x.nodes.new(type='<NodeTypeName>') -> that node class
    if "nodes" in chain and chain[-1] == "new":
        type_val = _string_kw_or_arg(call, "type", 0)
        if type_val:
            return _resolve_bpy_class(type_val) or type_val
        return None
    return None


def _state_of(root, parts, var_map=None):
    """(cls, pending_member) state for the expression root+parts."""
    if root is None:
        return None, None
    if isinstance(root, ast.Call):
        cls = _infer_call_class(root)
        if cls is None:
            return None, None
        return _walk_members(cls, parts)
    if root == "bpy":
        if not parts or parts[0][0] != "attr":
            return None, None
        first = parts[0][1]
        if first == "ops":
            return None, None              # operator tree is dynamic — never check
        if first == "data" and len(parts) >= 2 and parts[1][0] == "attr":
            el = BPy_DATA_CLASSES.get(parts[1][1])
            if el is None:
                return None, None
            if len(parts) == 2:
                return (_COLLECTED, el)    # bare collection; element class = el
            rest = parts[2:]
            if rest[0][0] == "sub":
                return _walk_members(el, rest[1:])
            return _walk_members(el, rest)
        if first == "context" and len(parts) >= 2 and parts[1][0] == "attr":
            el = CONTEXT_MAP.get(parts[1][1])
            if el is None:
                return None, None
            if len(parts) == 2:
                return (_COLLECTED, el)    # bare collection (selected_objects & co.)
            rest = parts[2:]
            if rest[0][0] == "sub":
                return _walk_members(el, rest[1:])
            return _walk_members(el, rest)
        return None, None
    # plain variable
    cls = (var_map or {}).get(root)
    if cls is None:
        return None, None
    return _walk_members(cls, parts)


def _expr_class(value, var_map):
    """bpy.types class produced by this expression (or None)."""
    if isinstance(value, ast.Call):
        cls = _infer_call_class(value)
        if cls:
            return cls
    root, parts = _parse_parent(value)
    if root is None:
        return None
    # obj.modifiers.new(name, type='OCEAN') — the type argument names the
    # concrete modifier class (Blender's modifier RNA enum). The result
    # was previously untyped, so property TYPE checks (e.g. a float literal
    # assigned to an INT property like OceanModifier.spatial_size) were
    # silently skipped on modifier variables.
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) \
            and value.func.attr == "new":
        names = _chain_names(value.func.value)
        if len(names) >= 2 and names[-2] == "modifiers" and \
                isinstance(root, str) and parts and parts[0][0] == "attr" \
                and parts[0][1] == "modifiers":
            type_arg = None
            if len(value.args) >= 2 and isinstance(value.args[1], ast.Constant):
                type_arg = value.args[1].value
            else:
                for kw in value.keywords:
                    if kw.arg == "type" and isinstance(kw.value, ast.Constant):
                        type_arg = kw.value.value
            if isinstance(type_arg, str):
                for cand in (f"{type_arg}Modifier", type_arg):
                    if cand in BPy_NAMES:
                        return BPy_NAMES[cand]
    cls, last = _state_of(root, parts, var_map)
    if cls is None:
        return None
    if cls == _COLLECTED:
        return last                          # variable holds a collection -> element
    if last is None:
        return cls
    return COLLECTION_MAP.get((cls, last))


def _elem_class(value, var_map):
    """Class of the elements yielded when iterating this expression."""
    if isinstance(value, ast.Call):
        return _infer_call_class(value)
    root, parts = _parse_parent(value)
    if root is None:
        return None
    cls, last = _state_of(root, parts, var_map)
    if cls is None:
        return None
    if cls == _COLLECTED:
        return last
    if last is None:
        return cls                           # e.g. iterating bpy.context.selected_objects
    return COLLECTION_MAP.get((cls, last))


def _expr_is_collection(value, var_map):
    """True if this expression evaluates to a collection OBJECT ITSELF
    (bpy.data.objects, mat.node_tree.nodes, node.inputs, ...) rather
    than to a single element. .new/.remove/.clear/.get on such a variable
    are collection APIs — not element properties — so pass 1 must not
    validate them against the element class."""
    if isinstance(value, ast.Call):
        return False
    root, parts = _parse_parent(value)
    if root is None:
        return False
    cls, last = _state_of(root, parts, var_map)
    if cls == _COLLECTED:
        return True
    if cls is None or last is None:
        return False
    if COLLECTION_MAP.get((cls, last)) is not None:
        return True
    return last in ("inputs", "outputs") and cls.lower() in BPy_SOCKETS


# ============================================================
# VALUE-TYPE / RANGE / ENUM CHECKER
# ============================================================
def _type_issue(cls_name, attr, info, value_node):
    """Check a CONSTANT right-hand side against the property's declared
    type, range and enum values. Dynamic values are NOT checked.
    Returns an issue string or None."""
    if not info or "type" not in info:
        return None
    ptype = (info.get("type") or "").upper()
    if not ptype:
        return None
    if isinstance(value_node, (ast.Tuple, ast.List)):
        # sequence literal on the RHS (e.g. attr = (0, 1)).
        # Requires the v4 truth table: array properties are dumped as
        # FLOAT_ARRAY / INT_ARRAY, so a plain FLOAT/INT here is a true scalar.
        if ptype in ("INT_ARRAY", "FLOAT_ARRAY", "FLOAT_VECTOR", "CHAR_ARRAY"):
            return None          # a tuple is the right shape for an array/vector slot
        if ptype in ("INT", "FLOAT"):
            return (f"- {attr}: bpy.types.{cls_name}.{attr} expects a single "
                    f"{'integer' if ptype == 'INT' else 'number'} (you wrote a "
                    f"tuple). Pass one value, e.g. {attr} = 1.5")
        if ptype == "BOOLEAN":
            return (f"- {attr}: bpy.types.{cls_name}.{attr} expects True/False "
                    f"(you wrote a tuple).")
        if ptype in ("STRING", "ENUM"):
            return (f"- {attr}: bpy.types.{cls_name}.{attr} expects a string "
                    f"(you wrote a tuple).")
        return None
    if not isinstance(value_node, ast.Constant):
        return None
    v = value_node.value

    if ptype == "INT":
        if isinstance(v, bool):
            return f"- {attr}: bpy.types.{cls_name}.{attr} expects an int (you wrote a bool)."
        if isinstance(v, float):
            lo, hi = info.get("min"), info.get("max")
            rng = f" (legal range: {lo}..{hi})" if lo is not None and hi is not None else ""
            return (f"- {attr}: bpy.types.{cls_name}.{attr} is an INT in this Mixar build "
                    f"(you wrote the float {v!r}). Use an integer literal within the legal range"
                    + rng + ".")
    elif ptype == "FLOAT":
        pass  # int or float both accepted
    elif ptype in ("INT_ARRAY", "FLOAT_ARRAY", "FLOAT_VECTOR", "CHAR_ARRAY"):
        if not isinstance(v, (list, tuple)):
            hint = " (e.g. (x, y, z))" if ptype == "FLOAT_VECTOR" else " (e.g. (a, b))"
            return (f"- {attr}: bpy.types.{cls_name}.{attr} expects a sequence{hint}, "
                    f"not a single {type(v).__name__}.")
    elif ptype == "BOOL":
        if not isinstance(v, bool):
            return f"- {attr}: bpy.types.{cls_name}.{attr} expects True/False (you wrote {v!r})."
    elif ptype == "ENUM":
        if not isinstance(v, str):
            return f"- {attr}: bpy.types.{cls_name}.{attr} expects an enum string (you wrote {v!r})."
        enums = info.get("enum") or []
        if enums and v not in enums:
            close = get_close_matches(v, enums, n=3, cutoff=0.4)
            shown = ", ".join(enums[:12]) + ("..." if len(enums) > 12 else "")
            return (f"- {attr}: '{v}' is not a valid enum value for bpy.types.{cls_name}.{attr}. "
                    f"Valid: {shown}. "
                    + (f"Did you mean: {', '.join(close)}?" if close else ""))
        return None
    elif ptype == "STRING":
        if not isinstance(v, str):
            return f"- {attr}: bpy.types.{cls_name}.{attr} expects a string (you wrote {v!r})."

    # numeric range check for INT / FLOAT
    if ptype in ("INT", "FLOAT") and isinstance(v, (int, float)) and not isinstance(v, bool):
        lo, hi = info.get("min"), info.get("max")
        if lo is not None and v < lo:
            return f"- {attr}: value {v!r} is below the minimum {lo!r} allowed by bpy.types.{cls_name}."
        if hi is not None and v > hi:
            return f"- {attr}: value {v!r} is above the maximum {hi!r} allowed by bpy.types.{cls_name}."
    return None


# struct-pointer members that LEGALLY take ['name'] (e.g. obj.pose['Bone']),
# plus collection-typed members this build's type map records as plain
# methods (they are in dir() but not in the RNA property map).
_SUBSCRIPTABLE_POINTERS = {"pose"}
_NONPROP_COLLECTIONS = {"children", "children_recursive", "users_scene", "users_collection"}


def _subscript_target_issue(cls, member, node):
    """Validate WHAT a Subscript node is subscripting into — not just the key.

    The attribute pass already proved cls.<member> EXISTS; this checks whether
    the member can actually be indexed. Methods and scalars exist too, yet die
    at runtime ('builtin_function_or_method object does not support item
    assignment' / 'float object is not subscriptable'). member is None when a
    whole class instance is subscripted (mesh['k'] — legal custom-property
    access on data-blocks, illegal on non-Id structs). Returns an issue or None."""
    key = cls.lower()
    attrset = BPy_ATTR_SETS.get(key) or set()
    if member is None:
        # data-blocks in this build expose a dict API (get/keys/values/items/
        # pop) for custom properties, so  id['custom_prop'] = ...  is legal;
        # classes WITHOUT that API cannot be indexed at all
        if "get" in attrset:
            return None
        return (f"- {cls} does not support ['...'] item access — it has no "
                f"custom-property dict API in this Mixar build. Set its properties "
                f"directly (e.g. <{cls.lower()}>.<property> = value) instead of "
                f"indexing the object itself.")
    info = (BPy_TYPES.get(key) or {}).get(member)
    if info is None:
        if member in _NONPROP_COLLECTIONS:
            return None   # RNA collection the type map recorded as a method
        if not BPy_TYPES.get(key):
            # The per-class type map never loaded: memory-gated load, an older
            # table, or a class the dump missed. A dir() list alone cannot tell
            # a property from a method — without the map every property LOOKS
            # like a method, and calling a live `ob.location` a method is the
            # kind of confident wrong advice that makes the whole gate
            # untrustworthy. Can't decide, so say nothing.
            return None
        if member in attrset:
            return (f"- {member}: bpy.types.{cls}.{member} is a METHOD, not a "
                    f"collection or a property — methods can never be subscripted "
                    f"(the engine kills it at runtime with \"'builtin_function_or_method' "
                    f"object does not support item assignment\"). Call it with "
                    f"parentheses to use its return value, or set the data property "
                    f"it manages instead of indexing it.")
        return None   # the attribute pass already reported the missing member
    ptype = (info.get("type") or "").upper()
    if ptype == "COLLECTION":
        return None
    if ptype in ("FLOAT_ARRAY", "INT_ARRAY"):
        sl = node.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            return (f"- {member}: bpy.types.{cls}.{member} is a numeric array, not a "
                    f"dict — a string key is not a valid index. Use a numeric index "
                    f"(e.g. {member}[0]) or assign a tuple to the whole property "
                    f"({member} = (x, y, z)).")
        return None
    if ptype == "POINTER":
        if member in _SUBSCRIPTABLE_POINTERS:
            return None
        target = STRUCT_MAP.get((cls, member))
        if target is None:
            return None               # unknown target -> can't decide, don't guess
        if "get" in (BPy_ATTR_SETS.get(target.lower()) or set()):
            return None               # pointed-to data-block has the dict API
        return (f"- {member}: bpy.types.{cls}.{member} points at a {target} struct, "
                f"which has no ['...'] item access in this build. Reach it first and "
                f"set its properties directly (e.g. obj.{member}.<property> = value).")
    kind = {"FLOAT": "a number", "INT": "an integer", "BOOLEAN": "True/False",
            "STRING": "a string", "ENUM": "an enum string"}.get(ptype, "a single value")
    ex = {"FLOAT": "0.0", "INT": "0", "BOOLEAN": "True", "STRING": '"text"'}.get(ptype)
    if ptype == "ENUM" and (info.get("enum") or []):
        ex = repr(info["enum"][0])
    ex_s = f" (e.g. {member} = {ex})" if ex else ""
    return (f"- {member}: bpy.types.{cls}.{member} is {kind}, not a collection — "
            f"it can't be subscripted. Assign it directly{ex_s} "
            f"instead of {member}[...].")


# ============================================================
# WRITE-LEGALITY CHECK  (read-only RNA props + non-RNA attributes)
# ============================================================
# Probe of mixar.exe (2026-09-30, all 4041 bpy.types classes): ZERO
# dir()-level class attributes outside the RNA property map are
# writable — socket value aliases (values/vector/color/...), methods,
# descriptors and python properties are ALL read-only, and the engine
# rejects an assignment to any of them with
#   "'NodeSocketColor' object attribute 'values' is read-only".
# Whitelist of proven-writable non-RNA attributes (empty today).
_NONRNA_WRITABLE = set()


def _writable_props(cls_name, limit=10):
    tmap = BPy_TYPES.get(cls_name.lower()) or {}
    out = [a for a in sorted(tmap)
           if isinstance(tmap.get(a), dict) and not tmap[a].get("readonly")]
    return out[:limit]


def _write_issue(cls_name, attr):
    """Is  <cls_name>.<attr> = ...  legal in this build? Issue string or None.

    Two layers, both ground-truthed against the Mixar binary:
      * attr is an RNA property -> flagged only when it is readonly;
      * attr is NOT an RNA property (socket alias / method / descriptor —
        it passed the existence check because dir() lists it) -> flagged,
        because the engine rejects the assignment at runtime."""
    tmap = BPy_TYPES.get(cls_name.lower()) or {}
    if not tmap:
        return None          # no type map for this class -> can't decide
    info = tmap.get(attr)
    if info is None:
        if attr in _NONRNA_WRITABLE:
            return None
        wr = _writable_props(cls_name)
        return (f"- {attr}: bpy.types.{cls_name}.{attr} is NOT a writable property in this "
                f"Mixar build (read-only alias, method or descriptor — the engine kills the "
                f"assignment with \"'{cls_name}' object attribute '{attr}' is read-only\"). "
                f"Delete that line or set one of the writable properties instead: "
                f"{', '.join(wr) if wr else '(none on this class)'}")
    if info.get("readonly"):
        wr = _writable_props(cls_name)
        return (f"- {attr}: bpy.types.{cls_name}.{attr} is READ-ONLY in this Mixar build "
                f"(the engine computes it). Never assign to it — delete that line and "
                f"achieve the visual effect through the writable properties that drive it"
                + (f" (e.g. {', '.join(wr[:6])})." if wr else "."))
    return None


def _socket_iter_write_issue(node_cls, side, attr):
    """Write check for a socket variable whose concrete type is UNKNOWN
    (it comes from  for s in <node>.inputs/outputs ): legal only if EVERY
    recorded socket type on that node side accepts the write."""
    smap = BPy_SOCKETS.get(node_cls.lower()) or {}
    stypes = [t for t in (smap.get(side[:-1] + "_types") or {}).values() if t]
    tmaps = [tm for tm in (BPy_TYPES.get(t.lower()) for t in stypes) if tm]
    if not tmaps:
        return None          # socket table has no type info -> don't guess
    for tm in tmaps:
        info = tm.get(attr)
        if info is None or info.get("readonly"):
            break
    else:
        return None           # writable on every socket type of that side
    names = smap.get(side) or []
    return (f"- {attr}: a {node_cls} socket has no writable '{attr}' property in this Mixar "
            f"build (socket value slots like values/vector/color are read-only aliases — the "
            f"engine kills the assignment). Address the slot BY NAME and set a writable "
            f"property of it, e.g. {node_cls.lower()}.{side}['<socket>'].default_value = "
            f"(r, g, b, a) — but only if that socket's type lists default_value in its "
            f"valid properties"
            + (f". Sockets on {node_cls}: {', '.join(names[:12])}." if names else "."))


# ============================================================
# ATTRIBUTE VALIDATOR  (single definition — truth table only)
# ============================================================
_TRUTH_SEP = "| valid properties:"


def _generic_socket_access_issue(attr, is_write):
    """Check a property access on a socket slot whose CONCRETE type is
    unknown: the owning node's class is absent from the socket table
    (e.g. a plain  for node in nodes  — node is the generic Node class),
    so the slot resolved to the bare NodeSocket base. That base entry is
    a strict subset of the concrete types (it lacks default_value in this
    build), so the verdict goes against the WHOLE socket family:
      read:  legal if ANY socket type has the attribute;
      write: legal if SOME socket type accepts it (the engine resolves
             the slot's real type at runtime); flagged only when NO
             socket type makes the access legal.
    Returns an issue string or None."""
    sock_maps = [tm for k, tm in BPy_TYPES.items() if k.startswith("nodesocket")]
    generic_set = BPy_ATTR_SETS.get("nodesocket") or set()
    if not sock_maps:
        # No socket type maps at all (memory-gated load or an older table).
        # The verdict here is about the whole socket FAMILY, and an empty
        # family proves nothing - it would call every socket write illegal.
        return None
    if attr not in generic_set:
        if not any(attr in tm for tm in sock_maps):
            return (f"- {attr}: no socket type in this Mixar build has a '{attr}' "
                    f"attribute - this slot access dies at runtime. Address the slot "
                    f"by name and use a property its type lists (e.g. default_value, "
                    f"hide, hide_value, enabled, description).")
        return None
    if not is_write:
        return None
    def _ok(tm):
        info = tm.get(attr)
        return isinstance(info, dict) and not info.get("readonly")
    if any(_ok(tm) for tm in sock_maps):
        return None
    return (f"- {attr}: no socket type in this Mixar build has a writable '{attr}' "
            f"property (socket value slots like values/vector/color are read-only "
            f"aliases - the engine kills the assignment). Address the slot BY NAME "
            f"and set a writable property of it, e.g. node.inputs['<socket>']"
            f".default_value = (r, g, b, a) - only if that socket's type lists "
            f"default_value in its valid properties.")


def validate_bpy_properties(script: str):
    """AST-scan the script; return a list of human-readable issues.

    EVERY attribute access (read or write) is resolved to a bpy.types class
    via the chain-walking resolver and checked against the binary-dumped
    dir() truth set. Socket-name subscripts are checked against the socket
    table; constant RHS values are checked for type/range/enum.
    No documentation search is involved — the truth table is the sole
    authority for this build."""
    _load_property_reference()
    issues, seen = [], set()

    def add(msg):
        if msg not in seen:
            seen.add(msg)
            issues.append(msg)

    try:
        tree = ast.parse(script)
    except SyntaxError:
        return []

    # ---- Pass 0: variable -> class tracking (source order) ----
    raw_events = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and node.value is not None:
            raw_events.append((node.lineno, node.col_offset, node.targets[0].id, "assign", node.value))
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            raw_events.append((node.lineno, node.col_offset, node.target.id, "iter", node.iter))
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            if node.generators and isinstance(node.generators[0].target, ast.Name):
                raw_events.append((node.lineno, node.col_offset,
                                   node.generators[0].target.id, "iter", node.generators[0].iter))
    var_class = {}
    var_colls = set()      # vars that hold a collection object (see _expr_is_collection)
    for _ln, _col, name, kind, value in sorted(raw_events):
        if kind == "assign":
            if _expr_is_collection(value, var_class):
                var_colls.add(name)
            else:
                var_colls.discard(name)
        cls = _elem_class(value, var_class) if kind == "iter" else _expr_class(value, var_class)
        if cls:
            var_class[name] = cls

    # socket variables born from  for s in <node>.inputs/outputs  (or from a
    # variable holding such a collection) — their concrete socket class is
    # unknowable, so their writes are checked against EVERY socket type of
    # that node side (see _socket_iter_write_issue).
    coll_socket_vars = {}    # var holding <node>.inputs/outputs -> (node_cls, side)
    for _ln, _col, name, kind, value in sorted(raw_events):
        if kind != "assign":
            continue
        root_v, parts_v = _parse_parent(value)
        if isinstance(root_v, str) and len(parts_v) == 1 and parts_v[0][0] == "attr" \
                and parts_v[0][1] in ("inputs", "outputs"):
            nclsv = var_class.get(root_v)
            if nclsv and nclsv.lower() in BPy_SOCKETS:
                coll_socket_vars[name] = (nclsv, parts_v[0][1])
    sock_iters = {}          # loop var name -> (node_cls, side)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.For) and isinstance(node.target, ast.Name)):
            continue
        it = node.iter
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) \
                and it.func.id == "list" and it.args:
            it = it.args[0]
        root, parts = _parse_parent(it)
        if not isinstance(root, str):
            continue
        if root in coll_socket_vars:
            sock_iters[node.target.id] = coll_socket_vars[root]
        elif len(parts) == 1 and parts[0][0] == "attr" and parts[0][1] in ("inputs", "outputs"):
            ncls = var_class.get(root)
            if ncls and ncls.lower() in BPy_SOCKETS:
                sock_iters[node.target.id] = (ncls, parts[0][1])

    # Map attribute-write targets -> their RHS value node (for type checks)
    assign_rhs = {}
    readonly_targets = {}   # id(leaf attr node of a WRITE TARGET) -> readonly issue text
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            tgt = node.targets[0] if len(node.targets) == 1 else None
        elif isinstance(node, ast.AugAssign):
            tgt = node.target
        else:
            tgt = None
        if tgt is not None and isinstance(tgt, ast.Attribute) and node.value is not None:
            assign_rhs[id(tgt)] = node.value
            try:
                root, parts = _parse_parent(tgt)
                cls_r, leaf_r = _state_of(root, parts, var_class)
                if cls_r and cls_r != _COLLECTED and leaf_r:
                    wi = _write_issue(cls_r, leaf_r)
                    if wi:
                        readonly_targets[id(tgt)] = wi
            except Exception:
                pass

    # ---- Pass 1: check every attribute access + socket subscript ----
    checked = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            root, parts = _parse_parent(node.value)
            if isinstance(root, str) and not parts and root in var_colls:
                continue   # holds a collection: .new/.remove/etc. are collection APIs
            if isinstance(root, str) and not parts and root in sock_iters:
                # socket from iteration: concrete type unknown -> only WRITEs
                # are checkable (against every socket type of that node side)
                if id(node) in assign_rhs or id(node) in readonly_targets:
                    ncls_i, side_i = sock_iters[root]
                    wi = _socket_iter_write_issue(ncls_i, side_i, node.attr)
                    if wi:
                        add(wi)
                continue
            cls, last = _state_of(root, parts, var_class)
            if cls is None or cls == _COLLECTED or last is not None:
                continue                     # parent not a known bpy class -> don't guess
            key = cls.lower()
            if key in TRUSTED_CLASSES:
                continue
            attr = node.attr
            if cls == _GENERIC_SOCKET:
                gi = _generic_socket_access_issue(attr, id(node) in assign_rhs)
                if gi:
                    add(gi)
                else:
                    checked += 1
                continue
            attrset = BPy_ATTR_SETS.get(key)
            if attrset is None:
                # The class name itself is not in the truth table — flag the class.
                close = get_close_matches(key, list(BPy_NAMES.keys()), n=3, cutoff=0.4)
                add(f"- bpy.types.{cls} is not a class in this Mixar build (cannot verify '{attr}')."
                    + (f" Did you mean: {', '.join(BPy_NAMES[c] for c in close)}?" if close else ""))
                continue
            if not attrset:
                continue   # class in truth table but zero recorded attrs -> nothing to verify
            if attr not in attrset:
                close = get_close_matches(attr, sorted(attrset), n=3, cutoff=0.45)
                add(f"- {attr}: bpy.types.{cls} has no attribute '{attr}' in this Mixar build."
                    + (f" Did you mean: {', '.join(close)}?" if close else ""))
                continue
            checked += 1
            # value type/range/enum on constant RHS
            rhs = assign_rhs.get(id(node))
            if rhs is not None:
                wi = _write_issue(cls, attr)
                if wi:
                    add(wi)
                    continue
                info = (BPy_TYPES.get(key) or {}).get(attr)
                if info:
                    t = _type_issue(cls, attr, info, rhs)
                    if t:
                        add(t)
            else:
                # deep write target (e.g. bpy.context.scene.display.shading = ...)
                if id(node) in readonly_targets:
                    add(readonly_targets[id(node)])
        elif isinstance(node, ast.For):
            # unscoped object-delete loop (the Mixar engine blocks it at runtime)
            it = node.iter
            if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) \
                    and it.func.id == "list" and it.args:
                it = it.args[0]
            names = _chain_names(it)
            if names in (["bpy", "data", "objects"],
                         ["bpy", "context", "view_layer", "objects"],
                         ["bpy", "context", "scene", "collection", "all_objects"]):
                removes = any(
                    isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "remove"
                    and _chain_names(c.func.value) == ["bpy", "data", "objects"]
                    for c in ast.walk(node))
                guarded = any(isinstance(s, ast.If) for s in node.body)
                if removes and not guarded:
                    add("- unscoped object-delete loop: the Mixar engine blocks it at runtime "
                         "with 'Blocked: unscoped delete' (bpy.data is shared by every scene in "
                         "this session). Rewrite it with a positive name guard - one of:\n"
                         "  (a) for n in ['Exact_Name_1', 'Exact_Name_2']:\n"
                         "        o = bpy.context.scene.objects.get(n)\n"
                         "        if o: bpy.data.objects.remove(o, do_unlink=True)\n"
                         "  (b) for obj in list(bpy.context.scene.collection.all_objects):\n"
                         "        if obj.name.startswith('Your_Prefix_'):\n"
                         "            bpy.data.objects.remove(obj, do_unlink=True)")
        elif isinstance(node, ast.Call):
            # bpy.ops.<category>.<op>(...) — operator NAME validation. The
            # attribute pass skips the dynamic bpy.ops tree (see _state_of),
            # so this is the only place operator names are checked.
            if isinstance(node.func, ast.Attribute):
                ochain = _chain_names(node.func)
                if len(ochain) >= 4 and ochain[0] == "bpy" and ochain[1] == "ops":
                    oi = _ops_issue(ochain[-2], ochain[-1])
                    if oi:
                        add(oi)
            # .new() on collections this build does not support (bpy.data.sounds.new, ...)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "new":
                names = _chain_names(node.func.value)
                if len(names) >= 3 and names[0] == "bpy" and names[1] == "data" \
                        and names[2] in NO_NEW_COLLECTIONS:
                    add(f"- bpy.data.{names[2]}.new: this collection has no .new in this Mixar build "
                         f"(Mixar kills the call at runtime). DELETE those lines - there are no sound "
                         f"data-blocks or audio emitters in this build; configure audio at scene level: "
                         f"scene.use_audio, scene.audio_volume, scene.audio_distance_model, "
                         f"scene.audio_doppler_factor, scene.audio_doppler_speed, scene.use_audio_scrub.")
                # typed-collection .new(): the type STRING must name a class that exists in
                # this build, or Mixar dies with "Node type X undefined" / a bad modifier type
                type_str = None
                if "nodes" in names:
                    # x.nodes.new('ShaderNodeBump') or nodes.new(type='...')
                    for kw in node.keywords:
                        if kw.arg in ("type", "bl_idname") and isinstance(kw.value, ast.Constant) \
                                and isinstance(kw.value.value, str):
                            type_str = kw.value.value
                    if type_str is None and node.args and isinstance(node.args[0], ast.Constant) \
                            and isinstance(node.args[0].value, str):
                        type_str = node.args[0].value
                elif "modifiers" in names:
                    # x.modifiers.new('Name', 'OCEAN') or new(name, type='...')
                    for kw in node.keywords:
                        if kw.arg == "type" and isinstance(kw.value, ast.Constant) \
                                and isinstance(kw.value.value, str):
                            type_str = kw.value.value
                    if type_str is None and len(node.args) >= 2 \
                            and isinstance(node.args[1], ast.Constant) \
                            and isinstance(node.args[1].value, str):
                        type_str = node.args[1].value
                if type_str and type_str[:1].isupper():
                    if "modifiers" in names:
                        t = re.sub(r"[-_ ]", "_", type_str.strip().upper())
                        cand = "".join(w[:1].upper() + w[1:].lower() for w in t.split("_") if w) + "Modifier"
                        key, label = cand.lower(), cand
                    else:
                        key, label = type_str.lower(), type_str
                    if key not in BPy_NAMES:
                        close = get_close_matches(key, list(BPy_NAMES.keys()), n=3, cutoff=0.4)
                        add(f"- {label}: {label} is not a class in this Mixar build "
                             f"(.new('{type_str}') fails at runtime with \"type undefined\")."
                             + (f" Did you mean: {', '.join(BPy_NAMES[c] for c in close)}?" if close else ""))

            # .normal_update(): the attribute is not on ANY class in the
            # binary-dumped truth table (the MeshPolygons collection class
            # is absent from this build), so every form of the call —
            # mesh.polygons.normal_update() or the per-polygon
            # "for f in mesh.polygons: f.normal_update()" the generation
            # model keeps emitting — dies at runtime with AttributeError.
            # Face normals derive from the face data itself (from_pydata()
            # already sets it up) — no explicit recompute call exists.
            if isinstance(node.func, ast.Attribute) and node.func.attr == "normal_update":
                add("- normal_update: no class in this Mixar build has normal_update() "
                    "(the MeshPolygons collection class is not in the binary-dumped truth "
                    "table), so mesh.polygons.normal_update() and per-polygon calls like "
                    "'for f in mesh.polygons: f.normal_update()' both crash at runtime "
                    "(AttributeError). DELETE the call — face normals are computed from "
                    "the face data set by from_pydata(), nothing else is needed.")

        elif isinstance(node, ast.Subscript):
            # socket-name validation + subscript-TARGET validation
            root, parts = _parse_parent(node.value)
            cls, last = _state_of(root, parts, var_class)
            if cls and cls != _COLLECTED and last in ("inputs", "outputs"):
                # socket-name validation:  someNode.inputs['...'] / outputs['...']
                if not (isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
                    continue
                smap = BPy_SOCKETS.get(cls.lower())
                if not smap:
                    continue         # generic Node or unmapped class -> can't verify
                names = smap.get(last) or []
                if names and node.slice.value not in names:
                    close = get_close_matches(node.slice.value, names, n=3, cutoff=0.4)
                    add(f"- {node.slice.value}: not an input/output socket on {cls}. "
                        f"Available sockets: {', '.join(names)}. "
                        + (f"Did you mean: {', '.join(close)}?" if close else ""))
            elif cls and cls != _COLLECTED and cls != _GENERIC_SOCKET:
                # existence (checked by the attribute pass) is not subscriptability:
                # methods, scalars and non-Id structs die at runtime when indexed
                t = _subscript_target_issue(cls, last, node)
                if t:
                    add(t)

    logger.info("Validated %d attribute access(es) against the Mixar truth table "
                "(%d classes, %d type maps, %d socket tables).",
                checked, len(BPy_ATTRS), len(BPy_TYPES), len(BPy_SOCKETS))
    return issues[:20]

# ============================================================
# MIXAR NORMALIZER — transform stock-Blender idioms into the
# equivalents this Mixar build actually accepts, BEFORE any gate
# runs. The gates below still validate the normalized script and
# catch whatever the normalizer cannot rewrite.
# ============================================================
def _socket_subscript(node):
    """True for <something>.inputs['name'] / <something>.outputs['name']."""
    return (isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr in ("inputs", "outputs")
            and isinstance(node.slice, ast.Constant))


def _dead_new_call(node):
    """True for the Call node itself: bpy.data.<unsupported collection>.new(...)"""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "new":
        names = _chain_names(node.func.value)
        if len(names) >= 3 and names[:2] == ["bpy", "data"] \
                and names[2] in NO_NEW_COLLECTIONS:
            return True
    return False


def normalize_mixar_script(script):
    """Rewrite known stock-Blender idioms into Mixar-accepted equivalents.

    Returns (script, notes). notes are human-readable transform reports
    (printed to the server log); an empty notes list means the script was
    returned byte-identical. Every rule mirrors a real error reproduced
    against mixar.exe:

    T1  socket .values = ...           -> socket .default_value = ...
         ONLY when the socket's CONCRETE type is resolvable from the truth
         table (node class + socket name) and that type actually has
         default_value in this build. Untyped sockets keep .values (it
         exists on every socket); a blind rewrite produced default_value on
         sockets that lack it (NodeSocketGeometry/Matrix/Shader, ...) which
         the gate then rejected.
    T2  bpy.data.sounds.new(...) usage -> lines deleted, scene-level
        audio inserted (no sound data-blocks in this build:
         attribute 'new' not found)
    T5  for X in *.polygons:  X.normal_update()  ->  loop replaced by pass
        (MeshPolygon has no normal_update in this build — it is a
        MeshPolygons collection API — and face normals are already
        derived from the from_pydata() face data, so the loops were
        runtime-fatal no-ops)
    """
    notes = []
    if not script or not script.strip():
        return script, notes
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return script, notes        # Gate 1 owns syntax errors

    changed = False

    # ---- T1: socket .values -> .default_value ----------------------------
    # Only when the CONCRETE socket type is known AND its truth-table entry
    # actually has default_value. A blind rewrite produced .default_value on
    # sockets that lack it (NodeSocketGeometry/Matrix/Shader/...) and on
    # untyped sockets the gate resolves to the base NodeSocket — which also
    # lacks default_value in this build — so the rewrite only ever made
    # scripts MORE likely to be rejected.
    node_class_of = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)):
            c = _infer_call_class(node.value)
            if c:
                node_class_of[node.targets[0].id] = c

    def _node_io_info(expr):
        """(node_class, 'inputs'|'outputs') for  <obj>.inputs / <obj>.outputs."""
        if not (isinstance(expr, ast.Attribute)
                and expr.attr in ("inputs", "outputs")):
            return None
        c = None
        if isinstance(expr.value, ast.Call):
            c = _infer_call_class(expr.value)
        elif isinstance(expr.value, ast.Name):
            c = node_class_of.get(expr.value.id)
        return (c, expr.attr) if c else None

    def _socket_info(expr):
        """(node_class, side, socket_name) for a socket expression, or None."""
        if isinstance(expr, ast.Subscript) and _socket_subscript(expr):
            info = _node_io_info(expr.value)
            if info:
                return (info[0], info[1], expr.slice.value)
        elif isinstance(expr, ast.Name) and expr.id in socket_vars:
            return socket_vars[expr.id]
        return None

    socket_vars = {}    # var name -> (node_class|None, side, socket_name)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and _socket_subscript(node.value)):
            info = _node_io_info(node.value.value)
            if info:
                socket_vars[node.targets[0].id] = (info[0], info[1], node.value.slice.value)
            else:
                socket_vars[node.targets[0].id] = (None, None, None)

    # socket variables born from  for s in <node>.inputs/outputs  — the
    # concrete slot is unknown, so the rewrite is allowed only when EVERY
    # socket type on that node side has default_value in this build.
    sock_iters = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            it = node.iter
            if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) \
                    and it.func.id == "list" and it.args:
                it = it.args[0]
            if isinstance(it, ast.Attribute) and it.attr in ("inputs", "outputs") \
                    and isinstance(it.value, ast.Name):
                c = node_class_of.get(it.value.id)
                if c and c.lower() in BPy_SOCKETS:
                    sock_iters[node.target.id] = (c, it.attr)

    def _has_dv(t):
        return "default_value" in (BPy_ATTR_SETS.get(t.lower()) or set())

    n_vals = n_keep = 0
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for tgt in targets:
            if not (isinstance(tgt, ast.Attribute) and tgt.attr == "values"):
                continue
            stypes = []
            info = _socket_info(tgt.value)
            if info:
                ncls, side, name = info
                if ncls and BPy_ATTR_SETS:
                    smap = BPy_SOCKETS.get(ncls.lower())
                    if smap:
                        st = (smap.get(side[:-1] + "_types") or {}).get(name)
                        if st:
                            stypes = [st]
            elif isinstance(tgt.value, ast.Name) and tgt.value.id in sock_iters:
                ncls, side = sock_iters[tgt.value.id]
                smap = BPy_SOCKETS.get(ncls.lower()) or {}
                stypes = [t for t in (smap.get(side[:-1] + "_types") or {}).values() if t]
            if not stypes:
                n_keep += 1     # type unconfirmed -> keep .values (always exists)
                continue
            if all(_has_dv(t) for t in stypes):
                tgt.attr = "default_value"
                n_vals += 1
            else:
                n_keep += 1     # some socket type on this side lacks default_value
    if n_vals:
        changed = True
        notes.append(f"{n_vals} socket .values assignment(s) rewritten to "
                     f".default_value (confirmed present on the socket type)")
    if n_keep:
        notes.append(f"{n_keep} socket .values assignment(s) left untouched "
                     f"(socket type not confirmed to have default_value)")

    # ---- T2: sound data-blocks -> scene-level audio -----------------------
    sounds_vars = set()
    bare_sounds = False
    for stmt in tree.body:
        for sub in ast.walk(stmt):
            if _dead_new_call(sub):
                bare_sounds = True
                if isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if isinstance(t, ast.Name):
                            sounds_vars.add(t.id)
    if bare_sounds:
        def _kills(stmt):
            if any(_dead_new_call(sub) for sub in ast.walk(stmt)):
                return True
            if isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Attribute) \
                            and isinstance(t.value, ast.Name) \
                            and t.value.id in sounds_vars:
                        return True
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                func = stmt.value.func
                if isinstance(func, ast.Attribute) \
                        and isinstance(func.value, ast.Name) \
                        and func.value.id in sounds_vars:
                    return True
            return False

        kept, n_dead = [], 0
        for stmt in tree.body:
            if _kills(stmt):
                n_dead += 1
                continue
            kept.append(stmt)
        if n_dead:
            if not re.search(r"\buse_audio\b", script):
                kept.append(ast.parse("bpy.context.scene.use_audio = True").body[0])
            changed = True
            notes.append(f"{n_dead} sound-data line(s) removed (no sound data-blocks "
                         f"in this build) - replaced with scene-level audio "
                         f"(bpy.context.scene.use_audio = True)")
        tree.body = kept

    # ---- T3: use_nodes (deprecated shim - node trees are always on) ------
    class _StripUseNodes(ast.NodeTransformer):
        def __init__(self):
            super().__init__()
            self.n = 0
        def _fix(self, st):
            if (isinstance(st, ast.Assign) and len(st.targets) == 1
                    and isinstance(st.targets[0], ast.Attribute)
                    and st.targets[0].attr == "use_nodes"):
                self.n += 1
                return None
            # containers that lost their only statement need repair
            if isinstance(st, ast.If) and not st.body:
                if st.orelse:
                    st.body = [ast.parse("pass").body[0]]
                else:
                    return None            # no-op if -> drop entirely
            if isinstance(st, (ast.For, ast.While, ast.Try)) and not st.body:
                st.body = [ast.parse("pass").body[0]]
            return st
        def generic_visit(self, node):
            node = super().generic_visit(node)
            for fname, value in ast.iter_fields(node):
                if (isinstance(value, list) and value
                        and isinstance(value[0], ast.stmt)):
                    setattr(node, fname,
                            [k for k in (self._fix(st) for st in value)
                             if k is not None])
            return node

    stripper = _StripUseNodes()
    tree = stripper.visit(tree)
    if stripper.n:
        changed = True
        notes.append(f"{stripper.n} use_nodes assignment(s) removed (node trees are "
                     f"always enabled in this build; the property is deprecated and warns "
                     f"at runtime)")

    # ---- T4: ocean modifier filmable floor -------------------------------
    # The small generation model copies the manual's example values
    # verbatim (resolution ~7, time 0, geometry_mode 'DISPLACE'), which
    # renders as a flat, nearly motionless quad. Enforce the filmable
    # floor deterministically:
    #   geometry_mode 'GENERATE'  ('DISPLACE' on a plain plane never waves)
    #   resolution >= 24          (the documented default is a preview grid)
    #   time > 0                  (at t=0 the wave field is exactly flat)
    ocean_fixes = []
    ocean_inserts = {}    # creation-stmt body index -> [stmts inserted after]
    for i, stmt in enumerate(tree.body):
        if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Call)):
            continue
        f = stmt.value.func
        if not (isinstance(f, ast.Attribute) and f.attr == "new"
                and isinstance(f.value, ast.Attribute)
                and f.value.attr == "modifiers"):
            continue
        if not any(isinstance(a, ast.Constant) and str(a.value) == "OCEAN"
                   for a in list(stmt.value.args)
                   + [k.value for k in stmt.value.keywords]):
            continue
        var = stmt.targets[0].id
        # Property writes reach the modifier two ways:  o.mod.X  when the
        # created modifier was stored in a local (var), or
        #  o.modifiers['Name'].X  by index. Follow both.
        var_aliases = {var}
        if isinstance(f.value.value, ast.Name):
            var_aliases.add(f.value.value.id)
        mod_names = {str(c.value) for c in stmt.value.args
                     if isinstance(c, ast.Constant)}
        if any(k.value is not None and isinstance(k.value, ast.Constant)
               for k in stmt.value.keywords):
            mod_names.add(str(stmt.value.keywords[0].value.value))

        def _is_mod_write(t):
            if (isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name)
                    and t.value.id in var_aliases):
                return True
            if (isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Subscript)
                    and isinstance(t.value.value, ast.Attribute)
                    and t.value.value.attr == "modifiers"
                    and isinstance(t.value.slice, ast.Constant)
                    and str(t.value.slice.value) in mod_names):
                return True
            return False

        seen = {"geometry_mode": False, "time": False}
        for s2 in tree.body:
            if not (isinstance(s2, ast.Assign) and len(s2.targets) == 1):
                continue
            t = s2.targets[0]
            if not (isinstance(t, ast.Attribute)
                    and _is_mod_write(t)):
                continue
            if t.attr in seen:
                seen[t.attr] = True
            if not isinstance(s2.value, ast.Constant):
                continue
            if t.attr == "geometry_mode" and s2.value.value != "GENERATE":
                s2.value.value = "GENERATE"
                ocean_fixes.append(f"{var}: geometry_mode -> 'GENERATE' "
                                   f"('DISPLACE' on a plain plane never waves)")
            elif t.attr == "time" and isinstance(s2.value.value, (int, float)) \
                    and not isinstance(s2.value.value, bool) \
                    and s2.value.value <= 0:
                s2.value.value = 5.0
                ocean_fixes.append(f"{var}: time set to 5.0 s "
                                   f"(t=0 renders a flat surface)")
            elif t.attr == "resolution" and isinstance(s2.value.value, (int, float)) \
                    and not isinstance(s2.value.value, bool) \
                    and s2.value.value < 24:
                s2.value.value = 24
                ocean_fixes.append(f"{var}: resolution raised to 24 "
                                   f"(the documented default renders a coarse grid)")
        insert = []
        if not seen["geometry_mode"]:
            insert.append(ast.parse(f"{var}.geometry_mode = 'GENERATE'").body[0])
            ocean_fixes.append(f"{var}: geometry_mode 'GENERATE' inserted")
        if not seen["time"]:
            insert.append(ast.parse(f"{var}.time = 5.0").body[0])
            ocean_fixes.append(f"{var}: time 5.0 s inserted "
                               f"(t=0 renders a flat surface)")
        if insert:
            ocean_inserts[i] = insert

    if ocean_fixes:
        new_body = []
        for i, stmt in enumerate(tree.body):
            new_body.append(stmt)
            new_body.extend(ocean_inserts.get(i, []))
        tree.body = new_body
        changed = True
        notes.extend(ocean_fixes)

    # ---- T5: per-polygon .normal_update() loop --------------------------
    # The generation model (trained on stock-Blender tutorials) emits
    #     for face in mesh.polygons:
    #         face.normal_update()
    # MeshPolygon has no normal_update() in this build — that is a
    # MeshPolygons COLLECTION method in stock Blender — so the per-polygon
    # form dies at runtime (AttributeError). The loop is a no-op anyway:
    # face normals derive from the from_pydata() face data. Replace it
    # with pass so the generated script runs.
    class _NormalUpdateLoopDrop(ast.NodeTransformer):
        n = 0
        def visit_For(self, node):
            node = self.generic_visit(node)
            it = node.iter
            if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) \
                    and it.func.id == "list" and it.args:
                it = it.args[0]
            if not (isinstance(it, ast.Attribute) and it.attr == "polygons"
                    and isinstance(node.target, ast.Name) and not node.orelse):
                return node
            if len(node.body) != 1:
                return node
            b = node.body[0]
            if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Call)):
                return node
            f = b.value.func
            if not (isinstance(f, ast.Attribute) and f.attr == "normal_update"
                    and isinstance(f.value, ast.Name)
                    and f.value.id == node.target.id
                    and not b.value.args and not b.value.keywords):
                return node
            self.n += 1
            p = ast.parse("pass").body[0]
            p.col_offset, p.end_col_offset = node.col_offset, node.end_col_offset
            return p

    dropper = _NormalUpdateLoopDrop()
    tree = dropper.visit(tree)
    if dropper.n:
        changed = True
        notes.append(f"{dropper.n} per-polygon normal_update() loop(s) removed "
                     f"(MeshPolygon has no normal_update in this build — it is a "
                     f"MeshPolygons collection API, and face normals are already "
                     f"derived from the from_pydata() face data, so the loops "
                     f"were no-ops)")

    if not changed:
        return script, notes
    ast.fix_missing_locations(tree)
    try:
        return ast.unparse(tree), notes
    except Exception:
        return script, notes        # never break a script we cannot re-emit


# ============================================================
# PUBLIC FACADE — normalize, then validate; the executor calls this
# exactly once per incoming script, before compilation.
#
# ADVISORY ONLY. See "SOFT GATE" in the module docstring: nothing returned
# here may decide whether a script runs.
# ============================================================

GATE_MODE = "soft"     # "soft" is the only supported shipped value

# Ceiling on how many issues ride back to the model in one result. The full
# list is always in the log; an agent script that invents 40 properties does
# not need 40 lines of advice repeating the same lesson.
MAX_REPORTED_ISSUES = 12


@dataclass(frozen=True)
class GateReport:
    """What the soft gate learned about one script. Never a verdict.

    normalized     — the script text to compile and run. Identical to the
                     input when no rule fired, so callers can pass the result
                     straight to the executor unconditionally.
    notes          — human-readable report of the rewrites applied (log only).
    issues         — attributes/sockets/operators that could not be confirmed
                     against the truth table. Advisory; carried to the model as
                     warnings, never as an error.
    syntax_error   — set when the normalized text does not parse. Reported, not
                     raised: the executor's own ``ast.parse`` produces the real
                     traceback, so the model still gets the usual signal.
    """

    normalized: str = ""
    notes: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    syntax_error: Optional[str] = None

    @property
    def clean(self) -> bool:
        """True when there is nothing worth telling the model."""
        return not self.issues and self.syntax_error is None

    @property
    def warnings(self) -> list[str]:
        """The issue list as carried on the execution result, capped."""
        shown = self.issues[:MAX_REPORTED_ISSUES]
        if len(self.issues) > len(shown):
            shown = shown + [
                f"... {len(self.issues) - len(shown)} further issue(s); "
                "see the Mixar log for the full list."
            ]
        return shown


def prepare_script(script) -> GateReport:
    """Normalize a Mixar script, then report on it. Never blocks, never raises.

    Every failure mode — no script, a rewrite that cannot be re-emitted, a
    corrupt truth table, a bug in this module — collapses to a GateReport
    carrying the ORIGINAL text, so the caller runs exactly what it was given.
    """
    if not isinstance(script, str) or not script.strip():
        return GateReport(normalized=script if isinstance(script, str) else "",
                          issues=[] if isinstance(script, str)
                          else ["No script provided."])

    try:
        normalized, notes = normalize_mixar_script(script)
    except Exception as exc:                       # noqa: BLE001 — advisory only
        logger.warning("Script normalization skipped (%s: %s)",
                       type(exc).__name__, exc)
        return GateReport(normalized=script,
                          issues=["Normalization was skipped: "
                                  f"{type(exc).__name__}: {exc}"])

    try:
        ast.parse(normalized)
    except SyntaxError as exc:
        # Reported, not raised: the executor parses too, and its traceback is
        # the signal the correction loop understands. Do not pre-empt it.
        return GateReport(normalized=normalized, notes=notes,
                          syntax_error=f"Syntax error at line {exc.lineno}: {exc.msg}",
                          issues=[f"Syntax error at line {exc.lineno}: {exc.msg}"])

    try:
        issues = validate_bpy_properties(normalized)
    except Exception as exc:                       # noqa: BLE001 — advisory only
        logger.warning("Attribute validation skipped (%s: %s)",
                       type(exc).__name__, exc)
        issues = []

    return GateReport(normalized=normalized, notes=notes, issues=list(issues))
