const $ = id => document.getElementById(id);
const state = {projects: [], project: null, chart: null, detail: null, proposal: null, openProjects: new Set()};
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const endpoint = action => `/api/projects/${encodeURIComponent(state.project)}/charts/${encodeURIComponent(state.chart)}/${action}`;
async function api(url, options) { const r = await fetch(url, options); const data = await r.json(); if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`); return data; }
function alertStatus(s) { $('status').textContent = s; }
function bubble(s, cls='assistant') { const e=document.createElement('div'); e.className='bubble '+cls; e.textContent=s; $('messages').append(e); $('messages').scrollTop=$('messages').scrollHeight; }
function tab(name) { document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.dataset.tab===name)); for(const n of ['figure','code','data']) $(n+'Pane').classList.toggle('hide',n!==name); }
function drawTree() {
  $('tree').innerHTML=state.projects.map(p=>{
    const open=state.openProjects.has(p.id);
    return `<section class="projectGroup"><button class="projectName" data-toggle="${esc(p.id)}">${open?'▾':'▸'} ${esc(p.name)}</button><div class="projectContents ${open?'':'hide'}"><div class="folder">⌄ 绘图代码</div>${p.charts.map(c=>`<button class="file ${state.project===p.id&&state.chart===c?'active':''}" data-project="${esc(p.id)}" data-chart="${esc(c)}">${esc(c)}.py</button>`).join('')}<div class="folder">⌄ 数据集</div>${p.data.map(d=>`<div class="csv">▦ ${esc(d)}</div>`).join('')}</div></section>`;
  }).join('');
  document.querySelectorAll('[data-toggle]').forEach(e=>e.onclick=()=>{const id=e.dataset.toggle;state.openProjects.has(id)?state.openProjects.delete(id):state.openProjects.add(id);drawTree();});
  document.querySelectorAll('.file').forEach(e=>e.onclick=()=>select(e.dataset.project,e.dataset.chart));
}
function drawHistory() { const h=state.detail.history; $('historyCount').textContent=h.length+' 条'; $('history').innerHTML=h.length?h.slice().reverse().map(x=>`<div class="historyItem"><strong>${esc(x.note)}</strong><time>${esc(new Date(x.time).toLocaleString('zh-CN'))} · ${esc(x.id)}</time><button data-id="${esc(x.id)}">恢复此版本 ↗</button></div>`).join(''):'<div class="placeholder">当前是初始版本。保存一次修改后会出现历史记录。</div>'; document.querySelectorAll('.historyItem button').forEach(e=>e.onclick=()=>restore(e.dataset.id)); }
function drawData() { $('dataInfo').innerHTML=state.detail.data.map(d=>`<section><h3>▦ ${esc(d.file)}</h3><table><thead><tr>${d.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${d.sample.map(r=>`<tr>${r.map(x=>`<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table><p class="hint">显示前 3 行 · 数据文件位于项目 data/ 目录</p></section>`).join(''); }
async function preview() { $('figure').hidden=true; $('empty').hidden=false; $('empty').textContent='正在渲染…'; const r=await fetch(endpoint('preview')+'?v='+Date.now()); if(!r.ok){const e=await r.json(); throw new Error(e.error);} const blob=await r.blob(); if($('figure').dataset.url) URL.revokeObjectURL($('figure').dataset.url); const u=URL.createObjectURL(blob); $('figure').src=u; $('figure').dataset.url=u; $('figure').hidden=false; $('empty').hidden=true; alertStatus('已渲染 · '+new Date().toLocaleTimeString('zh-CN')); }
async function select(project,chart) { state.openProjects.add(project); state.project=project;state.chart=chart;state.proposal=null;$('proposal').hidden=true;drawTree();const p=state.projects.find(x=>x.id===project);$('breadcrumb').textContent=`${p.name.toUpperCase()} / CHARTS / ${chart.toUpperCase()}`;$('chartTitle').textContent=chart.replaceAll('_',' ');$('description').textContent=p.description;$('filename').textContent=chart+'.py';$('refresh').disabled=false;$('svg').hidden=false;$('pdf').hidden=false;$('svg').href=endpoint('svg');$('pdf').href=endpoint('pdf');try{state.detail=await api(endpoint('detail'));$('editor').value=state.detail.code;$('skillText').textContent=state.detail.style;drawHistory();drawData();tab('figure');await preview();}catch(e){alertStatus(e.message);$('empty').textContent=e.message;} }
async function post(action,body){return api(endpoint(action),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
async function apply(code,note){try{$('saveCode').disabled=true;$('apply').disabled=true;const r=await post('apply',{code,note});bubble(r.message);state.proposal=null;$('proposal').hidden=true;await select(state.project,state.chart);}catch(e){bubble(e.message,'error');}finally{$('saveCode').disabled=false;$('apply').disabled=false;}}
async function restore(id){if(!confirm('将此历史版本恢复为新的当前版本？原版本仍保留。'))return;try{await post('restore',{id});await select(state.project,state.chart);bubble('已恢复历史版本。');}catch(e){bubble(e.message,'error');}}
$('chatForm').onsubmit=async e=>{e.preventDefault();if(!state.chart){bubble('请先选择一张图。','error');return;}const prompt=$('prompt').value.trim();if(!prompt)return;$('prompt').value='';bubble(prompt,'user');alertStatus('正在生成修改建议…');try{const r=await post('propose',{prompt});state.proposal={code:r.code,prompt};$('proposal').hidden=false;bubble(r.reply);alertStatus('待审核修改');}catch(e){bubble(e.message,'error');alertStatus('修改建议未生成');}};
$('prompt').onkeydown=e=>{if(e.key==='Enter'&&e.ctrlKey){e.preventDefault();$('chatForm').requestSubmit();}};
$('inspect').onclick=()=>{if(state.proposal){$('editor').value=state.proposal.code;tab('code');}};
$('apply').onclick=()=>{if(state.proposal)apply(state.proposal.code,state.proposal.prompt);};
$('saveCode').onclick=()=>{if(state.chart)apply($('editor').value,'手动编辑绘图代码');};
$('refresh').onclick=async()=>{try{await preview();}catch(e){alertStatus(e.message);bubble(e.message,'error');}};
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
  $('codeFolderStatus').textContent='尚未选择';$('dataFolderStatus').textContent='尚未选择';
  $('uploadDialog').showModal();
};
$('closeUpload').onclick=()=>$('uploadDialog').close();
$('uploadProjectMode').onchange=e=>{$('newProjectFields').hidden=e.target.value!=='__new__';};
$('codeFolder').onchange=e=>{$('codeFolderStatus').textContent=e.target.files.length?`${e.target.files.length} 个 Python 文件`:'尚未选择';};
$('dataFolder').onchange=e=>{$('dataFolderStatus').textContent=e.target.files.length?`${e.target.files.length} 个数据文件`:'尚未选择';};
$('startUpload').onclick=async()=>{
  const existing=$('uploadProjectMode').value!=='__new__';
  const chosen=existing?state.projects.find(p=>p.id===$('uploadProjectMode').value):null;
  const name=existing?chosen.name:$('uploadProjectName').value.trim();
  const project_id=existing?chosen.id:$('uploadProjectId').value.trim();
  const codeFiles=[...$('codeFolder').files],dataFiles=[...$('dataFolder').files];
  if(!name||!project_id){alert('请填写项目名称和项目 ID。');return;}
  if(!codeFiles.length||!dataFiles.length){alert('请分别选择代码文件夹和数据文件夹。');return;}
  $('startUpload').disabled=true;alertStatus('Agent 正在归档、拆分并验证…');
  try{
    const code=await Promise.all(codeFiles.filter(f=>f.name.endsWith('.py')).map(async f=>({name:f.name,path:f.webkitRelativePath,kind:'code',content:await f.text()})));
    const data=await Promise.all(dataFiles.filter(f=>/\.(csv|tsv|json)$/i.test(f.name)).map(async f=>({name:f.name,path:f.webkitRelativePath,kind:'data',content:await f.text()})));
    if(!code.length||!data.length)throw new Error('所选目录中没有可用的 Python 或数据文件。');
    const r=await api('/api/uploads/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,project_id,existing,files:[...code,...data]})});
    $('uploadDialog').close();await reloadProjects();state.openProjects.add(r.project);
    const sync=r.github_synced?'已同步到 GitHub':'GitHub 同步失败：'+(r.github_error||'未知错误');
    bubble(`项目“${name}”已处理：${r.files} 个数据文件，${r.charts.length} 张图表；${sync}。`);
    if(r.charts[0])await select(r.project,r.charts[0]);
  }catch(err){bubble(err.message,'error');alertStatus('上传拆分失败');}
  finally{$('startUpload').disabled=false;}
};

$('importCsv').onclick=()=>{if(!state.project){alert('请先创建或选中项目。');return;}$('csvFile').click();};
$('csvFile').onchange=async e=>{const f=e.target.files[0];if(!f)return;try{const content=await f.text();await api(`/api/projects/${state.project}/data`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:f.name,content})});await reloadProjects();if(state.chart)await select(state.project,state.chart);alertStatus('已导入 '+f.name);}catch(err){alert(err.message);}e.target.value='';};
(async()=>{try{const r=await api('/api/projects');state.projects=r.projects;drawTree();alertStatus(`项目目录：${r.root}`);if(r.projects[0]?.charts[0])await select(r.projects[0].id,r.projects[0].charts[0]);if(!r.llm_enabled)bubble('尚未配置 OPENAI_API_KEY。可以查看图、编辑代码和版本；配置密钥后即可对话改图。');}catch(e){alertStatus(e.message);}})();
