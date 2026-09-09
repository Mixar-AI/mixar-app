# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Trusted entry point used by backend CAD tools. Invoke on Blender's main thread."""
from .constants import MAX_PAGE
from .core import delivery, mutations, state, visual, reference, grounding, raster, inventory, progress, metadata_bridge
import time


def dispatch(action, payload):
    if isinstance(payload,dict) and 'packed_payload' in payload:
        try: payload=metadata_bridge.unpack(payload['packed_payload'])
        except Exception:
            return {'success':False,'error':{'code':'invalid_payload','message':'Invalid compressed CAD request.'}}
    started=time.monotonic()
    result=_dispatch(action,payload)
    progress.timing(action,time.monotonic()-started,result.get('success') is True)
    if result.get('success') is True and action in ('verify','reference_assign','reference_coverage','save'):
        try: progress.maybe(state.read(payload,check=False),action,result)
        except state.CadError: pass
    return result


def _dispatch(action, payload):
    try:
        if not isinstance(payload, dict): state.fail('invalid_payload', 'Expected a structured object.')
        if raster.busy():
            run = state.read(payload, check=False)
            if action in ('render', 'status'):
                return {'success': True, **raster.progress()}
            state.fail('render_busy', 'Wait for the native raster job and restored scene before other CAD operations.')
        if action == 'start':
            if payload.get('workflow') is not None:
                metadata_bridge.validate_settings(payload['workflow'])
            run = state.start(payload)
            metadata_bridge.install(run,payload.get('workflow'))
            if payload.get('reference_profile') and not run.get('reference_profile'):
                run['reference_profile'] = reference.profile(run)['profile_id']
                run['artifact'] = None
                state.persist(run)
            return {'success': True, **delivery.summary(run)}
        # Reads expose recorded evidence. Mutation boundaries check metadata;
        # expensive mesh audits belong to geometry edits/checkpoints/delivery.
        run = state.read(payload, check=action in ('undo', 'review', 'save'))
        if action in ('wheel_review_image','store_wheel_review','inspect_assembly','reference_assign','reference_coverage','render','ray_select','evidence_image'):
            targets=set()
            groups=payload.get('decisions',[]) if action=='reference_assign' else [payload]
            for group in groups:
                targets.update(group.get('object_ids') or [])
                selection=run.get('selections',{}).get(group.get('selection_id'),{})
                targets.update(selection.get('object_ids',[]))
            if action in ('ray_select','evidence_image'):
                targets.update(run.get('evidence',{}).get(payload.get('evidence_id'),{}).get('render_ids',[]))
            if action=='render' and not targets:
                targets.update(k for k,r in run.get('reference_assignments',{}).items() if r['disposition']=='keep') if payload.get('delivery') else targets.update(run['records'])
            if action=='reference_coverage':
                paths={r.get('path') for r in payload.get('reviews',[])}
                targets.update(k for k,r in run.get('reference_assignments',{}).items() if r.get('path') in paths)
            state.check_targets(run,targets)
        if action in ('verify','save') and (action=='save' or not payload.get('stage')):
            expected=payload.get('expected_state')
            if not isinstance(expected,dict) or any(expected.get(k)!=run.get(k,0) for k in
                    ('revision','fingerprint','assignment_revision')):
                state.fail('stale_delivery_state','Run the delivery tool against the current scene revision.')
        if action == 'metadata_snapshot': result = metadata_bridge.snapshot(run,payload)
        elif action == 'result_upload': result = metadata_bridge.upload(run,payload)
        elif action == 'result_commit':
            result = metadata_bridge.commit(run,payload)
            if result.get('success') is False: return result
            if result.get('assigned',0)>=200 or result.get('reviewed_paths'):
                progress.maybe(run,'reference_assign',{'assigned':200})
        elif action == 'checkpoint': result = progress.checkpoint(run,payload)
        elif action == 'ray_select': result = grounding.ray_select(run,payload)
        elif action == 'evidence_image': result = grounding.image(run,payload)
        elif action == 'store_localization': result = grounding.store_localization(run,payload)
        elif action == 'status': result = delivery.summary(run)
        elif action == 'apply': result = mutations.apply(run, payload)
        elif action == 'undo': result = mutations.undo(run, payload)
        elif action == 'verify': result = delivery.verify(run, payload)
        elif action == 'render': result = visual.render(run, payload)
        elif action == 'review': result = visual.review(run, payload)
        elif action == 'save':
            # Recheck at the write boundary: external edits after verification
            # must never be accepted from cached geometry expectations.
            if state.digest(state.capture(run, full=True)) != run['fingerprint']:
                state.fail('scene_changed', 'Scene changed since verification; inspect before saving.')
            result = delivery.save(run, payload)
        else: state.fail('unknown_action', 'Unsupported CAD tool action.')
        return {'success': True, **result}
    except state.CadError as exc:
        state.drop_cache()
        return {'success': False, 'error': {'code': exc.code, 'message': str(exc)}, **exc.details}
    except Exception as exc:
        state.drop_cache()
        # Tracebacks remain local; file paths or implementation details must not enter chat.
        return {'success': False, 'error': {'code': 'execution_failed',
                'message': 'CAD operation failed (' + type(exc).__name__ + '). Check local application diagnostics.'}}
