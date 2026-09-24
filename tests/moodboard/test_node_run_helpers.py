# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Generic run rules: upstream readiness, label-named images, frame growth."""

import ast
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from mixar.modules.moodboard.core import node_run_helpers as helpers

MOODBOARD = Path(__file__).resolve().parents[2] / "src/scripts/mixar/modules/moodboard"


def _action(node_id, action_type='IMAGE_GEN', **kwargs):
    values = dict(node_id=node_id, action_type=action_type, label="", state='DRAFT',
                  preview_image=None, preview_object=None, result_names="", frame_id="")
    values.update(kwargs)
    return NS(**values)


def _scene(nodes, links=()):
    return NS(mixie_moodboard_action_nodes=list(nodes), mixie_moodboard_images=[],
              mixie_moodboard_asset_nodes=[], mixie_moodboard_links=list(links))


def _link(from_id, to_id):
    return NS(from_node_id=from_id, to_node_id=to_id)


def test_producer_ready_rules():
    scene = _scene([
        _action("draft"),
        _action("done", state='SUCCESS'),
        _action("image", state='FAILED', preview_image=object()),
        _action("mesh", state='QUEUED', preview_object=object()),
        _action("named", state='CANCELLED', result_names=" Talwar "),
        _action("blank", state='FAILED', result_names="  "),
    ])
    # Media and asset cards are their own content.
    assert helpers.producer_ready(scene, "a-media-id")
    assert not helpers.producer_ready(scene, "draft")
    assert not helpers.producer_ready(scene, "blank")
    for ready in ("done", "image", "mesh", "named"):
        assert helpers.producer_ready(scene, ready), ready


def test_unready_producer_is_named_in_the_refusal():
    target = _action("target", 'MODEL_3D')
    running = _action("ref", label="Body", state='RUNNING')
    scene = _scene([running, target], [_link("ref", "target")])
    with pytest.raises(ValueError) as refused:
        helpers.require_upstream_results(scene, target)
    assert str(refused.value) == "Wait for 'Body' to finish — this card uses its result"

    running.state = 'DRAFT'
    running.label = ""
    with pytest.raises(ValueError) as refused:
        helpers.require_upstream_results(scene, target)
    assert str(refused.value) == "Generate 'Generate Image' first — this card uses its result"

    running.state = 'SUCCESS'
    helpers.require_upstream_results(scene, target)


def test_media_sources_and_other_cards_links_never_block():
    target = _action("target")
    other = _action("other")
    scene = _scene([_action("ref"), target, other],
                   [_link("media", "target"), _link("ref", "other")])
    helpers.require_upstream_results(scene, target)


def test_assemble_skips_ungenerated_parts_itself():
    assemble = _action("asm", 'ASSEMBLE')
    scene = _scene([_action("part", 'MODEL_3D', state='QUEUED'), assemble],
                   [_link("part", "asm")])
    helpers.require_upstream_results(scene, assemble)


def test_label_becomes_the_image_name():
    assert helpers.label_image_name(NS(label="Right-hand item")) == "Right_hand_item"
    assert helpers.label_image_name(NS(label="   ")) == ""
    assert helpers.label_image_name(NS(label="")) == ""
    assert len(helpers.label_image_name(NS(label="x" * 200))) == helpers.IMAGE_NAME_MAXLEN


def test_frame_grows_only_for_framed_cards(monkeypatch):
    from mixar.modules.moodboard.core import frames

    calls = []
    monkeypatch.setattr(frames, "grow_frames_to_fit_members",
                        lambda scene, ids: calls.append((scene, ids)))
    scene = object()
    helpers.grow_owner_frame(scene, _action("loose"))
    assert calls == []
    helpers.grow_owner_frame(scene, _action("framed", frame_id="frame-1"))
    assert calls == [(scene, ["frame-1"])]


def _function_source(name: str) -> str:
    tree = ast.parse((MOODBOARD / "core/node_execution.py").read_text(encoding="utf-8"))
    return ast.unparse(next(node for node in ast.walk(tree)
                            if isinstance(node, ast.FunctionDef) and node.name == name))


def test_execution_applies_the_run_rules():
    run = _function_source("run_action_node")
    assert run.index("node.error = ''") < run.index(
        "require_upstream_results(context.scene, node)") < run.index("_run_image(")

    image = _function_source("_run_image")
    guard = image.index("getattr(node, 'requires_reference', False) and (not references)")
    assert image.index("references = [") < guard < image.index("enqueue_generation(")
    assert "Connect your character sheet to this card first" in image
    named = image.index("payload['image_name'] = name")
    assert image.index("name = label_image_name(node)") < named < image.index(
        "enqueue_generation(")
    assert "label=f'ImageNode:{node.node_id[:8]}:" in image

    hook = _function_source("_result_hook")
    image_branch = hook.split("elif kind == 'IMAGE':")[1]
    assert image_branch.count("grow_owner_frame(scene, node)") == 2
    assert "return final" in hook
