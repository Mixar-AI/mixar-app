# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
import numpy as np
import pytest
from mixar.modules.asset_search.core.scatter_sampling import sample_surface, validate_layers

V = [[0,0,0], [10,0,0], [10,10,0], [0,10,0]]
T = [[0,1,2], [0,2,3]]


def test_sampling_is_deterministic_and_surface_bound():
    a, normals = sample_surface(V, T, count=150, seed=73)
    b, _ = sample_surface(V, T, count=150, seed=73)
    assert np.array_equal(a,b) and len(a) == 150
    assert np.all(a[:,:2] >= 0) and np.all(a[:,:2] <= 10)
    assert np.all(a[:,2] == 0) and np.all(normals[:,2] == 1)


def test_minimum_distance_is_enforced_and_bounded():
    pts, _ = sample_surface(V,T,count=100,seed=1,min_distance=3)
    distance = np.linalg.norm(pts[:,None,:]-pts[None,:,:],axis=2)
    np.fill_diagonal(distance,np.inf)
    assert np.min(distance) >= 3 and 0 < len(pts) < 100


def test_empty_masks_fail_instead_of_placing_everywhere():
    with pytest.raises(ValueError, match='No surface'):
        sample_surface(V,T,count=20,weights=[0,0,0,0])
    with pytest.raises(ValueError, match='No surface'):
        sample_surface(V,T,count=20,slope=[10,40])


def test_mask_density_is_interpolated_inside_triangles():
    points, _ = sample_surface([[0,0,0],[1,0,0],[0,1,0]], [[0,1,2]],
                              count=6000, seed=42, weights=[0,1,0])
    # Linear density proportional to x has E[x]=1/2, E[y]=1/4.
    # Face-average-only sampling would incorrectly produce E[x]=E[y]=1/3.
    assert abs(points[:,0].mean()-.5) < .015
    assert abs(points[:,1].mean()-.25) < .015


@pytest.mark.parametrize('patch', [{'count':-1},{'count':True},{'scale':[1,float('nan')]},
    {'slope':[80,20]},{'min_distance':-1},{'revision':''},{'scale':[1]}])
def test_bad_recipes_fail_before_scene_mutation(patch):
    with pytest.raises(ValueError):
        validate_layers([{'asset_id':'asset','revision':'v1',**patch}])


def test_duplicate_layer_ids_are_rejected():
    with pytest.raises(ValueError, match='unique'):
        validate_layers([{'id':'trees','asset_id':'one','revision':'v1'},
                         {'id':'trees','asset_id':'two','revision':'v1'}])
