# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the schema-driven generation parameter engine."""

# Widget kinds the backend catalog may specify per parameter.
WIDGET_DROPDOWN = "dropdown"
WIDGET_SLIDER = "slider"
WIDGET_TOGGLE = "toggle"
WIDGET_TEXT = "text"
WIDGET_NUMBER = "number"
WIDGET_SEGMENTED = "segmented"

# Parameter value types the backend catalog may specify.
TYPE_STRING = "string"
TYPE_INTEGER = "integer"
TYPE_NUMBER = "number"
TYPE_FLOAT = "float"
TYPE_BOOLEAN = "boolean"
# A list of published choices (``items.enum`` / ``choices``), rendered as a
# searchable multi-select and collected as a list — see core/multi_select.py.
TYPE_ARRAY = "array"

# Suffix of the hidden per-list active-row IntProperty beside a multi-select
# collection attribute (``p_<name>`` + this); template_list needs one.
MULTI_SELECT_ACTIVE_SUFFIX = "__active"
# The shared UIList that draws every multi-select (ui/lists/choice_list.py).
MULTI_SELECT_LIST_ID = "MIXAR_UL_genparams_choices"

# The backend validator treats "float" and "number" as the same numeric
# type; keep the client in sync so a "float" param renders as a real
# FloatProperty (and is sent as a number) instead of a text field/string.
FLOAT_TYPES = (TYPE_NUMBER, TYPE_FLOAT)

# Prefix for the dynamic property attributes inside a generated
# PropertyGroup (avoids collisions with reserved names / leading digits).
PARAM_ATTR_PREFIX = "p_"

# Prefix for the WindowManager pointer attribute per (service, model).
WM_ATTR_PREFIX = "mixar_genparams_"

# Hidden StringProperty on each generated group: JSON object mapping RNA
# attr (`p_*`) → {other RNA attr: expected text}. FloatProperty conditions
# validate Python str equality before using lossless .17g transport; all
# other values use str(expected). Native strips match `is_param_visible`.
# Must not start with `_` — Blender RNA refuses those identifiers, which
# would drop every generated param group. Must not use `p_` either, or
# native strips would treat it as a catalog chip.
VISIBLE_IF_ATTR = "mixar_visible_if"
VISIBLE_IF_MAXLEN = 65536
# Sentinel inner key when a `visible_if` names a param the group does not
# have — C++ and Python both fail closed (hide).
VISIBLE_IF_MISSING = "__missing__"

# Fallback bounds for unbounded numeric parameters (min/max may be null in
# the catalog → unbounded number field).
UNBOUNDED_INT_MIN = -(2**31)
UNBOUNDED_INT_MAX = 2**31 - 1
UNBOUNDED_FLOAT_MIN = -1.0e18
UNBOUNDED_FLOAT_MAX = 1.0e18

# The selected model's catalog description is drawn as muted wrapped lines
# under a Model dropdown (core/draw.py:draw_model_description), measured to
# the host's width less MODEL_DESCRIPTION_MARGIN (UI units: popup/box padding
# plus the label's own inset). Columns are the fallback when the width or the
# font cannot be measured.
MODEL_DESCRIPTION_MARGIN = 40
MODEL_DESCRIPTION_WRAP_COLUMNS = 32
MODEL_DESCRIPTION_SCALE_Y = 0.8
