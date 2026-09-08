# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Trusted entry point used by backend CAD tools. Invoke on Blender's main thread."""
from .constants import CATEGORIES, MAX_PAGE
from .core import delivery, mutations, stages, state, visual, reference, grounding, raster, inventory, progress, assemblies, wheel_policy
import time


def dispatch(action, payload):
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
            run = state.start(payload)
            if payload.get('reference_profile') and not run.get('reference_profile'):
                run['reference_profile'] = reference.profile()['profile_id']
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
        if action == 'checkpoint': result = progress.checkpoint(run,payload)
        elif action == 'wheel_review_image': result = wheel_policy.image(run,payload)
        elif action == 'store_wheel_review': result = wheel_policy.store_review(run,payload)
        elif action == 'inspect_assembly': result = assemblies.inspect(run,payload)
        elif action == 'inspect_batch': result = inventory.inspect_batch(run,payload)
        elif action == 'reference_coverage': result = reference.review_coverage(run,payload)
        elif action == 'reference_catalog': result = reference.catalog(run, payload)
        elif action == 'reference_assign': result = reference.assign(run, payload)
        elif action == 'ray_select': result = grounding.ray_select(run, payload)
        elif action == 'evidence_image': result = grounding.image(run, payload)
        elif action == 'store_localization': result = grounding.store_localization(run,payload)
        elif action == 'status': result = delivery.summary(run)
        elif action == 'inspect':
            if payload.get('proposal_id'): result=inspect(run,payload)
            else:
                batch=inventory.inspect_batch(run,{'queries':[payload],'refresh_index':payload.get('refresh_index',False)})
                result={**batch['results'][0],**{k:v for k,v in batch.items() if k!='results'}}
                if payload.get('catalog'):
                    result['category_counts']=result.get('categories',{})
                    result['categories']=list(CATEGORIES)
        elif action == 'analyze': result = stages.analyze(run, str(payload.get('stage')))
        elif action == 'propose': result = stages.propose(run, payload)
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


def inspect(run, payload):
    limit = payload.get('limit', 50); cursor = payload.get('cursor', 0)
    if type(limit) is not int or type(cursor) is not int or not 1 <= limit <= MAX_PAGE or cursor < 0:
        state.fail('invalid_page', 'Use limit 1..100 and a nonnegative cursor.')
    proposal_id = payload.get('proposal_id')
    if proposal_id:
        preview = run['proposals'].get(proposal_id)
        if not preview: state.fail('missing_proposal', 'Preview no longer exists.')
        items = preview['decisions']
        notes = preview.get('notes', [])
        return {'proposal_id': proposal_id, 'decisions': items[cursor:cursor + limit],
                'snapshot_revision': preview['revision'], 'live_geometry_checked': False,
                'notes': notes[cursor:cursor + limit], 'note_count': len(notes),
                'groups': stages.decision_groups(items) if cursor == 0 else [],
                'total': len(items), 'next_cursor': cursor + limit if cursor + limit < max(len(items), len(notes)) else None}
    obs = state.objects(run)
    wanted = payload.get('object_ids')
    if wanted is not None and (not isinstance(wanted, list) or any(k not in obs for k in wanted)):
        state.fail('invalid_target', 'Unknown object IDs.')
    selection_id = payload.get('selection_id')
    if selection_id:
        selection = run.get('selections', {}).get(selection_id)
        if not selection or selection['revision'] != run['revision']:
            state.fail('stale_selection', 'Use a current selection.')
        selected_ids = set(selection['object_ids'])
        wanted = selected_ids if wanted is None else selected_ids.intersection(wanted)
    category = payload.get('category')
    if category:
        category_ids = {k for k,r in run['records'].items() if r['category'] == category}
        wanted = category_ids if wanted is None else category_ids.intersection(wanted)
    query = (payload.get('query') or '').casefold()
    selected = [(k, ob) for k, ob in obs.items() if (wanted is None or k in wanted) and query in ob.name.casefold()]
    indexes = state.relations()
    result = {'run_id': run['run_id'], 'revision': run['revision'], 'total': len(selected),
              'live_geometry_checked': False,
              'evidence_kind': 'live_metadata; geometry is audited at stage checkpoints and delivery',
              'objects': [state.record(ob, k, run, indexes) for k, ob in selected[cursor:cursor + limit]],
              'next_cursor': cursor + limit if cursor + limit < len(selected) else None}
    if cursor == 0 and (query or category or selection_id):
        result['selection_id'] = reference.selection(run, [k for k, _ in selected], None, 'metadata_group')
    if query and not selected:
        result['query_help'] = 'query is a literal case-insensitive substring of an object name, not a natural-language instruction. Use category for exact classification groups.'
    if payload.get('catalog'): result['categories'] = list(CATEGORIES)
    return result
