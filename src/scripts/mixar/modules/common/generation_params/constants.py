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
TYPE_BOOLEAN = "boolean"

# Prefix for the dynamic property attributes inside a generated
# PropertyGroup (avoids collisions with reserved names / leading digits).
PARAM_ATTR_PREFIX = "p_"

# Prefix for the WindowManager pointer attribute per (service, model).
WM_ATTR_PREFIX = "mixar_genparams_"

# Fallback bounds for unbounded numeric parameters (min/max may be null in
# the catalog → unbounded number field).
UNBOUNDED_INT_MIN = -(2**31)
UNBOUNDED_INT_MAX = 2**31 - 1
UNBOUNDED_FLOAT_MIN = -1.0e18
UNBOUNDED_FLOAT_MAX = 1.0e18
