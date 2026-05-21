# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Utility functions for vector displacement map operations."""


def create_link(tree, out, inp):
    """Create a node link if it doesn't already exist.

    Args:
        tree: Node tree containing the nodes.
        out: Output socket to link from.
        inp: Input socket to link to.

    Returns:
        NodeOutputs or None: The outputs of the input node if it exists, None otherwise.
    """
    if not any(l for l in out.links if l.to_socket == inp):
        tree.links.new(out, inp)
    if inp.node:
        return inp.node.outputs
    return None
