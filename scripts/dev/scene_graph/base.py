# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""RelationLayer contract.

A layer reads the shared NodeRegistry and emits relation triplets
[subject_idx, object_idx, relation_type], read as
"nodes[subject] <relation_type> nodes[object]". Relation-type ids are
layer-local (start at 1); each triplet is decoded against its own layer's
legend, so layers never collide in id space.
"""


class RelationLayer:
    name = "base"
    relation_types = {}  # {int id: str name}

    def build(self, reg):
        """Return a list of [subject_idx, object_idx, relation_type] triplets."""
        raise NotImplementedError

    def legend(self):
        return {str(k): v for k, v in self.relation_types.items()}
