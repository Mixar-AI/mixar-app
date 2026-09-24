# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Help survives sparse/offline catalogs without inventing model constraints."""

import json
from types import SimpleNamespace

import pytest

from mixar.modules.moodboard.core.parameter_help import parameter_help, parameter_specs


def parameter(**overrides):
    fields = dict(name='custom', label='Custom', description='', parameter_type='ENUM',
                  choices_json='[]', minimum=-1e18, maximum=1e18, required=False)
    return SimpleNamespace(**(fields | overrides))


def test_sparse_aspect_ratio_explains_shape_and_uses_catalog_labels():
    field = parameter(label='Aspect Ratio', choices_json=json.dumps([
        {'value': 'square', 'label': '1:1'}, {'value': 'wide', 'label': '16:9'}]))
    help_text = parameter_help(field, {'default': 'wide'})
    assert 'width:height' in help_text
    assert 'Options: 1:1, 16:9' in help_text
    assert 'Default: 16:9' in help_text
    assert 'square' not in help_text


def test_model_specific_description_wins_over_generic_explanation():
    description = 'Text-to-video only; reference images determine the output shape.'
    help_text = parameter_help(parameter(label='Aspect Ratio', description=description))
    assert description in help_text
    assert 'Wider ratios' not in help_text


@pytest.mark.parametrize(('kind', 'instruction'), [
    ('ENUM', 'Choose one'), ('BOOLEAN', 'on or off'), ('INTEGER', 'whole number'),
    ('FLOAT', 'decimal values'), ('STRING', 'Enter text'),
])
def test_new_catalog_fields_have_help_without_assuming_semantics(kind, instruction):
    help_text = parameter_help(parameter(label='New Model Setting', parameter_type=kind))
    assert instruction in help_text
    assert 'Default:' not in help_text
    assert 'Range:' not in help_text


@pytest.mark.parametrize(('bounds', 'expected'), [
    ((1, 4), 'Range: 1 to 4'), ((3, 1e18), 'Minimum: 3'),
    ((-1e18, 8), 'Maximum: 8'),
])
def test_numeric_help_handles_two_sided_and_one_sided_bounds(bounds, expected):
    help_text = parameter_help(parameter(parameter_type='FLOAT', minimum=bounds[0],
                                         maximum=bounds[1]))
    assert expected in help_text
    assert '1e+18' not in help_text


@pytest.mark.parametrize('bounds', [(4, 1), (float('nan'), 2), (-1e18, 1e18)])
def test_invalid_and_unbounded_ranges_are_not_advertised(bounds):
    help_text = parameter_help(parameter(parameter_type='FLOAT', minimum=bounds[0],
                                         maximum=bounds[1]))
    assert not any(word in help_text for word in ('Range:', 'Minimum:', 'Maximum:'))


@pytest.mark.parametrize(('value', 'expected'), [(False, 'Off'), (True, 'On'), (0, '0'), ('', 'Empty')])
def test_false_and_zero_are_valid_catalog_defaults(value, expected):
    assert f'Default: {expected}' in parameter_help(parameter(), {'default': value})


@pytest.mark.parametrize('choices', ['not json', '{}', 'null', '[null, 0, {}]'])
def test_malformed_saved_choices_do_not_break_settings(choices):
    help_text = parameter_help(parameter(choices_json=choices, required=True))
    assert 'Options:' not in help_text
    assert 'Required for generation.' in help_text


def test_help_reads_saved_schema_and_does_not_mutate_values():
    node = SimpleNamespace(schema_json=json.dumps({'parameters': {'custom': {'default': 0}}}))
    field = parameter(value_integer=7)
    original = vars(field).copy()
    assert 'Default: 0' in parameter_help(field, parameter_specs(node)['custom'])
    assert vars(field) == original


@pytest.mark.parametrize('schema', ['not json', 'null', '[]', '{"parameters": []}'])
def test_malformed_saved_schema_keeps_help_available(schema):
    assert parameter_specs(SimpleNamespace(schema_json=schema)) == {}
