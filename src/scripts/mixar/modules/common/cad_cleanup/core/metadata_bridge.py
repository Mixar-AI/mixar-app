# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Data-only metadata transport. Backend decides; Blender checks transactional scope."""
import base64
import copy
import json
import time
import zlib
from . import state, inventory

VERSION = 3
LIMIT = 64 * 1024 * 1024
TABLES = ('proposals','reference_assignments','reference_assemblies','reference_coverage',
          'reference_inspected','reference_searches','selections','wheel_reviews','requests')
SCALARS = ('reference_profile','assignment_revision','artifact','reference_review')
_tickets = {}


def pack(data):
    raw=json.dumps(data,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>LIMIT: state.fail('metadata_payload_limit','Metadata exceeds the metadata transport limit.')
    return base64.b64encode(zlib.compress(raw)).decode('ascii')


def unpack(blob):
    if not isinstance(blob,str) or len(blob)>LIMIT: state.fail('metadata_payload_limit','Invalid metadata payload size.')
    decoder=zlib.decompressobj()
    raw=decoder.decompress(base64.b64decode(blob,validate=True),LIMIT+1)
    if len(raw)>LIMIT or not decoder.eof or decoder.unused_data:
        state.fail('metadata_payload_limit','Incomplete or oversized metadata data.')
    return json.loads(raw)


def validate_settings(contract):
    if not isinstance(contract,dict) or contract.get('version')!=VERSION:
        state.fail('cad_transport_mismatch','Update backend and client together for CAD metadata transport version 3.')
    stages=contract.get('stage_keys')
    if not isinstance(stages,list) or not stages or len(stages)>32 or any(not isinstance(s,str) or len(s)>32 for s in stages):
        state.fail('invalid_contract','Invalid workflow stage contract.')
    profile=contract.get('reference')
    if not isinstance(profile,dict) or not isinstance(profile.get('collections'),list):
        state.fail('invalid_contract','Missing backend reference contract.')
    if not isinstance(profile.get('assignable_paths'),list):
        state.fail('invalid_contract','Missing backend assignable paths.')
    organization=contract.get('organization',{})
    if any(not isinstance(organization.get(k),str) or not organization[k] or
           len(organization[k])>200 or '/' in organization[k] or '\\' in organization[k]
           for k in ('review_path','hidden_path')):
        state.fail('invalid_contract','Invalid organization destinations.')
    return contract


def install(run, contract):
    if contract is None:
        if not run.get('workflow'): state.fail('collection_schema_required','Supply a hierarchy for this new run.')
        contract=copy.deepcopy(run['workflow'])
        contract['version']=VERSION
    contract=validate_settings(contract)
    if run.get('workflow') and {k:v for k,v in run['workflow'].items() if k!='version'}!={k:v for k,v in contract.items() if k!='version'}:
        state.fail('request_conflict','A resumed run cannot change its collection schema.')
    run['workflow']=contract
    state.persist(run)


def snapshot(run,payload):
    if run.get('workflow',{}).get('version')!=VERSION:
        state.fail('cad_transport_mismatch','Start/resume through the updated backend before metadata calls.')
    # Pure metadata, no filesystem paths, geometry, materials or recovery snapshots.
    action=payload.get('operation')
    arguments=payload.get('arguments',{})
    summary_only=action in ('reference_summary','delivery_check')
    rows={} if summary_only else inventory.index(run, payload.get('refresh_index',False))
    if action in ('reference_assign','inspect_assembly','wheel_review_image','store_wheel_review','reference_coverage'):
        ids=set()
        for group in arguments.get('decisions',[]) if action=='reference_assign' else [arguments]:
            ids.update(group.get('object_ids') or [])
            ids.update(run.get('selections',{}).get(group.get('selection_id'),{}).get('object_ids',[]))
        rows={k:r for k,r in rows.items() if k in ids}
    fields=('object_id','name','type','category','dimensions','polygons','parent','geometry_supported','scale','duplicate_key')
    data={k:run.get(k,{}) for k in TABLES}
    # Only a matching metadata replay receipt crosses the boundary, never arbitrary
    # save/start receipts or the source operation history.
    request_id=arguments.get('request_id')
    old=run.get('requests',{}).get(request_id)
    data['requests']={request_id:old} if action=='reference_assign' and old else {}
    if summary_only:
        data={k:data[k] for k in ('reference_assignments','reference_coverage','wheel_reviews')}
    data.update({k:run[k] for k in ('run_id','revision','fingerprint','assignment_revision','reference_profile','workflow') if k in run})
    data.update({k:run.get(k) for k in ('stage_status','verified_revision','reference_review','reference_reviews','visual_review')})
    data['records']={k:{'name':r['name'],'category':r.get('category')} for k,r in run['records'].items()}
    data['_rows']={k:{f:r[f] for f in fields if f in r} for k,r in rows.items()}
    data['baseline']={'objects':{k:{f:r.get(f) for f in ('name','parent','type')}
                                 for k,r in run['baseline']['objects'].items()}}
    # Existing immutable-source receipts retain their exact signature. Send full
    # baseline metadata only for their bounded members, never all mesh buffers.
    proof_ids={k for receipt in run.get('wheel_reviews',{}).values() for k in receipt.get('members',[])}
    if action in ('wheel_review_image','store_wheel_review'):
        proof_ids.update(run.get('selections',{}).get(arguments.get('selection_id'),{}).get('object_ids',[]))
    for k in proof_ids:
        if k in run['baseline']['objects']: data['baseline']['objects'][k]=run['baseline']['objects'][k]
    evidence_fields=('revision','fingerprint','camera','render_ids','view','scope','assignment_revision','delivery')
    data['evidence']={k:{f:r[f] for f in evidence_fields if f in r} for k,r in run.get('evidence',{}).items()}
    # Only replay bookkeeping required by metadata, never source operation journals.
    data['operations']=[]
    blob=pack(data)
    if payload.get('read_only'):
        return {'protocol':VERSION,'snapshot':blob,'encoding':'zlib-base64-json'}
    now=time.monotonic()
    for key in list(_tickets):
        if now-_tickets[key]['created']>600: del _tickets[key]
    while len(_tickets)>=8:
        old=next((k for k,v in _tickets.items() if v['committed'] is not None),None)
        if old is None: break
        del _tickets[old]
    if len(_tickets)>=8: state.fail('metadata_busy','Too many outstanding metadata transactions; retry after expiry.')
    ticket=state.token()
    _tickets[ticket]={'created':now,'run_id':run['run_id'],'owner_id':run['owner_id'],
        'scene_revision':run['revision'],'fingerprint':run['fingerprint'],
        'assignment_revision':run.get('assignment_revision',0),'result_sequence':run.get('result_sequence',0),
        'chunks':[], 'size':0, 'committed':None}
    return {'protocol':VERSION,'ticket':ticket,'snapshot':blob,'encoding':'zlib-base64-json'}


def ticket(run,payload):
    value=_tickets.get(payload.get('ticket'))
    if not value or value['run_id']!=run['run_id'] or value['owner_id']!=run['owner_id']:
        state.fail('metadata_ticket_expired','Request a fresh metadata snapshot.')
    return value


def upload(run,payload):
    value=ticket(run,payload)
    chunk=payload.get('chunk'); index=payload.get('index')
    if not isinstance(chunk,str) or len(chunk)>16000 or type(index) is not int or index<0:
        state.fail('invalid_metadata_chunk','Use ordered bounded metadata chunks.')
    if index<len(value['chunks']):
        if value['chunks'][index]!=chunk: state.fail('request_conflict','Metadata chunk replay differs.')
    elif index==len(value['chunks']):
        if value['size']+len(chunk)>LIMIT: state.fail('metadata_payload_limit','Metadata patch too large.')
        value['chunks'].append(chunk); value['size']+=len(chunk)
    else: state.fail('invalid_metadata_chunk','Missing earlier metadata chunk.')
    return {'uploaded':index}


def commit(run,payload):
    value=ticket(run,payload)
    if value['committed'] is not None: return value['committed']
    if (value['scene_revision']!=run['revision'] or value['fingerprint']!=run['fingerprint'] or
        value['assignment_revision']!=run.get('assignment_revision',0) or value['result_sequence']!=run.get('result_sequence',0)):
        state.fail('stale_metadata_snapshot','Scene or decisions changed during metadata evaluation; request a fresh snapshot.')
    patch=unpack(''.join(value['chunks']))
    if set(patch)-{'tables','scalars','summary','coverage','accepted','result'}:
        state.fail('invalid_metadata_patch','Unsupported metadata state fields.')
    if set(patch.get('tables',{}))-set(TABLES) or set(patch.get('scalars',{}))-set(SCALARS):
        state.fail('invalid_metadata_patch','Metadata cannot write scene or recovery state.')
    targets=set()
    for row in patch.get('tables',{}).get('proposals',{}).get('set',{}).values():
        if row.get('stage') not in run['stage_status'] or row.get('revision')!=run['revision'] or row.get('fingerprint')!=run['fingerprint']:
            state.fail('invalid_metadata_patch','Proposal must match the current workflow and scene.')
        seen=set()
        for item in row.get('decisions',[]):
            if item['object_id'] in seen or item.get('operation') not in ('classify','park_duplicate','park_cull'):
                state.fail('invalid_metadata_patch','Duplicate target or unsupported operation.')
            seen.add(item['object_id'])
            targets.add(item['object_id'])
            path=item.get('destination')
            if (not isinstance(path,list) or not 1<=len(path)<=16 or
                    any(not isinstance(p,str) or not p or len(p)>200 or '/' in p or '\\' in p for p in path)):
                state.fail('invalid_metadata_patch','Invalid collection destination.')
    targets.update(patch.get('tables',{}).get('reference_assignments',{}).get('set',{}))
    if not targets<=run['records'].keys(): state.fail('invalid_target','Metadata references objects outside this run.')
    state.check_targets(run,targets)
    # Copy only changed dictionaries. Never clone the heavy recovery journal.
    prior={k:run.get(k) for k in (*TABLES,*SCALARS,'backend_summary','result_sequence')}
    try:
        for name,delta in patch.get('tables',{}).items():
            updated=dict(run.get(name,{}))
            for key in delta.get('delete',[]): updated.pop(key,None)
            updated.update(delta.get('set',{})); run[name]=updated
        run['reference_assignments']={k:{**row,'_backend_accepted':patch['accepted'].get(k,False)}
            for k,row in run.get('reference_assignments',{}).items()}
        run.update(patch.get('scalars',{}))
        run['result_sequence']=run.get('result_sequence',0)+1
        run['backend_summary']={'revision':run['revision'],'fingerprint':run['fingerprint'],
            'assignment_revision':run.get('assignment_revision',0),
            'summary':patch['summary'],'coverage':patch['coverage'],'accepted':patch['accepted']}
        state.persist(run)
    except Exception:
        for k,v in prior.items():
            if v is None: run.pop(k,None)
            else: run[k]=v
        raise
    value['committed']=patch['result']
    return patch['result']
