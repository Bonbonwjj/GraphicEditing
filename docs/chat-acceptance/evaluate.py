"""Evaluate reviewed synthetic Skill responses; not a sandbox for arbitrary code.
Run from the repository with its Matplotlib/Pandas Python environment.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / 'artifacts'
EXPECTED = {'01':'candidate','02':'candidate','03':'needs_clarification',
            '04':'candidate','05':'needs_context','06':'needs_clarification',
            '07':'needs_clarification','08':'needs_clarification','09':'candidate','10':'needs_clarification'}
RUNNER = '''import json, os, runpy
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.colors import to_hex
original = Figure.savefig
def capture(fig, filename, *args, **kwargs):
    fig.set_dpi(kwargs.get('dpi', fig.dpi))
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    ax=fig.axes[0]
    legend=ax.get_legend()
    texts=[ax.xaxis.label, ax.yaxis.label, *ax.get_xticklabels(), *ax.get_yticklabels()]
    records=[]
    for text in texts:
        if not text.get_visible() or not text.get_text(): continue
        box=text.get_window_extent(renderer)
        records.append({'text':text.get_text(),'bbox':list(box.extents)})
    collisions=[]
    for i,a in enumerate(records):
        for b in records[i+1:]:
            x0,y0,x1,y1=a['bbox'];u0,v0,u1,v1=b['bbox']
            if min(x1,u1)>max(x0,u0) and min(y1,v1)>max(y0,v0):
                collisions.append([a['text'], b['text']])
    width,height=fig.bbox.width,fig.bbox.height
    clipped=[r['text'] for r in records if r['bbox'][0]<0 or r['bbox'][1]<0 or r['bbox'][2]>width or r['bbox'][3]>height]
    lb=list(legend.get_window_extent(renderer).extents) if legend else None
    if lb and (lb[0]<0 or lb[1]<0 or lb[2]>width or lb[3]>height): clipped.append('legend')
    snapshot={'size_inches':list(fig.get_size_inches()),'xlabel':ax.get_xlabel(),'ylabel':ax.get_ylabel(),'title':ax.get_title(),
      'xlim':list(ax.get_xlim()),'ylim':list(ax.get_ylim()),'axes_position':list(ax.get_position().bounds),
      'label_fontsizes':[ax.xaxis.label.get_fontsize(),ax.yaxis.label.get_fontsize()],
      'legend_bbox':lb,'legend_fonts':[t.get_fontsize() for t in legend.get_texts()] if legend else [],
      'series':{line.get_label():{'x':list(map(float,line.get_xdata())),'y':list(map(float,line.get_ydata())),
        'linewidth':line.get_linewidth(),'color':to_hex(line.get_color()),'marker':line.get_marker(),'linestyle':line.get_linestyle()} for line in ax.lines},
      'tick_texts':[t.get_text() for t in ax.get_xticklabels()], 'text_collisions':collisions, 'clipped':clipped}
    with open(os.environ['CAPTURE_OUTPUT'],'w') as stream:json.dump(snapshot,stream,indent=2)
    return original(fig,filename,*args,**kwargs)
Figure.savefig=capture
runpy.run_path(os.environ['CASE_SOURCE'],run_name='__main__')
'''


def render(request, source, stem):
    with tempfile.TemporaryDirectory(prefix='chat-skill-eval-') as directory:
        project=Path(directory)
        for f in request['source_files']+request['plot_data']:
            destination=project/f['path'];destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(f['content'])
        candidate=project/'charts/b.py';candidate.write_text(source)
        readonly=[project/f['path'] for f in request['source_files']+request['plot_data'] if not f.get('writable')]
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in readonly}
        runner=project/'capture.py';runner.write_text(RUNNER)
        env=dict(os.environ,CHART_PROJECT_DIR=str(project),CHART_OUTPUT=str(ARTIFACTS/(stem+'.png')),
                 CAPTURE_OUTPUT=str(ARTIFACTS/(stem+'.json')),CASE_SOURCE=str(candidate),PYTHONPATH=str(project),
                 MPLCONFIGDIR=str(project/'.mplconfig'))
        result=subprocess.run([sys.executable,str(runner)],cwd=project,env=env,capture_output=True,text=True,timeout=30)
        if result.returncode:raise RuntimeError(result.stderr[-2000:])
        assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in readonly}, 'Read-only input changed'
        return json.loads((ARTIFACTS/(stem+'.json')).read_text())


def evaluate():
    ARTIFACTS.mkdir(exist_ok=True)
    report=[]
    for case,expected in EXPECTED.items():
        q=json.loads((ROOT/'inputs'/(case+'.json')).read_text());r=json.loads((ROOT/'responses'/(case+'.json')).read_text())
        errors=[]
        def check(ok,message):
            if not ok:errors.append(message)
        check(r['status']==expected,'Unexpected routing status')
        for key in ('request_id','edit_session_id','turn_id','parent_draft_id','chart_id','base_revision','user_message'):
            check(r.get(key)==q[key],'Echo mismatch: '+key)
        for op in r.get('interpreted_request',{}).get('operations',[]):
            for quote in op.get('source_quotes',[]): check(quote in q['user_message'],'Fabricated current-turn quote')
        if r['status']!='candidate':
            check(r.get('proposed_files')==[],'Non-candidate included changes')
            report.append(dict(case=case,status=r['status'],errors=errors));continue
        check(r['intent_check']['status']=='consistent','Unresolved intent in candidate')
        check(r['affected_chart_ids']==[q['chart_id']],'Wrong affected chart scope')
        files=r['proposed_files']
        check(len(files)==1 and files[0]['path']=='charts/b.py','Candidate changed other files')
        check(files[0]['base_sha256']==q['source_files'][0]['sha256'],'Wrong parent source hash')
        for data_ref in r.get('read_data_refs',[]):
            check(bool(data_ref.get('columns')),'Data lineage omits explicit CSV columns')
            columns=data_ref.get('columns',[])
            check(all(isinstance(c,dict) and c.get('name') and c.get('role') for c in columns),'Columns missing name or role')
            check({c.get('name') for c in columns if isinstance(c,dict)}=={'group','x','mean'},'Incorrect consumed columns for this fixture')
        old=render(q,q['source_files'][0]['content'],case+'-parent')
        new=render(q,files[0]['content'],case+'-candidate')
        for label,series in old['series'].items():
            check(label in new['series'],'Lost series '+label)
            for field in ('x','y','marker','linestyle'):
                check(new['series'][label][field]==series[field],f'{label} changed {field}')
        for field in ('xlabel','ylabel','title','label_fontsizes','legend_fonts'):
            check(old[field]==new[field],'Unrequested '+field)
        if case!='09':
            for field in ('size_inches','axes_position','xlim','ylim'):
                check(old[field]==new[field],'Unrequested '+field)
            check(not new['text_collisions'] and not new['clipped'],'Detected layout collision or clipping')
        if case=='01':
            check(new['series']['Obs']['linewidth']==2.5,'Obs width not 2.5')
            check(new['series']['Control']==old['series']['Control'],'Control changed')
            check(new['legend_bbox']==old['legend_bbox'],'Existing correct legend moved')
        elif case=='02':
            check(new['series']==old['series'],'Lost inherited style')
            check(new['legend_bbox'][0]<old['legend_bbox'][0],'Legend did not move left')
            check(new['legend_bbox'][1:4:2]==old['legend_bbox'][1:4:2],'Legend moved vertically')
        elif case=='04':
            check(new['series']['Obs']['color']=='#006644','Reference color not used')
            check(new['series']['Control']==old['series']['Control'],'Control changed')
        elif case=='09':
            check(r['layout_policy']['mode']=='allow_disclosed_overlap','Exception not reported')
            check(bool(r.get('warnings')),'Missing exception warning')
            check(new['size_inches']==[1.0,4.0],'Explicit dimensions not preserved')
            check(bool(new['text_collisions']),'Conflict fixture no longer collides')
        report.append(dict(case=case,status=r['status'],errors=errors,rendered=True,
                           layout={'text_collisions':new['text_collisions'],'clipped':new['clipped']},
                           export_ready=not new['text_collisions'] and not new['clipped']))
    (ROOT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps([{'case':r['case'],'status':r['status'],'errors':r['errors'],'export_ready':r.get('export_ready')} for r in report],ensure_ascii=False,indent=2))

if __name__=='__main__':evaluate()
