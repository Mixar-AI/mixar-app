# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read-only help for a node's saved catalog schema and displayed fields."""

import json
import math

from mixar.modules.common.i18n import n_, tip_
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
        return tip_('On') if value else tip_('Off')
    if isinstance(value, float):
        return f'{value:g}'
    return str(value) if value != '' else tip_('Empty')


def _sentence(text):
    text = text.strip()
    return text if text.endswith(('.', '!', '?')) else text + '.'


def parameter_help(parameter, spec=None):
    """One hover tooltip: what the field does, then its valid input.

    The dropdown already lists an enum's options, so they are not repeated.
    Never invents a range or default the saved schema does not carry.
    """
    spec = spec if isinstance(spec, dict) else {}
    label = parameter.label or parameter.name.replace('_', ' ').title()
    kind = parameter.parameter_type
    description = str(getattr(parameter, 'description', '') or '').strip()
    if not description:
        description = tip_(PARAMETER_HELP_BY_LABEL.get(' '.join(label.lower().split()), ''))
    if not description:
        description = tip_({
            'ENUM': n_('Choose one of the options supported by this model.'),
            'BOOLEAN': n_('Turn this model setting on or off.'),
            'INTEGER': n_('Enter a whole number for this model setting.'),
            'FLOAT': n_('Enter a number for this model setting; decimal values are allowed.'),
            'STRING': n_('Enter text for this model setting.'),
        }.get(kind, n_('Configure this setting for the selected model.')))
    parts = [description]
    choices = _choices(parameter)
    if kind in {'INTEGER', 'FLOAT'}:
        low, high = parameter.minimum, parameter.maximum
        if low <= high:
            has_low = math.isfinite(low) and low > -1e17
            has_high = math.isfinite(high) and high < 1e17
            if has_low and has_high:
                parts.append(tip_('Range: {low:g} to {high:g}').format(low=low, high=high))
            elif has_low:
                parts.append(tip_('Minimum: {low:g}').format(low=low))
            elif has_high:
                parts.append(tip_('Maximum: {high:g}').format(high=high))
    if 'default' in spec and spec['default'] is not None:
        parts.append(tip_('Default: {value}').format(value=_display(spec['default'], choices)))
    if getattr(parameter, 'required', False):
        parts.append(tip_('Required for generation'))
    return ' '.join(_sentence(part) for part in parts)
