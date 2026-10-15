const $ = id => document.getElementById(id);
const state = {projects: [], project: null, resourceType: null, resourceId: null, chart: null, validationChart: null, detail: null, proposal: null, openProjects: new Set()};
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const savedTheme=localStorage.getItem('plot-forge-theme')||'dark';
document.documentElement.dataset.theme=savedTheme;
function updateThemeButton(){const light=document.documentElement.dataset.theme==='light';$('themeToggle').textContent=light?'☾ 深色':'☀ 浅色';}
$('themeToggle').onclick=()=>{const next=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=next;localStorage.setItem('plot-forge-theme',next);updateThemeButton();};
updateThemeButton();

const endpoint = action => {
  if(state.resourceType==='module'){
    const base=`/api/projects/${encodeURIComponent(state.project)}/modules/${encodeURIComponent(state.resourceId)}/${action}`;
    return `${base}?chart=${encodeURIComponent(state.validationChart||'')}`;
  }
  return `/api/projects/${encodeURIComponent(state.project)}/charts/${encodeURIComponent(state.chart)}/${action}`;
};
async function api(url, options) { const r = await fetch(url, options); const data = await r.json(); if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`); return data; }
function alertStatus(s) { $('status').textContent = s; }
function bubble(s, cls='assistant') { const e=document.createElement('div'); e.className='bubble '+cls; e.textContent=s; $('messages').append(e); $('messages').scrollTop=$('messages').scrollHeight; }
function tab(name) { document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.dataset.tab===name)); for(const n of ['figure','code','data']) $(n+'Pane').classList.toggle('hide',n!==name); }
function drawTree() {
  $('tree').innerHTML=state.projects.map(p=>{
    const open=state.openProjects.has(p.id);
    const sources=(p.data_sources||[]).map(s=>`<div class="sourceBadge">${s.kind==='plot_bundle'?'Bundle':'表格'} · ${esc(s.metadata?.analysis||s.metadata?.file_count||'已注册')}</div>`).join('');
    const charts=p.charts.map(c=>`<button class="file ${state.project===p.id&&state.resourceType==='chart'&&state.resourceId===c?'active':''}" data-project="${esc(p.id)}" data-resource-type="chart" data-resource-id="${esc(c)}">${esc(c)}.py</button>`).join('');
    const modules=(p.modules||[]).length?`<div class="folder">⌄ 共享绘图模块</div>${p.modules.map(m=>`<button class="file moduleFile ${state.project===p.id&&state.resourceType==='module'&&state.resourceId===m.id?'active':''}" data-project="${esc(p.id)}" data-resource-type="module" data-resource-id="${esc(m.id)}">${esc(m.path)}</button>`).join('')}`:'';
    return `<section class="projectGroup"><button class="projectName" data-toggle="${esc(p.id)}">${open?'▾':'▸'} ${esc(p.name)}</button><div class="projectContents ${open?'':'hide'}"><div class="folder">⌄ 绘图代码</div>${charts}${modules}<div class="folder">⌄ 数据源</div>${sources}${p.data.map(d=>`<div class="csv">▦ ${esc(d)}</div>`).join('')}</div></section>`;
  }).join('');
  document.querySelectorAll('[data-toggle]').forEach(e=>e.onclick=()=>{const id=e.dataset.toggle;state.openProjects.has(id)?state.openProjects.delete(id):state.openProjects.add(id);drawTree();});
  document.querySelectorAll('.file').forEach(e=>e.onclick=()=>selectResource(e.dataset.project,e.dataset.resourceType,e.dataset.resourceId));
}
function drawHistory() { const h=state.detail.history; $('historyCount').textContent=h.length+' 条'; $('history').innerHTML=h.length?h.slice().reverse().map(x=>`<div class="historyItem"><strong>${esc(x.note)}</strong><time>${esc(new Date(x.time).toLocaleString('zh-CN'))} · ${esc(x.id)}</time><button data-id="${esc(x.id)}">恢复此版本 ↗</button></div>`).join(''):'<div class="placeholder">当前是初始版本。保存一次修改后会出现历史记录。</div>'; document.querySelectorAll('.historyItem button').forEach(e=>e.onclick=()=>restore(e.dataset.id)); }
function drawData() { const sources=(state.detail.data_sources||[]).map(s=>{const m=s.metadata||{};const size=m.payload_bytes?`${(m.payload_bytes/1024/1024).toFixed(1)} MB`:`${m.file_count||0} 个文件`;return `<section class="sourceCard"><h3>${s.kind==='plot_bundle'?'Plot Bundle':'表格数据源'}</h3><p>${esc(m.analysis||'tabular')} · ${esc(m.plot_count||m.file_count||0)} 项 · ${esc(size)} · 只读</p>${s.kind==='plot_bundle'?'<p class="hint">按所选图延迟加载 payload；不会把服务器路径或 Bundle 元数据发送给大模型。</p>':''}</section>`;}).join('');const tables=state.detail.data.map(d=>`<section><h3>▦ ${esc(d.file)}</h3><table><thead><tr>${d.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${d.sample.map(r=>`<tr>${r.map(x=>`<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table><p class="hint">显示前 3 行 · 数据文件位于项目 data/ 目录</p></section>`).join('');$('dataInfo').innerHTML=sources+tables; }
async function preview() { if(!state.chart)throw new Error('当前项目没有可用的代表图。');$('figure').hidden=true;$('empty').hidden=false;$('empty').textContent='正在渲染…';const url=endpoint('preview');const r=await fetch(url+(url.includes('?')?'&':'?')+'v='+Date.now());if(!r.ok){const e=await r.json();throw new Error(e.error);}const blob=await r.blob();if($('figure').dataset.url)URL.revokeObjectURL($('figure').dataset.url);const u=URL.createObjectURL(blob);$('figure').src=u;$('figure').dataset.url=u;$('figure').hidden=false;$('empty').hidden=true;alertStatus('已渲染 · '+new Date().toLocaleTimeString('zh-CN'));}
function updateResourceLinks(){const available=Boolean(state.chart);$('refresh').disabled=!available;$('svg').hidden=!available;$('pdf').hidden=!available;if(available){$('svg').href=endpoint('svg');$('pdf').href=endpoint('pdf');}}
async function selectResource(project,type,id){
  const previousProject=state.project,previousChart=state.chart;
  state.openProjects.add(project);state.project=project;state.resourceType=type;state.resourceId=id;state.proposal=null;$('proposal').hidden=true;
  const p=state.projects.find(x=>x.id===project);
  if(type==='chart'){state.chart=id;state.validationChart=null;}else{const preferred=previousProject===project&&p.charts.includes(previousChart)?previousChart:p.charts[0];state.validationChart=preferred||null;state.chart=state.validationChart;}
  drawTree();
  const module=type==='module'?(p.modules||[]).find(m=>m.id===id):null;
  $('validationControls').hidden=type!=='module';
  if(type==='module'){$('validationChart').innerHTML=p.charts.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');$('validationChart').value=state.validationChart||'';$('breadcrumb').textContent=`${p.name.toUpperCase()} / SHARED MODULES`;$('chartTitle').textContent=module?.name||'共享绘图模块';$('description').textContent='修改会影响所有引用该模块的图；保存前仅验证所选代表图。';$('filename').textContent=module?.path||'module.py';}
  else{$('breadcrumb').textContent=`${p.name.toUpperCase()} / CHARTS / ${id.toUpperCase()}`;$('chartTitle').textContent=id.replaceAll('_',' ');$('description').textContent=p.description;$('filename').textContent=id+'.py';}
  updateResourceLinks();
  try{state.detail=await api(endpoint('detail'));$('editor').value=state.detail.code;$('skillText').textContent=state.detail.style;drawHistory();drawData();tab('figure');if(state.chart)await preview();else{$('figure').hidden=true;$('empty').hidden=false;$('empty').textContent='该项目没有可用于验证的图表。';}}catch(e){alertStatus(e.message);$('empty').textContent=e.message;}
}
async function select(project,chart){return selectResource(project,'chart',chart);}
async function post(action,body){const payload={...body};if(state.resourceType==='module')payload.chart=state.validationChart;return api(endpoint(action),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});}
async function apply(code,note){const selected={project:state.project,type:state.resourceType,id:state.resourceId};try{$('saveCode').disabled=true;$('apply').disabled=true;const r=await post('apply',{code,note});bubble(r.message);state.proposal=null;$('proposal').hidden=true;await reloadProjects();await selectResource(selected.project,selected.type,selected.id);}catch(e){bubble(e.message,'error');}finally{$('saveCode').disabled=false;$('apply').disabled=false;}}
async function restore(id){if(!confirm('将此历史版本恢复为新的当前版本？原版本仍保留。'))return;const selected={project:state.project,type:state.resourceType,id:state.resourceId};try{await post('restore',{id});await reloadProjects();await selectResource(selected.project,selected.type,selected.id);bubble('已恢复历史版本。');}catch(e){bubble(e.message,'error');}}
$('chatForm').onsubmit=async e=>{e.preventDefault();if(!state.resourceId||!state.chart){bubble('请先选择图表，或为共享模块选择一张代表图。','error');return;}const prompt=$('prompt').value.trim();if(!prompt)return;$('prompt').value='';bubble(prompt,'user');alertStatus('正在生成修改建议…');try{const r=await post('propose',{prompt});state.proposal={code:r.code,prompt};$('proposal').hidden=false;bubble(r.reply);alertStatus('待审核修改');}catch(e){bubble(e.message,'error');alertStatus('修改建议未生成');}};
$('prompt').onkeydown=e=>{if(e.key==='Enter'&&e.ctrlKey){e.preventDefault();$('chatForm').requestSubmit();}};
$('inspect').onclick=()=>{if(state.proposal){$('editor').value=state.proposal.code;tab('code');}};
$('apply').onclick=()=>{if(state.proposal)apply(state.proposal.code,state.proposal.prompt);};
$('saveCode').onclick=()=>{if(state.resourceId&&state.chart)apply($('editor').value,state.resourceType==='module'?'手动编辑共享绘图模块':'手动编辑绘图代码');};
$('refresh').onclick=async()=>{try{await preview();}catch(e){alertStatus(e.message);bubble(e.message,'error');}};
$('validationChart').onchange=async e=>{state.validationChart=e.target.value;state.chart=state.validationChart;updateResourceLinks();try{await preview();}catch(error){alertStatus(error.message);bubble(error.message,'error');}};
document.querySelectorAll('.tab').forEach(e=>e.onclick=()=>tab(e.dataset.tab));
$('showSkill').onclick=()=>$('skillDialog').showModal();$('closeSkill').onclick=()=>$('skillDialog').close();
async function reloadProjects(){const r=await api('/api/projects');state.projects=r.projects;drawTree();return r;}
$('newProject').onclick=async()=>{const id=prompt('项目 ID（英文字母、数字、下划线或连字符）：');if(!id)return;const name=prompt('项目显示名称：',id)||id;try{await api('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,name})});await reloadProjects();state.project=id;alertStatus('已创建项目 '+id);}catch(e){alert(e.message);}};
$('newChart').onclick=async()=>{if(!state.project){alert('请先创建或选中项目。');return;}const name=prompt('新图名称（英文字母、数字或下划线）：');if(!name)return;try{await api(`/api/projects/${state.project}/charts`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});await reloadProjects();await select(state.project,name);}catch(e){alert(e.message);}};

$('uploadPackage').onclick=()=>{
  const mode=$('uploadProjectMode');
  mode.innerHTML='<option value="__new__">＋ 新建项目</option>'+state.projects.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}（${esc(p.id)}）</option>`).join('');
  mode.value='__new__';$('newProjectFields').hidden=false;
  $('uploadProjectName').value='';$('uploadProjectId').value='';
  $('codeFolder').value='';$('dataFolder').value='';
  $('bundleFolder').value='';$('bundleServerPath').value='';$('bundleTrusted').checked=false;
  $('codeFolderStatus').textContent='尚未选择';$('dataFolderStatus').textContent='尚未选择';
  $('bundleFolderStatus').textContent='尚未选择';$('importSourceType').value='tabular';$('bundleSourceMode').value='server_path';
  updateImportControls();
  $('uploadDialog').showModal();
};
$('closeUpload').onclick=()=>$('uploadDialog').close();
$('uploadProjectMode').onchange=e=>{$('newProjectFields').hidden=e.target.value!=='__new__';};
$('importSourceType').onchange=updateImportControls;
$('bundleSourceMode').onchange=updateImportControls;
$('codeFolder').onchange=e=>{$('codeFolderStatus').textContent=e.target.files.length?`${e.target.files.length} 个 Python 文件`:'尚未选择';};
$('dataFolder').onchange=e=>{$('dataFolderStatus').textContent=e.target.files.length?`${e.target.files.length} 个数据文件`:'尚未选择';};
$('bundleFolder').onchange=e=>{$('bundleFolderStatus').textContent=e.target.files.length?`${e.target.files.length} 个 Bundle 文件`:'尚未选择';};
function updateImportControls(){
  const bundle=$('importSourceType').value==='plot_bundle';
  $('tabularImportFields').hidden=bundle;$('bundleImportFields').hidden=!bundle;
  $('projectModeLabel').hidden=bundle;
  if(bundle){$('uploadProjectMode').value='__new__';$('newProjectFields').hidden=false;}
  const upload=$('bundleSourceMode').value==='upload';
  $('bundleUploadFields').hidden=!upload;$('bundleServerFields').hidden=upload;
}
$('startUpload').onclick=async()=>{
  const sourceType=$('importSourceType').value;
  const existing=sourceType==='tabular'&&$('uploadProjectMode').value!=='__new__';
  const chosen=existing?state.projects.find(p=>p.id===$('uploadProjectMode').value):null;
  const name=existing?chosen.name:$('uploadProjectName').value.trim();
  const project_id=existing?chosen.id:$('uploadProjectId').value.trim();
  if(!name||!project_id){alert('请填写项目名称和项目 ID。');return;}
  $('startUpload').disabled=true;alertStatus('正在验证并导入数据源…');
  try{
    let r;
    if(sourceType==='tabular'){
      const codeFiles=[...$('codeFolder').files],dataFiles=[...$('dataFolder').files];
      if(!codeFiles.length||!dataFiles.length)throw new Error('请分别选择代码文件夹和数据文件夹。');
      const code=codeFiles.filter(f=>f.name.endsWith('.py'));
      const data=dataFiles.filter(f=>/\.(csv|tsv|json)$/i.test(f.name));
      if(!code.length||!data.length)throw new Error('所选目录中没有可用的 Python 或数据文件。');
      const totalBytes=[...code,...data].reduce((sum,f)=>sum+f.size,0);
      if(totalBytes>500_000_000)throw new Error('单次上传总大小不能超过 500 MB。');
      alertStatus(`正在上传 ${(totalBytes/1024/1024).toFixed(1)} MB 并拆分…`);
      const form=new FormData();
      form.append('name',name);form.append('project_id',project_id);form.append('existing',String(existing));
      code.forEach(f=>form.append('code_files',f,f.webkitRelativePath||f.name));
      data.forEach(f=>form.append('data_files',f,f.webkitRelativePath||f.name));
      r=await api('/api/uploads/import',{method:'POST',body:form});
    }else{
      if(!$('bundleTrusted').checked)throw new Error('导入 Plot Bundle 前必须确认它来自受信任来源。');
      if($('bundleSourceMode').value==='server_path'){
        const source_path=$('bundleServerPath').value.trim();
        if(!source_path)throw new Error('请输入共享目录中的 Bundle 路径。');
        r=await api('/api/data-sources/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,project_id,source_path,trusted:true})});
      }else{
        const files=[...$('bundleFolder').files].filter(f=>/\.(json|gz)$/i.test(f.name));
        if(!files.length)throw new Error('请选择包含 manifest.json 的 Plot Bundle 文件夹。');
        const totalBytes=files.reduce((sum,f)=>sum+f.size,0);
        if(totalBytes>500_000_000)throw new Error('Bundle 超过 500 MB，请改用共享目录路径。');
        const form=new FormData();form.append('name',name);form.append('project_id',project_id);form.append('trusted','true');
        files.forEach(f=>form.append('bundle_files',f,f.webkitRelativePath||f.name));
        r=await api('/api/data-sources/import-upload',{method:'POST',body:form});
      }
    }
    $('uploadDialog').close();await reloadProjects();state.openProjects.add(r.project);
    const gitState=r.git?.enabled?(r.git.committed?'已记录本地 Git 提交':'Git 已启用但没有新提交'):'Git 未启用（不影响使用）';
    bubble(`项目“${name}”已导入：${r.files??r.plot_count??0} 个数据项，${r.charts.length} 张图表；${gitState}。`);
    if(r.charts[0])await select(r.project,r.charts[0]);
  }catch(err){bubble(err.message,'error');alertStatus('数据源导入失败');}
  finally{$('startUpload').disabled=false;}
};

$('importCsv').onclick=()=>{if(!state.project){alert('请先创建或选中项目。');return;}$('csvFile').click();};
$('csvFile').onchange=async e=>{const f=e.target.files[0];if(!f)return;try{const content=await f.text();const selected={project:state.project,type:state.resourceType,id:state.resourceId};await api(`/api/projects/${state.project}/data`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:f.name,content})});await reloadProjects();if(selected.id)await selectResource(selected.project,selected.type,selected.id);alertStatus('已导入 '+f.name);}catch(err){alert(err.message);}e.target.value='';};
(async()=>{try{const r=await api('/api/projects');state.projects=r.projects;drawTree();alertStatus(`项目目录：${r.root}`);if(r.projects[0]?.charts[0])await select(r.projects[0].id,r.projects[0].charts[0]);if(!r.llm_enabled)bubble('尚未配置 OPENAI_API_KEY。可以查看图、编辑代码和版本；配置密钥后即可对话改图。');}catch(e){alertStatus(e.message);}})();
