# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read-only help for a node's saved catalog schema and displayed fields."""

import json
import math

from ..constants import PARAMETER_HELP_BY_LABEL


def parameter_specs(node):
    """Use the schema owning these fields, including offline saved nodes."""
    try:
        schema = json.loads(getattr(node, 'schema_json', '') or '{}')
    except (TypeError, ValueError):
        return {}
    specs = schema.get('parameters') if isinstance(schema, dict) else None
    return specs if isinstance(specs, dict) else {}


def _choices(parameter):
    try:
        choices = json.loads(getattr(parameter, 'choices_json', '') or '[]')
    except (TypeError, ValueError):
        return []
    return [choice for choice in choices if isinstance(choice, dict) and 'value' in choice] \
        if isinstance(choices, list) else []


def _display(value, choices):
    for choice in choices:
        if str(choice['value']) == str(value):
            return str(choice.get('label') or choice['value'])
    if isinstance(value, bool):
        return 'On' if value else 'Off'
    if isinstance(value, float):
        return f'{value:g}'
    return str(value) if value != '' else 'Empty'


def parameter_help(parameter, spec=None):
    """Explain purpose and valid input without inventing model capabilities."""
    spec = spec if isinstance(spec, dict) else {}
    label = parameter.label or parameter.name.replace('_', ' ').title()
    kind = parameter.parameter_type
    description = str(getattr(parameter, 'description', '') or '').strip()
    if not description:
        description = PARAMETER_HELP_BY_LABEL.get(' '.join(label.lower().split()), '')
    if not description:
        description = {
            'ENUM': 'Choose one of the options supported by this model.',
            'BOOLEAN': 'Turn this model setting on or off.',
            'INTEGER': 'Enter a whole number for this model setting.',
            'FLOAT': 'Enter a number for this model setting; decimal values are allowed.',
            'STRING': 'Enter text for this model setting.',
        }.get(kind, 'Configure this setting for the selected model.')
    parts = [label, description]
    choices = _choices(parameter)
    if kind == 'ENUM' and choices:
        parts.append('Options: ' + ', '.join(_display(c['value'], choices) for c in choices))
    if kind in {'INTEGER', 'FLOAT'}:
        low, high = parameter.minimum, parameter.maximum
        if low <= high:
            has_low = math.isfinite(low) and low > -1e17
            has_high = math.isfinite(high) and high < 1e17
            if has_low and has_high:
                parts.append(f'Range: {low:g} to {high:g}')
            elif has_low:
                parts.append(f'Minimum: {low:g}')
            elif has_high:
                parts.append(f'Maximum: {high:g}')
    if 'default' in spec and spec['default'] is not None:
        parts.append('Default: ' + _display(spec['default'], choices))
    if getattr(parameter, 'required', False):
        parts.append('Required for generation.')
    return '\n\n'.join(parts)
