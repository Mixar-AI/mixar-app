# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Public MCP review requires explicit, accurate safety annotations."""

from mixar.modules.common.ui_control.core import schema


def test_local_catalog_has_explicit_submission_annotations():
    tools = {tool["name"]: tool for tool in schema.tools()}
    for tool in tools.values():
        annotations = tool["annotations"]
        for hint in ("readOnlyHint", "destructiveHint", "openWorldHint"):
            assert type(annotations[hint]) is bool, (tool["name"], hint)
        if annotations["readOnlyHint"]:
            assert not annotations["destructiveHint"], tool["name"]
    # UI input can activate arbitrary add-ons and file destinations. The other
    # operations are limited to desktop state and the user's recent projects.
    assert tools["mixar_ui_act"]["annotations"]["openWorldHint"] is True
    assert all(not tool["annotations"]["openWorldHint"]
               for name, tool in tools.items() if name != "mixar_ui_act")
