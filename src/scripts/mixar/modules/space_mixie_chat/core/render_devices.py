# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded hardware facts and temporary Cycles device selection, on the main thread."""
import os
import platform

import bpy

PRIORITY = ('OPTIX', 'METAL', 'HIP', 'ONEAPI', 'CUDA')


def cycles_inventory(context):
    """Enumerate without changing selected preferences or enabling devices."""
    addon = context.preferences.addons.get('cycles')
    if addon is None:
        return {'backends': [], 'devices': [], 'reason': 'cycles_unavailable'}
    prefs = addon.preferences
    import _cycles
    backends = [item[0] for item in prefs.get_device_types(context) if item[0] != 'NONE']
    enabled = {(d.name, d.type): bool(d.use) for d in prefs.devices}
    devices, errors = [], []
    for backend in backends:
        try:
            for device in _cycles.available_devices(backend):
                if device[1] != 'CPU':
                    devices.append({'name': device[0], 'backend': device[1],
                                    'enabled': enabled.get((device[0], device[1]), False)})
        except Exception:
            errors.append(backend)
    return {'backends': backends, 'devices': devices[:32],
            'selected_backend': prefs.compute_device_type, 'unavailable_backends': errors}


def system_info(context):
    scene = context.scene
    memory = None
    try:
        import psutil
        memory = psutil.virtual_memory().total
    except (ImportError, OSError):
        try:
            memory = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
        except (ValueError, OSError, AttributeError):
            pass
    try:
        inventory = cycles_inventory(context)
    except Exception:
        inventory = {'backends': [], 'devices': [], 'reason': 'device_probe_failed'}
    return {'available': True, 'blender_version': bpy.app.version_string,
            'os': platform.system(), 'architecture': platform.machine(),
            'cpu': platform.processor() or platform.machine(), 'cpu_threads': os.cpu_count(),
            'ram_bytes': memory, 'gpu': inventory,
            'render': {'engine': scene.render.engine, 'cycles_device': scene.cycles.device,
                       'resolution': [scene.render.resolution_x, scene.render.resolution_y],
                       'percentage': scene.render.resolution_percentage,
                       'samples': scene.cycles.samples, 'denoising': scene.cycles.use_denoising},
            'preview': {'async': True, 'max_edge': 768, 'max_samples': 32,
                        'device_policy': 'prefer_compatible_gpu', 'device_reporting': 'selected_configuration'}}


def select_device(context, set_value):
    """Resolve available GPU before starting; restore recorded fields after teardown.

    Cycles exposes configured devices, not per-job hardware telemetry. Report
    that distinction instead of pretending a driver-level fallback was measured.
    """
    scene = context.scene
    report = {'engine': scene.render.engine, 'device': 'engine_default',
              'actual_device': None, 'device_source': 'selected_configuration',
              'devices': [], 'fallback_reason': None}
    if scene.render.engine != 'CYCLES':
        return report
    try:
        inventory = cycles_inventory(context)
        prefs = context.preferences.addons['cycles'].preferences
        candidates = [inventory.get('selected_backend'), *PRIORITY]
        for backend in dict.fromkeys(candidates):
            available = {d['name'] for d in inventory['devices'] if d['backend'] == backend}
            if not available:
                continue
            existing = {(d.name, d.type) for d in prefs.devices}
            devices = prefs.get_devices_for_type(backend)
            # Enumeration creates preference entries. Newly discovered devices
            # had no enabled flag before this job; leave them disabled afterward.
            for device in devices:
                if (device.name, device.type) not in existing:
                    device.use = False
            selected = [d for d in devices if d.type == backend and d.name in available]
            if not selected:
                continue
            set_value(prefs, 'compute_device_type', backend)
            for device in devices:
                set_value(device, 'use', device.type == backend and device.name in available)
            set_value(scene.cycles, 'device', 'GPU')
            report.update(device='GPU', backend=backend, devices=[d.name for d in selected])
            return report
        report['fallback_reason'] = 'no_compatible_gpu'
    except Exception:
        report['fallback_reason'] = 'device_setup_failed'
    set_value(scene.cycles, 'device', 'CPU')
    report.update(device='CPU', backend='CPU')
    return report
