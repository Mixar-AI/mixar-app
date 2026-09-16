# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Reusable metadata inventory. Queries are snapshots, never geometry verification."""
from collections import Counter
import bpy
from . import state, reference, reference_policy

_cache = None


def index(run, refresh=False):
    global _cache
    key = (bpy.context.scene.as_pointer(), run['run_id'], run['revision'])
    if refresh or _cache is None or _cache[0] != key:
        objects = state.objects(run)
        relations = state.relations()
        rows = {k:state.record(o,k,run,relations) for k,o in objects.items()}
        _cache = (key, rows)
    return _cache[1]


def query(run, payload, rows):
    limit=payload.get('limit',10); cursor=payload.get('cursor',0)
    if type(limit) is not int or type(cursor) is not int or not 1<=limit<=100 or cursor<0:
        state.fail('invalid_page','Use limit 1..100 and a nonnegative cursor.')
    wanted=payload.get('object_ids')
    if wanted is not None and (not isinstance(wanted,list) or any(k not in rows for k in wanted)):
        state.fail('invalid_target','Unknown object IDs.')
    wanted=set(wanted) if wanted is not None else None
    selected=payload.get('selection_id')
    if selected:
        selection=run.get('selections',{}).get(selected)
        if not selection or selection['revision']!=run['revision']:
            state.fail('stale_selection','Inspect a current group.')
        keys=set(selection['object_ids']); wanted=keys if wanted is None else wanted&keys
    text=payload.get('query') or ''
    if not isinstance(text,str): state.fail('invalid_query','query must be a literal name substring.')
    text=text.casefold()
    category=payload.get('category'); path=payload.get('reference_path')
    status=payload.get('classification_state')
    if status not in (None,'pending','review','invalid','accepted'):
        state.fail('invalid_query','classification_state must be pending, review, invalid or accepted.')
    assignment=run.get('reference_assignments',{})
    def matches(k,r):
        if wanted is not None and k not in wanted: return False
        if text not in r['name'].casefold() or (category and r['category']!=category): return False
        a=assignment.get(k)
        if path and (not a or a.get('path')!=path): return False
        if status=='pending' and a: return False
        if status=='review' and (not a or a['disposition']!='review'): return False
        if status=='invalid' and (not a or a['disposition']=='review' or reference_policy.accepted(run,a)): return False
        if status=='accepted' and (not a or a['disposition']=='review' or not reference_policy.accepted(run,a)): return False
        return True
    keys=sorted(k for k,r in rows.items() if matches(k,r))
    page=keys[cursor:cursor+limit]
    run.setdefault('reference_inspected',{}).update({k:run['revision'] for k in page})
    token=reference.selection(run,keys,None,'metadata_group',persist=False)
    search_id=None
    if text:
        receipt={'revision':run['revision'],'query':text,'total':len(keys),
                 'full_scope':not any((wanted is not None,category,path,status))}
        searches=run.setdefault('reference_searches',{})
        search_id=next((k for k,v in searches.items() if v==receipt),None)
        if search_id is None: search_id=state.token(); searches[search_id]=receipt
        while len(searches)>256: del searches[next(iter(searches))]
    return {'total':len(keys),'objects':[rows[k] for k in page],
        'selection_id':token,'selection_scope':'entire filtered group, NOT only this page',
        'page_count':len(page),'all_candidates_inspected':all(run['reference_inspected'].get(k)==run['revision'] for k in keys),
        'categories':dict(Counter(rows[k]['category'] or 'unclassified' for k in keys)),
        'next_cursor':cursor+limit if cursor+limit<len(keys) else None,'search_id':search_id,
        'query_help':'Literal name substring only; split heterogeneous groups before assignment.' if text and not keys else None}


def inspect_batch(run,payload):
    queries=payload.get('queries')
    if not isinstance(queries,list) or not 1<=len(queries)<=20 or any(not isinstance(q,dict) for q in queries):
        state.fail('invalid_queries','Supply 1..20 structured queries in one call.')
    if any(type(q.get('limit',10)) is not int for q in queries) or sum(q.get('limit',10) for q in queries)>500:
        state.fail('response_too_large','Use at most 500 returned rows across all queries.')
    rows=index(run,payload.get('refresh_index',False))
    before=state.digest({k:run.get(k,{}) for k in ('reference_inspected','reference_searches','selections')})
    results=[query(run,q,rows) for q in queries]
    if before!=state.digest({k:run.get(k,{}) for k in ('reference_inspected','reference_searches','selections')}): state.persist(run)
    return {'run_id':run['run_id'],'revision':run['revision'],'results':results,
        'evidence_kind':'indexed metadata at scene revision; refresh_index after manual edits; not a geometry audit',
        'live_geometry_checked':False}
