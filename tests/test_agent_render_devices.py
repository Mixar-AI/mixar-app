# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
from types import SimpleNamespace
import pytest

from mixar.modules.space_mixie_chat.core import render_devices as devices


def context():
    gpu = SimpleNamespace(name='Test GPU', type='METAL', use=False)
    cpu = SimpleNamespace(name='CPU', type='CPU', use=True)
    prefs = SimpleNamespace(compute_device_type='NONE', devices=[gpu,cpu], get_devices_for_type=lambda backend:[gpu,cpu])
    scene = SimpleNamespace(render=SimpleNamespace(engine='CYCLES'), cycles=SimpleNamespace(device='CPU'))
    ctx = SimpleNamespace(scene=scene, preferences=SimpleNamespace(addons={'cycles':SimpleNamespace(preferences=prefs)}))
    return ctx, prefs, gpu, cpu


def test_gpu_selection_restores_preferences_without_overwriting_user_change(monkeypatch):
    ctx,prefs,gpu,cpu = context()
    monkeypatch.setattr(devices,'cycles_inventory',lambda ctx:{'selected_backend':'NONE','devices':[{'name':'Test GPU','backend':'METAL'}]})
    saved=[]
    def set_value(owner,name,value):
        saved.append((owner,name,getattr(owner,name),value));setattr(owner,name,value)
    report=devices.select_device(ctx,set_value)
    assert report['device']=='GPU' and report['backend']=='METAL'
    assert report['actual_device'] is None  # Do not pretend configuration is hardware telemetry.
    assert ctx.scene.cycles.device=='GPU' and gpu.use and not cpu.use
    gpu.use=False  # User modifies this setting while the render runs.
    for owner,name,old,applied in reversed(saved):
        if getattr(owner,name)==applied:setattr(owner,name,old)
    assert prefs.compute_device_type=='NONE' and ctx.scene.cycles.device=='CPU'
    assert not gpu.use and cpu.use


@pytest.mark.parametrize('broken',[False,True])
def test_unavailable_gpu_falls_back_to_cpu(monkeypatch,broken):
    ctx,*_=context()
    ctx.scene.cycles.device='GPU'
    def inventory(ctx):
        if broken:raise RuntimeError('driver unavailable')
        return {'devices':[]}
    monkeypatch.setattr(devices,'cycles_inventory',inventory)
    result=devices.select_device(ctx,setattr)
    assert result['device']=='CPU' and ctx.scene.cycles.device=='CPU'
    assert result['fallback_reason']==('device_setup_failed' if broken else 'no_compatible_gpu')


def test_other_engines_keep_their_device_policy(monkeypatch):
    ctx,*_=context();ctx.scene.render.engine='BLENDER_EEVEE'
    monkeypatch.setattr(devices,'cycles_inventory',lambda ctx:pytest.fail('Cycles probe on another engine'))
    assert devices.select_device(ctx,setattr)['device']=='engine_default'


def test_newly_discovered_devices_are_disabled_after_restore(monkeypatch):
    ctx, prefs, gpu, cpu = context()
    prefs.devices = []
    gpu.use = True  # Cycles creates GPU preference entries enabled by default.
    monkeypatch.setattr(devices, 'cycles_inventory', lambda ctx: {
        'selected_backend': 'NONE', 'devices': [{'name': 'Test GPU', 'backend': 'METAL'}]})
    saved = []
    def set_value(owner, name, value):
        saved.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)
    assert devices.select_device(ctx, set_value)['device'] == 'GPU'
    assert gpu.use
    for owner, name, old in reversed(saved):
        setattr(owner, name, old)
    assert not gpu.use and not cpu.use
    assert ctx.scene.cycles.device == 'CPU'
