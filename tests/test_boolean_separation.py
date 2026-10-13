# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Conservative cutter separation before the native Manifold fast path."""
import itertools
import numpy as np

from mixar.modules.common.agent_execution.boolean_prepare import bounds_overlap


def test_tilted_disjoint_cutters_can_have_overlapping_world_boxes():
    c=np.sqrt(.5)
    rotation=np.array([[c,-c,0],[c,c,0],[0,0,1]])
    a=np.array(list(itertools.product([-.1,.1],[-4,4],[-.1,.1]))) @ rotation.T
    b=a+rotation[:,0]*.3
    assert np.all(a.min(axis=0)<b.max(axis=0)) and np.all(b.min(axis=0)<a.max(axis=0))
    assert not bounds_overlap([a,b],[rotation.T,rotation.T])
    assert bounds_overlap([a,a+rotation[:,0]*.15],[rotation.T,rotation.T])


def test_containment_touching_and_concave_uncertainty_keep_exact():
    a=np.array(list(itertools.product([-1,1],repeat=3)),dtype=float)
    for b in (a*.5, a+[2,0,0], a.copy()):
        assert bounds_overlap([a,b],[np.eye(3)]*2)


def test_all_pairs_must_be_separated_and_world_offsets_do_not_change_result():
    a=np.array(list(itertools.product([-1,1],repeat=3)),dtype=float)
    for offset in (0, 1e8):
        assert not bounds_overlap([a+offset,a+offset+[3,0,0],a+offset+[6,0,0]],[np.eye(3)]*3)
        assert bounds_overlap([a+offset,a+offset+[3,0,0],a+offset+[4,0,0]],[np.eye(3)]*3)
