# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Node utility functions for baking operations"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def copy_default_value(inp_source, inp_target):
    """Copy default value between node inputs with type conversion.

    Parameters:
        inp_source: Source node input socket
        inp_target: Target node input socket

    Returns:
        None
    """
    if inp_target.bl_idname == inp_source.bl_idname:
        inp_target.default_value = inp_source.default_value
    elif isinstance(inp_target.default_value, float) and isinstance(
        inp_source.default_value, float
    ):
        inp_target.default_value = inp_source.default_value
    elif isinstance(inp_target.default_value, float):
        avg = sum([inp_source.default_value[i] for i in range(3)]) / 3
        inp_target.default_value = avg
    elif isinstance(inp_source.default_value, float):
        for i in range(3):
            inp_target.default_value[i] = inp_source.default_value


def connect_to_original_node(mtree, outp, ori_to):
    """Reconnect output socket to original destination nodes.

    Parameters:
        mtree: Node tree to work in
        outp: Output socket to connect from
        ori_to: List of original connection data

    Returns:
        None
    """
    for con in ori_to:
        node = mtree.nodes.get(con.node)
        if not node:
            continue
        # Some mix inputs has same name so use index instead
        if node.type == "MIX":
            try:
                mtree.links.new(outp, node.inputs[con.socket_index])
            except Exception as e:
                logger.error("Error linking node: %s", e)
        else:
            try:
                mtree.links.new(outp, node.inputs[con.socket])
            except Exception as e:
                logger.error("Error linking node: %s", e)
