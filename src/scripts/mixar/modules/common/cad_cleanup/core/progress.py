# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Local, immutable progress snapshots and a latest HTML index. No implicit renders."""
import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
import bpy
from . import state, reference, organized

_timings = {}


def timing(action, seconds, success):
    key=(bpy.context.scene.as_pointer(),action)
    row=_timings.setdefault(key,{'calls':0,'seconds':0,'failures':0})
    row['calls']+=1; row['seconds']+=seconds; row['failures']+=not success


def atomic(path, text):
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(text,encoding='utf-8'); temp.replace(path)


def document(data, prefix=''):
    escape=lambda v:html.escape(str(v))
    counts=data['reference']
    rows=''.join('<tr><td>'+escape(r['path'])+'</td><td>'+str(r['assigned'])+'</td><td>'+escape(r['status'])+'</td><td>'+escape(r['notes'])+'</td></tr>' for r in data['coverage'])
    cards=''.join('<figure><img src="'+prefix+escape(i['file'])+'"><figcaption>'+escape(i['view'])+' — '+escape(i['scope'])+'; scene revision '+str(i['revision'])+', assignment revision '+str(i.get('assignment_revision'))+'; '+('CURRENT' if i['current'] else 'STALE — historical evidence')+'</figcaption></figure>' for i in data['images'])
    deltas='; '.join(escape(k)+': '+str(v.get('before',0))+' → '+str(v['after']) for k,v in data['changed_paths'].items()) or 'No assignment count changes since previous snapshot.'
    changed_rows=''.join('<tr><td>'+escape(r['name'])+'</td><td>'+escape(r['before'])+'</td><td>'+escape(r['after'])+'</td></tr>' for r in data['changed_objects'][:100])
    changes='<h2>New or revised decisions ('+str(data['changed_object_count'])+')</h2><p>First 100 shown; full list in this snapshot summary.json.</p><table><tr><th>Object</th><th>Before</th><th>After</th></tr>'+changed_rows+'</table>'
    links='<p><a href="summary.json">Snapshot details</a></p>' if prefix else '<p><a href="latest.json">Latest snapshot details</a></p>'
    if data.get('checkpoint_filename'): links+='<p><a href="'+('checkpoint.mixar' if prefix else 'snapshots/'+data['timestamp']+'/checkpoint.mixar')+'">Saved resumable recovery checkpoint</a></p>'
    if data.get('organized_filename'): links+='<p><a href="'+('organized.mixar' if prefix else 'snapshots/'+data['timestamp']+'/organized.mixar')+'">Open organized inspection copy</a> (not final delivery)</p>'
    physical=data.get('organized', {})
    links+='<h2>Actual organized collections</h2><p>Scene: '+escape(physical.get('scene','Not created'))+'; current: '+str(physical.get('current',False))+'. Recovery diagnostics are separate. HIDDEN_INTERNALS is retained with display/render disabled; REVIEW contains uncertain or stale decisions.</p><pre>'+escape(json.dumps(physical.get('counts',{}),indent=2))+'</pre>'
    if data.get('artifact',{}).get('filename'): links+='<p><a href="'+prefix+'../../'+escape(data['artifact']['filename'])+'">Saved processed project</a></p>'
    errors=''.join('<li>'+escape(e)+'</li>' for e in data['issues'])
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CAD progress</title><style>body{font:16px/1.6 system-ui;background:#121a24;color:#eef3f9;margin:32px auto;padding:24px;max-width:1300px}a{color:#9cd2ff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}figure{margin:0}img{width:100%}table{border-collapse:collapse;width:100%}td,th{padding:8px;text-align:left;border-bottom:1px solid #405064}.state{padding:16px;background:#29374a}</style>'''+ '<h1>CAD cleanup progress</h1><p class="state">'+escape(data['status'])+' — '+escape(data['reason'])+'</p><p>'+escape(data['timestamp'])+' · scene revision '+str(data['revision'])+' · assignment revision '+str(counts['assignment_revision'])+'</p><p>Unassigned: '+str(counts['pending'])+' · Review: '+str(counts['review'])+' · Invalid/stale assignments: '+str(counts['invalid_assignments'])+' · Unresolved reference paths: '+str(counts['coverage_unresolved'])+'</p><p>Preserved geometry is not necessarily correctly classified. This report never substitutes for a verified saved deliverable.</p><h2>Changes since previous snapshot</h2><p>'+deltas+'</p><h2>Images</h2><p>Cached scoped captures only; stale images are labeled. Missing views are not silently rendered.</p><div class="grid">'+cards+'</div>'+changes+links+'<h2>Issues</h2><ul>'+errors+'</ul><h2>Coverage</h2><table><tr><th>Reference path</th><th>Assigned</th><th>Status</th><th>Observations</th></tr>'+rows+'</table><h2>Tool execution</h2><pre>'+escape(json.dumps(data['timings'],indent=2))+'</pre><p><a href="'+prefix+'history.html">Snapshot history</a></p></html>'


def checkpoint(run,payload=None):
    payload=payload or {}
    if run.get('reference_profile'):
        organized.sync(run)
    reason=str(payload.get('reason','Major classification checkpoint'))[:500]
    source=Path(run['source_file']) if run.get('source_file') else Path(bpy.app.tempdir)/'unsaved.mixar'
    root=source.parent/(source.stem+'_cad_progress')/run['run_id']
    images=root/'images'; snapshots=root/'snapshots'
    images.mkdir(parents=True,exist_ok=True); snapshots.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    snapshot=snapshots/stamp; snapshot.mkdir()
    status=reference.summary(run)
    previous_path=root/'latest.json'
    previous=json.loads(previous_path.read_text()) if previous_path.exists() else {}
    old=previous.get('reference',{}).get('counts',{})
    counts=status['counts']
    captured=[]
    from .visual import cached_path
    for eid,metadata in run.get('evidence',{}).items():
        path=cached_path(metadata)
        if path is None or not path.is_file(): continue
        target=images/(eid+'.png')
        if not target.exists(): shutil.copyfile(path,target)
        current=metadata.get('revision')==run['revision'] and metadata.get('fingerprint')==run['fingerprint'] and (not metadata.get('delivery') or metadata.get('assignment_revision')==run.get('assignment_revision'))
        captured.append({'file':'images/'+target.name,'view':metadata.get('view','unknown'),
            'scope':'kept delivery set' if metadata.get('delivery') else 'scoped inspection',
            'revision':metadata.get('revision'),'assignment_revision':metadata.get('assignment_revision'),'current':current})
    terminal=payload.get('status','checkpoint')
    artifact=run.get('artifact') or {}
    if terminal=='complete' and (not status['semantic_complete'] or artifact.get('revision')!=run['revision'] or
            artifact.get('assignment_revision')!=run.get('assignment_revision') or not Path(artifact.get('local_path','')).is_file()): terminal='incomplete'
    assignment_index={k:[r['disposition'],r.get('path'),r.get('policy_version'),r.get('scene_revision')] for k,r in run.get('reference_assignments',{}).items()}
    old_index=previous.get('assignment_index',{})
    changed=[{'object_id':k,'name':run['records'][k]['name'],'before':old_index.get(k),'after':v}
             for k,v in assignment_index.items() if old_index.get(k)!=v]
    data={'timestamp':stamp,'reason':reason,'status':terminal,'revision':run['revision'],
        'reference':status,'organized':organized.public(run),'coverage':reference.coverage_rows(run),'images':captured[-8:],
        'assignment_index':assignment_index,'changed_object_count':len(changed),'changed_objects':changed,
        'changed_paths':{k:{'before':old.get(k,0),'after':counts.get(k,0)} for k in old.keys()|counts.keys() if old.get(k,0)!=counts.get(k,0)},
        'issues':[payload['error']] if payload.get('error') else [],
        'timings':{action:{**v,'seconds':round(v['seconds'],3)} for (scene,action),v in _timings.items() if scene==bpy.context.scene.as_pointer()},
        'artifact':{k:v for k,v in (run.get('artifact') or {}).items() if k not in ('local_path','report_path')}}
    if payload.get('save_checkpoint'):
        destination=snapshot/'checkpoint.mixar'
        if run.get('reference_profile'):
            inspection=snapshot/'organized.mixar'
            bpy.data.libraries.write(str(inspection), {organized.scene_for(run)}, path_remap='ABSOLUTE', fake_user=True, compress=False)
            if not inspection.is_file(): state.fail('checkpoint_save_failed','The organized inspection copy could not be saved.')
            data['organized_filename']='organized.mixar'
        result=bpy.ops.wm.save_as_mainfile(filepath=str(destination),copy=True,check_existing=False)
        if result!={'FINISHED'}: state.fail('checkpoint_save_failed','The inspection checkpoint could not be saved.')
        if not destination.is_file(): state.fail('checkpoint_save_failed','The inspection checkpoint could not be saved.')
        data['checkpoint_filename']='checkpoint.mixar'
    serialized=json.dumps(data,indent=2)
    atomic(snapshot/'summary.json',serialized)
    atomic(snapshot/'index.html',document(data,'../../'))
    atomic(root/'latest.json',serialized); atomic(root/'index.html',document(data))
    links=''.join('<li><a href="snapshots/'+p.name+'/index.html">'+p.name+'</a></li>' for p in sorted(snapshots.iterdir(),reverse=True) if (p/'index.html').is_file())
    atomic(root/'history.html','<!doctype html><meta charset="utf-8"><h1>CAD progress history</h1><ul>'+links+'</ul>')
    run['progress_receipt']={'snapshot':stamp,'filename':'index.html','local_directory':str(root)}
    run['progress_assignment_revision']=run.get('assignment_revision',0)
    state.persist(run)
    return {'snapshot':stamp,'filename':'index.html','saved_checkpoint':bool(payload.get('save_checkpoint')),
            'organized':organized.public(run)}


def maybe(run,action,result):
    major=action in ('verify','reference_coverage','save') or (action=='reference_assign' and result.get('assigned',0)>=200)
    if major:
        try:
            checkpoint(run,{'reason':action,'status':'complete' if action=='save' else 'checkpoint'})
        except Exception as exc:
            result['progress_warning']='Progress report failed ('+type(exc).__name__+'); scene operation result is unchanged. Retry cad_checkpoint.'
