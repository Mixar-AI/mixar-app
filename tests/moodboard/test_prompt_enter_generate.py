# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Enter in an N-panel prompt runs that tab's Generate.

The node-graph work wired Enter for the CANVAS node prompt only, which
regressed the sidebar tabs: Enter there just confirmed the text. The C++
handler now forwards the prompt owner's RNA identifier to a Python
dispatcher; these pins keep the two sides and the drawer routing agreeing.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
HANDLERS = ROOT / "src/source/blender/editors/interface/interface_handlers.cc"

sys.path.insert(0, str(ROOT / "src/scripts"))

TAB_PROP_MODULES = (
    MOODBOARD / "ui/moodboard_tab_properties.py",
    MOODBOARD / "ui/moodboard_catalog_tab_props.py",
    MOODBOARD / "ui/moodboard_scene_recon_tab_props.py",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _prompt_submit():
    from mixar.modules.moodboard.core import prompt_submit

    return prompt_submit


def _prompt_owning_classes():
    owners = set()
    for path in TAB_PROP_MODULES:
        tree = ast.parse(_read(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                target = getattr(stmt, "target", None)
                if isinstance(stmt, ast.AnnAssign) and getattr(target, "id", "") == "prompt":
                    owners.add(node.name)
    return owners


def test_every_prompt_owning_tab_has_a_dispatch_entry():
    """A new tab that adds a ``prompt`` must wire its Enter routing too."""
    module = _prompt_submit()
    owners = _prompt_owning_classes()
    assert owners, "expected the tab property modules to declare prompts"
    missing = owners - set(module.PROMPT_TAB_DISPATCH)
    assert not missing, (
        f"tab PropertyGroups with a prompt but no Enter dispatch: {sorted(missing)}"
    )
    stale = set(module.PROMPT_TAB_DISPATCH) - owners
    assert not stale, f"dispatch entries without a prompt-owning tab: {sorted(stale)}"


def test_dispatch_targets_are_real_operator_idnames():
    """Every routed bl_idname must exist somewhere under the module tree."""
    module = _prompt_submit()
    scene = SimpleNamespace(mixie_moodboard_sidebar=SimpleNamespace())
    resolved = set()
    for owner in module.PROMPT_TAB_DISPATCH:
        operator_id, _props = module.resolve_prompt_generate(scene, owner)
        assert operator_id, f"{owner} resolved to no operator"
        resolved.add(operator_id)
    sources = "\n".join(
        _read(path)
        for path in (ROOT / "src/scripts/mixar/modules").rglob("*.py")
        if "ui/operators" in str(path).replace("\\", "/")
    )
    for operator_id in resolved:
        assert f'"{operator_id}"' in sources, (
            f"{operator_id} is not a registered operator bl_idname"
        )


def test_unknown_owner_resolves_to_nothing():
    module = _prompt_submit()
    scene = SimpleNamespace(mixie_moodboard_sidebar=SimpleNamespace())
    assert module.resolve_prompt_generate(scene, "SomeOtherGroup") == (None, None)
    assert module.resolve_prompt_generate(scene, "") == (None, None)


def test_mode_routed_tabs_follow_their_footer_tables():
    """Enter must submit through the operator the Generate button shows."""
    module = _prompt_submit()

    from mixar.modules.moodboard.ui.model_gen_drawer import _MODEL_GEN_FOOTER
    from mixar.modules.moodboard.ui.texture_gen_drawer import _TEXTURE_GEN_FOOTER

    source = _read(MOODBOARD / "core/prompt_submit.py")
    assert "_MODEL_GEN_FOOTER" in source and "_TEXTURE_GEN_FOOTER" in source, (
        "mode-routed tabs must resolve through the drawers' own footer tables"
    )
    # The tables themselves must still carry the operator per service key.
    assert _MODEL_GEN_FOOTER["model_3d"][2]
    assert _TEXTURE_GEN_FOOTER["pbr_gen"][0]


def test_cpp_handler_forwards_the_prompt_owner_to_the_dispatcher():
    """The Enter branch identifies sidebar prompts and never guesses a tab."""
    source = _read(HANDLERS)
    assert "MIXIE_OT_moodboard_prompt_generate" in source
    # Sidebar-only: the UI region gate keeps popup dialogs and the canvas out.
    assert "RGN_TYPE_UI" in source
    assert 'RNA_string_set(&submit_props, "owner_type"' in source
    # The canvas node branch must survive, with its explicit node id.
    assert "MIXIE_OT_moodboard_run_action_node" in source
    assert 'RNA_string_set(&run_props, "node_id", node_id.c_str())' in source


def test_dispatch_operator_is_registered_with_skip_save_owner():
    source = _read(MOODBOARD / "ui/operators/prompt_generate_ops.py")
    assert '"mixie.moodboard_prompt_generate"' in source
    assert "SKIP_SAVE" in source
    assert "INVOKE_DEFAULT" in source
    tree = ast.parse(source)
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    assert "MIXIE_OT_moodboard_prompt_generate" in classes
