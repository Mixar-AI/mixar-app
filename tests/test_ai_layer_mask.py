# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generate Mask with AI: a brush_gen job (purpose=layer_mask) attached to its layer."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from mixar.bootstrap import generation_catalog_cache as CATALOG_CACHE
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.paint.core.layer import ai_layer_mask

ROOT = Path(__file__).resolve().parents[1] / "src" / "scripts" / "mixar" / "modules"


def _load_brush_model_items():
    """The dialog's real model items callback, run from source: importing
    ``paint.ui.ui_state`` would import (and register) the whole paint package."""
    tree = ast.parse((ROOT / "paint" / "ui" / "ui_state.py").read_text(encoding="utf-8"))
    nodes = [n for n in tree.body
             if (isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "NO_BRUSH_MODEL")
             or (isinstance(n, ast.FunctionDef) and n.name == "_get_brush_model_items")]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "ui_state.py", "exec"), namespace)
    return namespace["NO_BRUSH_MODEL"], namespace["_get_brush_model_items"]


NO_BRUSH_MODEL, _get_brush_model_items = _load_brush_model_items()


def _layer(tree="MPaint Tree", group_node="Layer Group 3", name="Rust"):
    return SimpleNamespace(id_data=SimpleNamespace(name=tree), group_node=group_node, name=name)


def test_enqueues_a_brush_gen_layer_mask_job():
    with patch("mixar.modules.common.job_queue.enqueue_generation") as enqueue:
        ai_layer_mask.enqueue_layer_mask(
            layer=_layer(), uv_name="UVMap", prompt="rust streaks",
            location="CAVITY", model="flash",
        )
    kwargs = enqueue.call_args.kwargs
    assert kwargs["job_type"] == "brush_gen"
    assert kwargs["feature_key"] == "layer_mask_gen"
    assert kwargs["kind"] == "image"
    assert kwargs["model"] == "flash"
    assert kwargs["payload"] == {
        "prompt": "rust streaks", "purpose": "layer_mask", "location_hint": "CAVITY",
    }


def test_anywhere_sends_no_location_hint():
    with patch("mixar.modules.common.job_queue.enqueue_generation") as enqueue:
        ai_layer_mask.enqueue_layer_mask(
            layer=_layer(), uv_name="UVMap", prompt="moss", location="ANY", model="pro",
        )
    assert "location_hint" not in enqueue.call_args.kwargs["payload"]


def test_result_is_attached_to_the_requested_layer():
    with patch("mixar.modules.common.job_queue.enqueue_generation") as enqueue:
        ai_layer_mask.enqueue_layer_mask(
            layer=_layer(), uv_name="UVMap", prompt="moss", location="ANY", model="pro",
        )
    on_imported = enqueue.call_args.kwargs["on_imported"]
    with patch.object(ai_layer_mask, "attach_mask_image") as attach:
        on_imported(MagicMock(), "layer_mask_moss, layer_mask_moss.001")
    attach.assert_called_once_with("MPaint Tree", "Layer Group 3", "UVMap", "layer_mask_moss")


def test_a_lost_layer_keeps_the_image_and_warns():
    with patch("mixar.modules.common.job_queue.enqueue_generation") as enqueue:
        ai_layer_mask.enqueue_layer_mask(
            layer=_layer(), uv_name="UVMap", prompt="moss", location="ANY", model="pro",
        )
    on_imported = enqueue.call_args.kwargs["on_imported"]
    with patch.object(ai_layer_mask, "attach_mask_image", side_effect=LookupError("gone")), \
            patch.object(ai_layer_mask, "find_layer", return_value=None), \
            patch.object(ai_layer_mask, "_notify_unattached") as notify:
        on_imported(MagicMock(), "layer_mask_moss")
    notify.assert_called_once_with(True)


def test_image_masks_menu_offers_the_operator():
    src = (ROOT / "paint" / "ui" / "operators" / "mask_operators.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    menu = next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "MASKS_MT_ImageMasksMenu")
    assert "wm.m_generate_layer_mask" in ast.unparse(menu)


def test_layer_mask_queue_is_mirrored_to_the_queue_panel():
    src = (ROOT / "common" / "job_queue" / "ui" / "properties" / "queue_properties.py"
           ).read_text(encoding="utf-8")
    features = src.split("_FEATURES = (", 1)[1].split(")", 1)[0]
    assert "FEATURE_LAYER_MASK_GEN" in features


def _class_src(rel_path, class_name):
    src = (ROOT / rel_path).read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.ClassDef) and n.name == class_name)
    return ast.unparse(node)


def test_layer_mask_operator_takes_the_agent_target():
    src = _class_src("paint/ui/mask/mask_generate_ai.py", "MGenerateLayerMask")
    assert "object_name: StringProperty" in src
    assert "layer_index: IntProperty" in src
    assert "_agent_target(self.object_name, self.layer_index)" in src
    assert "NO_BRUSH_MODEL" in src


def test_brush_operator_can_apply_its_result_and_refuses_without_models():
    src = _class_src("paint/ui/layer/utils/brush_gen_ops.py", "MGenerateBrushTexture")
    assert "apply_to_brush: bpy.props.BoolProperty" in src
    assert "on_imported=_apply_result_to_brush if self.apply_to_brush else None" in src
    assert "model_name == NO_BRUSH_MODEL" in src


def test_brush_model_list_fails_closed_without_a_catalog():
    src = (ROOT / "paint" / "ui" / "ui_state.py").read_text(encoding="utf-8")
    fn = src.split("def _get_brush_model_items", 1)[1].split("\nclass ", 1)[0]
    assert '"flash"' not in fn and '"pro"' not in fn
    assert "NO_BRUSH_MODEL" in fn


def test_matgen_operator_takes_catalog_model_and_apply_targets():
    src = _class_src("paint/ui/operators/matgen_ops.py", "MATGEN_OT_GenerateMaterial")
    for prop in ("model: StringProperty", "object_names: StringProperty",
                 "layer_name: StringProperty"):
        assert prop in src
    assert "apply_to_object_names=object_names" in src


# --- The dialog opens on the catalog's default model ---------------------------


@pytest.fixture
def catalog():
    """Install a generation catalog (None = not loaded); restored afterwards."""
    saved = CATALOG_CACHE._catalog

    def install(models):
        with CATALOG_CACHE._lock:
            CATALOG_CACHE._catalog = None if models is None else {
                "catalog_version": "mask-default-v1",
                "capabilities": [{"key": "image_gen", "services": [
                    {"key": "brush_gen", "surface": "paint", "models": models},
                ]}],
            }
            CATALOG_CACHE._bump_enum_version_locked()

    yield install
    with CATALOG_CACHE._lock:
        CATALOG_CACHE._catalog = saved
        CATALOG_CACHE._bump_enum_version_locked()


def _dialog_model():
    """The model the dialog's invoke preselects, from the real dropdown items."""
    return ai_layer_mask.default_model(item[0] for item in _get_brush_model_items(None, None))


def test_dialog_opens_on_the_catalog_default_not_the_first_sorted_model(catalog):
    catalog([{"slug": "pro", "label": "Gemini 3 Pro"},
             {"slug": "flash-3-1", "label": "Gemini 3.1 Flash", "is_default": True}])
    assert [item[0] for item in _get_brush_model_items(None, None)] == ["pro", "flash-3-1"]
    assert _dialog_model() == "flash-3-1"


def test_dialog_follows_a_default_moved_back_to_the_first_model(catalog):
    catalog([{"slug": "pro", "label": "Gemini 3 Pro", "is_default": True},
             {"slug": "flash-3-1", "label": "Gemini 3.1 Flash"}])
    assert _dialog_model() == "pro"


def test_without_a_published_default_the_dialog_opens_on_the_first_model(catalog):
    catalog([{"slug": "pro", "label": "Gemini 3 Pro"},
             {"slug": "flash-3-1", "label": "Gemini 3.1 Flash"}])
    assert _dialog_model() == "pro"


def test_a_default_the_dropdown_does_not_offer_falls_back_to_the_first_item():
    with patch.object(CATALOG_CACHE, "get_default_model_slug", return_value="retired"):
        assert ai_layer_mask.default_model(["pro", "flash-3-1"]) == "pro"
    with patch.object(CATALOG_CACHE, "get_default_model_slug", side_effect=RuntimeError):
        assert ai_layer_mask.default_model(["pro", "flash-3-1"]) == "pro"
    assert ai_layer_mask.default_model([]) is None


def test_without_a_catalog_the_dialog_stays_fail_closed(catalog):
    catalog(None)
    assert [item[0] for item in _get_brush_model_items(None, None)] == [NO_BRUSH_MODEL]
    assert _dialog_model() == NO_BRUSH_MODEL


def test_invoke_preselects_the_default_unless_the_caller_passed_a_model():
    src = _class_src("paint/ui/mask/mask_generate_ai.py", "MGenerateLayerMask")
    invoke = src.split("def invoke", 1)[1].split("def draw", 1)[0]
    # ghost=True (the default): the last run's remembered pick is not "passed",
    # so a reopened dialog returns to the catalog default.
    assert "is_property_set('model')" in invoke
    assert "ghost" not in invoke
    assert "default_model(" in invoke and "_get_brush_model_items(self, context)" in invoke
    assert invoke.index("self.model = model") < invoke.index("invoke_props_dialog")


# --- The duplicate check is per target layer ----------------------------------


def _label(tree="MPaint Cube", group_node="Layer Group 1",
           layer_name="Fill Layer", prompt="rust streaks"):
    return ai_layer_mask.job_label(tree_name=tree, group_node=group_node,
                                   layer_name=layer_name, prompt=prompt)


def test_same_named_layers_in_two_materials_get_distinct_labels():
    cube = _label()
    assert cube != _label(tree="MPaint Cube.001")
    # Another layer of the same stack.
    assert cube != _label(group_node="Layer Group 2")


def test_the_same_target_and_description_keep_one_label():
    assert _label() == _label()
    assert _label().startswith("Mask: Fill Layer: rust streaks [")
    assert _label() != _label(prompt="moss patches")


@pytest.fixture
def held_queue(monkeypatch):
    """A real layer-mask FeatureQueue held before submit (no network)."""
    queue = QM.FeatureQueue("layer_mask_gen")
    queue._auth_paused = True  # jobs stay PENDING: the dedup window stays open
    monkeypatch.setattr(QM, "get_queue", lambda _feature: queue)
    monkeypatch.setattr(QM.bpy.app.timers, "register", lambda *a, **k: None)
    return queue


def _enqueue_on(tree, prompt="rust streaks"):
    return ai_layer_mask.enqueue_layer_mask(
        layer=_layer(tree=tree, group_node="Layer Group 1", name="Fill Layer"),
        uv_name="UVMap", prompt=prompt, location="ANY", model="pro",
    )


def test_one_description_on_two_materials_queues_two_jobs(held_queue):
    first = _enqueue_on("MPaint Cube")
    second = _enqueue_on("MPaint Cube.001")
    assert first is not None and second is not None
    assert len(held_queue._jobs) == 2
    # The Queue shows the description only; the identity stays in the label.
    assert [job.display_label for job in held_queue._jobs] == ["rust streaks"] * 2


def test_the_same_target_twice_is_still_refused(held_queue):
    # Also two objects sharing one paint material (a linked duplicate): the
    # mask lands on the same layer, so the second request is the duplicate.
    assert _enqueue_on("MPaint Cube") is not None
    assert _enqueue_on("MPaint Cube") is None
    assert len(held_queue._jobs) == 1
