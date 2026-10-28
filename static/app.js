const $ = id => document.getElementById(id);
const chatStartedAt = new Map();
const state = {projects: [], project: null, chart: null, detail: null, openProjects: new Set(), selectedCharts: new Set(), previews: new Map(), galleryVersion: 0, skills: [], historyChart: null, chatKey: '', chatDisplayProject: null, chatSessions: new Map(), chatSessionLists: new Map(), chatLoads: new Map(), projectChatHistory: new Map(), projectChatLoaded: new Set(), projectChatLoads: new Map(), projectChatErrors: new Map(), chatBusy: new Set(), chatReferences: new Map(), chatErrors: new Map(), chatPending: new Map(), chatPolling: new Set(), detailRequest: 0};
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const savedTheme=localStorage.getItem('plot-forge-theme')||'dark';
document.documentElement.dataset.theme=savedTheme;
function updateThemeButton(){const light=document.documentElement.dataset.theme==='light';$('themeToggle').textContent=light?'☾ 深色':'☀ 浅色';}
$('themeToggle').onclick=()=>{const next=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=next;localStorage.setItem('plot-forge-theme',next);updateThemeButton();};
updateThemeButton();

const chartEndpoint = (project, chart, action) => `/api/projects/${encodeURIComponent(project)}/charts/${encodeURIComponent(chart)}/${action}`;
const endpoint = action => chartEndpoint(state.project,state.chart,action);
function uploadRelativePath(file){const parts=(file.webkitRelativePath||'').split('/');return parts.length>1?parts.slice(1).join('/'):file.name;}
async function api(url, options) { const r = await fetch(url, options); const data = await r.json(); if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`); return data; }
function alertStatus(s) { $('status').textContent = s; }
function bubble(s, cls='assistant') { const e=document.createElement('div'); e.className='bubble '+cls; e.textContent=s; $('messages').append(e); $('messages').scrollTop=$('messages').scrollHeight; }
function updateModelTransportNotice(){const notice=$("modelTransportNotice");if(notice)notice.hidden=!$("modelApiUrl").value.trim().toLowerCase().startsWith("http://");}
$("modelApiUrl").oninput=updateModelTransportNotice;
function showModelConfig(config){updateModelTransportNotice();$('modelConfigBadge').textContent=config.key_configured?'已配置':'未配置';$('modelConfigButton').title=config.key_configured?'模型 API 已配置':'配置模型 API';$('modelApiUrl').value=config.api_url||'';updateModelTransportNotice();$('modelName').value=config.model||'';$('modelMaxOutputTokens').value=config.max_output_tokens||16384;$('modelApiKey').value='';$('modelVision').checked=!!config.vision_enabled;state.modelPreset=config.intranet_preset||null;$('useCdscPreset').disabled=!state.modelPreset;$('useCdscPreset').hidden=!state.modelPreset;const source=config.key_source==='session'?'当前会话可用：系统密钥存储不可用，重启后台后需重新输入 API Key':config.key_source==='windows_encrypted'?'已使用 Windows 用户加密保存，重启后仍可使用':config.keyring_available===false?'本机钥匙串暂不可用，请从普通终端启动工作台':config.key_source==='keychain'?'已保存在本机钥匙串':config.key_source==='environment'?'已由运行环境配置':'尚未配置 API Key';$('modelConfigState').textContent=source;$('modelConfigState').className=config.key_configured?'ok':'';$('testModelConfig').disabled=!config.key_configured;$('clearModelConfig').disabled=!['keychain','windows_encrypted','session'].includes(config.key_source);if(config.key_configured)document.querySelectorAll('.configNotice').forEach(e=>e.remove());}
async function loadModelConfig(){const config=await api('/api/model-config');showModelConfig(config);return config;}
$('modelConfigButton').onclick=async()=>{try{await loadModelConfig();$('modelConfigDialog').showModal();}catch(e){alertStatus('无法读取模型配置：'+e.message);}};
$('closeModelConfig').onclick=()=>$('modelConfigDialog').close();
$('useCdscPreset').onclick=()=>{if(!state.modelPreset)return;$('modelApiUrl').value=state.modelPreset.api_url;updateModelTransportNotice();$('modelName').value=state.modelPreset.model||$('modelName').value;$('modelConfigState').className='';$('modelConfigState').textContent='已填入默认模型与地址；请填写本机 API Key 并保存。HTTP 连接会传输 API Key 和请求内容。';};
$('modelConfigForm').onsubmit=async e=>{e.preventDefault();const save=$('saveModelConfig');save.disabled=true;$('modelConfigState').textContent='正在安全保存到本机…';try{const config=await api('/api/model-config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_url:$('modelApiUrl').value.trim(),model:$('modelName').value.trim(),max_output_tokens:Number($('modelMaxOutputTokens').value),api_key:$('modelApiKey').value,vision_enabled:$('modelVision').checked})});showModelConfig(config);$('modelConfigState').textContent=config.key_source==='session'?'配置已在当前会话生效，可测试连接或改图；系统密钥存储不可用，重启后台后需重新输入 API Key。':'已保存。规范化和对话改图可直接使用；可点击“测试已保存配置”。';alertStatus('模型 API 配置已保存');}catch(err){$('modelConfigState').className='error';$('modelConfigState').textContent=err.message;}finally{save.disabled=false;$('modelApiKey').value='';}};
$('testModelConfig').onclick=async()=>{const button=$('testModelConfig');button.disabled=true;$('modelConfigState').className='';$('modelConfigState').textContent='正在连接模型服务…';try{const result=await api('/api/model-config/test',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});$('modelConfigState').className='ok';$('modelConfigState').textContent=`连接成功：${result.model}（${result.elapsed_ms} ms）`;}catch(err){$('modelConfigState').className='error';$('modelConfigState').textContent=err.message;}finally{button.disabled=false;}};
$('clearModelConfig').onclick=async()=>{if(!confirm('清除保存在本机的模型 API Key 和地址、模型配置？'))return;try{const config=await api('/api/model-config',{method:'DELETE',headers:{'Content-Type':'application/json'}});showModelConfig(config);$('modelConfigState').textContent='页面保存的配置已清除。';alertStatus('模型 API 配置已清除');}catch(err){$('modelConfigState').className='error';$('modelConfigState').textContent=err.message;}};
function tab(name) { document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.dataset.tab===name)); for(const n of ['figure','code','data']) $(n+'Pane').classList.toggle('hide',n!==name); }
function toggleProject(id){
  if(state.openProjects.has(id)){state.openProjects.delete(id);drawTree();}
  else showProject(id,true);
}
function fitChartCanvas(card,img){
  const fit=()=>{
    if(!img.naturalWidth||!img.naturalHeight)return;
    const ratio=img.naturalWidth/img.naturalHeight;
    const oversized=Math.max(img.naturalWidth,img.naturalHeight)>=4096||
      img.naturalWidth*img.naturalHeight>=12000000||ratio<0.4;
    card.dataset.canvas=oversized?'oversized':ratio>2.8?'panorama':ratio>1.6?'wide':ratio<0.8?'portrait':'standard';
    card.style.setProperty('--canvas-ratio',String(ratio));
  };
  img.onload=fit;
  if(img.complete)fit();
}
function drawTree() {
  $('tree').innerHTML=state.projects.map(p=>{
    const open=state.openProjects.has(p.id);
    return `<section class="projectGroup"><div class="projectRow"><button class="projectName ${state.project===p.id?'current':''}" aria-expanded="${open}" data-toggle="${esc(p.id)}">${open?'▾':'▸'} ${esc(p.name)}${p.created_by?' · '+esc(p.created_by):''} <span class="projectChartCount">${p.charts.length}</span></button><button class="projectBulk" data-bulk-project="${esc(p.id)}" title="选择本项目全部图表并批量修改">批量修改</button></div><div class="projectContents ${open?'':'hide'}"><div class="folder">⌄ 绘图代码 <button class="inlineAction" data-add-chart="${esc(p.id)}">＋ 绘图</button></div>${p.charts.map(c=>`<button class="file ${state.project===p.id&&state.chart===c?'active':''}" data-project="${esc(p.id)}" data-chart="${esc(c)}">${esc(c)}.py</button>`).join('')}${(p.modules||[]).length?'<div class="folder">⌄ 共享绘图模块</div>'+p.modules.map(m=>`<button class="file moduleFile" data-module-project="${esc(p.id)}" data-module-id="${esc(m.id)}">${esc(m.path)}</button>`).join(''):''}<div class="folder">⌄ 数据集 <button class="inlineAction" data-add-csv="${esc(p.id)}">＋ CSV</button></div>${p.data.map(d=>`<div class="csv">▦ ${esc(d)}</div>`).join('')}</div></section>`;
  }).join('');
  document.querySelectorAll('[data-toggle]').forEach(e=>e.onclick=()=>toggleProject(e.dataset.toggle));
  document.querySelectorAll('.file').forEach(e=>e.onclick=()=>select(e.dataset.project,e.dataset.chart));
  document.querySelectorAll('[data-bulk-project]').forEach(e=>e.onclick=()=>{showProject(e.dataset.bulkProject,true);selectAllCharts(true);$('gallery').scrollIntoView({block:'start',behavior:'smooth'});});
  document.querySelectorAll('[data-module-id]').forEach(e=>e.onclick=()=>window.openSharedModule(e.dataset.moduleProject,e.dataset.moduleId));
  document.querySelectorAll('[data-add-chart]').forEach(e=>e.onclick=()=>newChart(e.dataset.addChart));
  document.querySelectorAll('[data-add-csv]').forEach(e=>e.onclick=()=>importCsv(e.dataset.addCsv));
}
function drawHistory(){if(!state.detail)return;const h=state.detail.history,chart=state.chart,project=state.project;$('historyTitle').textContent=`${chartName(project,chart)} · 图片历史（${h.length}）`;$('history').innerHTML=h.length?h.slice().reverse().map((x,i)=>`<div class="historyItem"><strong>${esc(x.note)}${i===0?' · 当前版':''}</strong><time>${esc(new Date(x.time).toLocaleString('zh-CN'))}</time>${x.image_available?`<img class="historyImage" loading="lazy" src="${chartEndpoint(project,chart,'history')}/${encodeURIComponent(x.id)}/image" alt="${esc(x.note)} 的图像">`:'<p class="dim">旧版本未保存图片</p>'}${x.code_available?`<button data-id="${esc(x.id)}">恢复此版本代码 ↗</button>`:'<span class="dim">仅保留图片</span>'}</div>`).join(''):'<div class="placeholder">这张图还没有修改历史。</div>';document.querySelectorAll('.historyItem button').forEach(e=>e.onclick=()=>restore(e.dataset.id));}
function drawData() { $('dataInfo').innerHTML=state.detail.data.map(d=>`<section><h3>▦ ${esc(d.file)}</h3><table><thead><tr>${d.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${d.sample.map(r=>`<tr>${r.map(x=>`<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table><p class="hint">显示前 3 行 · 数据文件位于项目 data/ 目录</p></section>`).join(''); }
function projectInfo(id){return state.projects.find(p=>p.id===id);}
function chartName(project,chart){return projectInfo(project)?.chart_metadata?.[chart]?.display_name||chart;}
function orderedCharts(p){const groups=new Map();for(const chart of p?.charts||[]){const key=p.chart_metadata?.[chart]?.group_key||'fallback:'+chart;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(chart);}return [...groups.values()].flat();}
function syncChartNames(){const p=projectInfo(state.project);if(!p)return;for(const chart of orderedCharts(p)){const card=[...$('gallery').children].find(c=>c.dataset.chart===chart);if(!card)continue;const name=chartName(state.project,chart);card.querySelector('.chartName').textContent=name;card.querySelector('.chartName').title=name+' · '+chart+'.py';card.querySelector('.chartCheck').setAttribute('aria-label','选择 '+name);card.querySelector('.chartOpen').setAttribute('aria-label','打开 '+name);const diagnostic=(p.chart_diagnostic_previews||[]).includes(chart);let note=card.querySelector('.chartImportWarning');if(diagnostic){if(!note){note=document.createElement('p');note.className='chartImportWarning';card.append(note);}note.textContent='布局警告预览：'+(p.chart_warnings?.[chart]||'后续原程序检查未完成');}else if(note)note.remove();const image=card.querySelector('img');if(image)image.alt=name+(diagnostic?' 布局警告预览':' 图像预览');$('gallery').append(card);}if(state.chart)$('chartTitle').textContent=chartName(state.project,state.chart);updateSelection();}
async function refreshChartNames(){const r=await api('/api/projects');for(const p of state.projects){const fresh=r.projects.find(x=>x.id===p.id);if(fresh){p.chart_metadata=fresh.chart_metadata;p.chart_warnings=fresh.chart_warnings||{};p.chart_diagnostic_previews=fresh.chart_diagnostic_previews||[];}}syncChartNames();}
function updateSelection(){const p=projectInfo(state.project),total=p?.charts.length||0,count=state.selectedCharts.size;$('selectedCount').textContent=`已选 ${count} 张`;$('selectAllCharts').checked=total>0&&count===total;$('selectAllCharts').indeterminate=count>0&&count<total;$('selectAllCharts').disabled=!total;document.querySelectorAll('.chartCard').forEach(card=>{const selected=state.selectedCharts.has(card.dataset.chart);card.classList.toggle('selected',selected);const box=card.querySelector('.chartCheck');if(box)box.checked=selected;});syncChatContext();}

function selectAllCharts(on){state.selectedCharts=new Set(on?(projectInfo(state.project)?.charts||[]):[]);updateSelection();}
// A chat context is the exact set shown in its header. Async responses never change it.
function chatContext(){const charts=(state.selectedCharts.size?[...state.selectedCharts]:state.chart?[state.chart]:[]).sort();return {project:state.project,charts,key:state.project&&charts.length?JSON.stringify([state.project,charts]):''};}
function sessionEndpoint(context,id='',suffix=''){return `/api/projects/${encodeURIComponent(context.project)}/chat/sessions${id?'/'+encodeURIComponent(id):''}${suffix?'/'+suffix:''}`;}
function postJSON(url,body){return api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
function selectedReferences(key=state.chatKey){return [...(state.chatReferences.get(key)||[])];}
function sessionMatches(session,context){const charts=(session.charts||[]).map(c=>typeof c==='string'?c:c.chart).sort();return JSON.stringify(charts)===JSON.stringify(context.charts);}
function referenceRoutes(session){return (session.references||session.reference_charts||[]).map(r=>typeof r==='string'?r:r.chart).filter(Boolean);}
function storeSession(context,session){state.chatSessions.set(context.key,session);const list=state.chatSessionLists.get(context.key)||[];state.chatSessionLists.set(context.key,[session,...list.filter(x=>x.id!==session.id)]);const history=state.projectChatHistory.get(context.project)||[];state.projectChatHistory.set(context.project,[session,...history.filter(x=>x.id!==session.id)]);}
async function loadProjectChatHistory(project){
  if(!project||state.projectChatLoaded.has(project))return state.projectChatHistory.get(project)||[];
  if(state.projectChatLoads.has(project))return state.projectChatLoads.get(project);
  const task=(async()=>{const result=await api(`/api/projects/${encodeURIComponent(project)}/chat/history`);const byId=new Map((result.sessions||[]).map(session=>[session.id,session]));for(const session of state.projectChatHistory.get(project)||[])byId.set(session.id,session);const sessions=[...byId.values()];state.projectChatHistory.set(project,sessions);state.projectChatLoaded.add(project);state.projectChatErrors.delete(project);if(state.project===project)renderChat();return sessions;})();
  state.projectChatLoads.set(project,task);
  try{return await task;}catch(error){state.projectChatErrors.set(project,error.message);if(state.project===project)renderChat();throw error;}finally{state.projectChatLoads.delete(project);}
}
function syncChatContext(){const context=chatContext(),changed=state.chatKey!==context.key,projectChanged=state.chatDisplayProject!==context.project;state.chatKey=context.key;$('chatTargets').innerHTML=context.charts.length?`<strong>修改目标 · ${context.charts.length} 张 · ${esc(projectInfo(context.project)?.name||'')}</strong><div class="targetChips">${context.charts.map(chart=>`<span title="${esc(chart)}.py">${esc(chartName(context.project,chart))}</span>`).join('')}</div>`:'尚未选择图表';renderChatReferences();if(changed||projectChanged)renderChat();if(changed&&context.key)loadChatSessions(context).catch(error=>{state.chatErrors.set(context.key,error.message);if(state.chatKey===context.key)renderChat();});if(context.project&&!state.projectChatLoaded.has(context.project)&&!state.projectChatLoads.has(context.project))loadProjectChatHistory(context.project).catch(()=>{});updateChatControls();}
async function loadChatSessions(context,preferredId){if(state.chatLoads.has(context.key))return state.chatLoads.get(context.key);if(state.chatSessionLists.has(context.key))return state.chatSessions.get(context.key);const task=(async()=>{const r=await api(sessionEndpoint(context)+'?charts='+encodeURIComponent(context.charts.join(',')));const list=(r.sessions||[]).filter(s=>!s.charts||sessionMatches(s,context));state.chatSessionLists.set(context.key,list);if(list.length){const chosen=list.find(s=>s.id===preferredId)||list[0];const session=Array.isArray(chosen.turns)&&Array.isArray(chosen.drafts)?chosen:await api(sessionEndpoint(context,chosen.id));storeSession(context,session);if(!state.chatReferences.has(context.key))state.chatReferences.set(context.key,new Set(referenceRoutes(session)));}if(state.chatKey===context.key){renderChatReferences();renderChat();}return state.chatSessions.get(context.key);})();state.chatLoads.set(context.key,task);updateChatControls();try{return await task;}finally{state.chatLoads.delete(context.key);if(state.chatKey===context.key)updateChatControls();}}
async function ensureChatSession(context){await loadChatSessions(context);let session=state.chatSessions.get(context.key);if(!session||session.status==='closed'){session=await postJSON(sessionEndpoint(context),{charts:context.charts,reference_charts:selectedReferences(context.key)});storeSession(context,session);}return session;}
function renderChatReferences(){const context=chatContext(),refs=new Set(selectedReferences());const available=orderedCharts(projectInfo(context.project)).filter(c=>!context.charts.includes(c));state.chatReferences.set(context.key,new Set([...refs].filter(c=>available.includes(c))));$('chatReferenceChoices').innerHTML=available.length?available.map(c=>`<label><input type="checkbox" data-reference="${esc(c)}" ${refs.has(c)?'checked':''}> <span title="${esc(c)}.py">${esc(chartName(context.project,c))}</span></label>`).join(''):'<p class="hint">当前项目没有其他可参照的图。</p>';$('chatReferenceSummary').textContent=`参照图 · 只读（${selectedReferences().length}）`;$('chatReferenceChoices').querySelectorAll('input').forEach(box=>box.onchange=()=>{const set=new Set(selectedReferences());box.checked?set.add(box.dataset.reference):set.delete(box.dataset.reference);state.chatReferences.set(state.chatKey,set);$('chatReferenceSummary').textContent=`参照图 · 只读（${set.size}）`;});updateChatControls();}
function updateChatControls(){if(typeof renderPanelControls==='function')renderPanelControls();const context=chatContext(),session=state.chatSessions.get(context.key),busy=state.chatBusy.has(context.key)||session?.status==='running',loading=state.chatLoads.has(context.key),phase={preparing:'准备图表资料',model_request:'等待模型生成代码',rendering:'渲染并检查候选图',repairing:'修正候选图'}[session?.progress?.stage];$('sendChat').disabled=!context.key||busy||loading;$('sendChat').textContent=busy?'正在生成…':'生成候选 ↗';$('chatState').textContent=busy?(phase||'生成中'):loading?'读取会话…':'先预览，再应用';$('chatSendHint').textContent=busy?'本轮完成后可继续对话；切换图不会混入结果':'Enter 发送 · Shift + Enter 换行';$('newChatSession').disabled=!context.key||busy||loading;$('chatSessionPicker').disabled=busy||loading||!(state.chatSessionLists.get(context.key)||[]).length;$('batchNormalize').disabled=!state.selectedCharts.size||busy||loading;$('batchEdit').disabled=!state.selectedCharts.size||busy;$('chatReferenceChoices').querySelectorAll('input').forEach(x=>x.disabled=busy||loading);$('messages').querySelectorAll('[data-draft-action],[data-layout-override],[data-retry-turn]').forEach(x=>x.disabled=x.dataset.blocked==='true'||busy||loading);}
function readable(value){if(value===null||value===undefined)return '';if(typeof value==='string'){return value.replace(/^Agent request failed: /,'').replace('模型没有返回改图方案；请重试或更换模型。','模型生成阶段：模型没有返回可用的改图方案；图片和代码均未修改。').replace('Interpreted operation targets a different chart','目标校验阶段：模型将修改说明指向了别的图，系统已拦截；图片和代码均未修改。').replace('Operation must specify element, property, current value and desired change','意图结构校验阶段：模型的修改说明缺少“目标元素、属性、当前值、期望变化”中的至少一项；图片和代码均未修改。');}if(Array.isArray(value))return value.map(readable).filter(Boolean).join('\n');return value.message||value.reason||value.summary||value.description||JSON.stringify(value);}
function asList(value){return Array.isArray(value)?value:value?[value]:[];}
function warningList(record){const issues=[...asList(record.warnings),...asList(record.layout?.issues)];return [...new Map(issues.map(x=>[readable(x),x])).values()];}
function warningIds(record){return [...new Set(asList(record.layout?.issues).map(x=>typeof x==='object'&&(x.warning_id||x.issue_id||x.id)).filter(Boolean))];}
function warningsHTML(record){const warnings=warningList(record);return warnings.length?`<details class="draftWarnings" open><summary>请留意 <span>（${warnings.length} 条）</span></summary><ul>${warnings.map(x=>`<li>${esc(readable(x))}</li>`).join('')}</ul></details>`:'';}
function reviewList(title, items, format=readable){const values=asList(items).map(format).filter(Boolean);return values.length?`<section><strong>${esc(title)}</strong><ul>${values.map(value=>`<li>${esc(value)}</li>`).join('')}</ul></section>`:'';}
function renderDraftReview(draft){
  const proposal=draft.proposal||{},interpreted=proposal.interpreted_request||{},layout=draft.layout||{},checks=proposal.normalization_checks;
  let body=reviewList('本轮修改理解',interpreted.operations||interpreted.changes,operation=>{
    if(typeof operation!=='object'||operation===null)return readable(operation);
    const quotes=asList(operation.source_quotes).join('；'),element=operation.target_element||operation.element;
    return [quotes?'原话：“'+quotes+'”':'',element?'对象：'+readable(element):'',operation.property?'属性：'+readable(operation.property):'',operation.current_value!==undefined?'原值：'+readable(operation.current_value):'',operation.desired_change!==undefined?'拟改为：'+readable(operation.desired_change):''].filter(Boolean).join('\n')||readable(operation);
  });
  body+=reviewList('需要保留',interpreted.preserve,item=>typeof item==='object'&&item!==null?readable(item.details||item.constraints||item.description||item):readable(item));
  body+=reviewList('预期效果（仍需对照候选审阅）',proposal.expected_effects,effect=>{
    if(typeof effect!=='object'||effect===null)return readable(effect);
    return [readable(effect.observable_change||effect.description||effect.summary),effect.preservation_checks?'保留检查：'+readable(effect.preservation_checks):'',effect.review_required?'需审阅：'+readable(effect.review_required):''].filter(Boolean).join('\n')||readable(effect);
  });
  const transform=draft.chart_transform;
  if(transform){
    body+=`<section><strong>图型转换数据核对</strong><p>${esc(transform.reason||transform.status)}</p></section>`;
    body+=reviewList('原始样本与分组',transform.matches,item=>['scatter','line'].includes(transform.kind)?`${item.label}：${item.count} 个坐标逐点一致（${item.axis}）`:`${item.path} · ${item.group_column} / ${item.value_column}：${asList(item.groups).map(g=>`${g.label}（${g.count} 个样本）`).join('，')}`);
  }
  const visual=draft.visual_change;
  if(visual){
    const unchanged=visual.status==='identical';
    const ylabelRatio=visual.text_ink_ratios?.['axes_0.ylabel'];
    body+=`<section><strong>实际图像变化</strong><p>${unchanged?'候选图与上一版逐像素相同。':visual.changed_pixels!==undefined?`与上一版相比，有 ${esc(visual.changed_pixels)} 个像素发生变化。`:'图片尺寸或内容发生变化。'}</p>${ylabelRatio!==undefined?`<p>Y 轴标题墨色约为上一版的 ${esc(Math.round(ylabelRatio*100))}%（近似视觉量，仍需查看图片）。</p>`:''}</section>`;
  }
  if(layout.status){
    const labels={pass:'检测范围内未发现布局冲突',conflict:'发现布局冲突',unverified:'部分布局未能自动确认',accepted_exception:'按已明确接受的布局例外执行'};
    body+=`<section><strong>实际布局检查</strong><p>${esc(labels[layout.status]||layout.status)}</p>${layout.scope?`<p>范围：${esc(layout.scope==='text_spines_canvas_and_panel_spacing'?'文字、坐标轴线、导出边界及相邻子图间距':layout.scope==='text_spines_and_canvas'?'文字、坐标轴线及导出画布边界':readable(layout.scope))}</p>`:''}<p>这些检查不能保证所有视觉元素都没有遮挡，请结合候选图片审阅。</p></section>`;
  }
  if(layout.panel_spacing){
    const spacing=layout.panel_spacing;
    body+=reviewList('同一画布的子图间距',spacing.pairs,item=>{
      const names=asList(item.panels).map(index=>'子图 '+(index+1)).join(' 与 ');
      if(item.status==='unverified')return names+'：无法确认轴标题与轴线距离';
      return names+'（'+(item.direction==='horizontal'?'左右':'上下')+'）：实际留白 '+item.gap_px+' px，最低 '+item.required_px+' px · '+(item.status==='pass'?'符合':'不足');
    });
  }
  const limitationLabels={
    'Checks use Matplotlib text bounding boxes at the final PNG save size.':'按最终 PNG 导出尺寸检查 Matplotlib 文字边界。',
    'Data curve crossings and heatmap-cell/text overlays are intentional and excluded.':'正常数据曲线交叉、热图单元格与其文字叠放不计为布局冲突。',
    'Text against arbitrary data artists, 3D/custom artists, and visual meaning require review.':'文字与任意数据图元的遮挡、三维或自定义图元，以及视觉含义，仍需人工审阅。',
  };
  body+=reviewList('检查限制',layout.limitations,value=>limitationLabels[readable(value)]||readable(value));
  if(checks){
    const status=checks.status==='pass'?'代码结构检查通过':checks.status==='fail'?'代码结构检查未通过':readable(checks.status)||'已记录';
    body+=`<section><strong>标准化静态检查</strong><p>${esc(status)}</p><p>静态结果只说明代码结构；固定字号、间距等视觉规范需另行核对，不代表所有视觉规则均已通过。</p></section>`;
    body+=reviewList('静态检查发现的问题',checks.violations);
    if(checks.note)body+=reviewList('静态检查说明',checks.note==='Static check only; visual values require running and inspecting the Figure.'?'仅进行静态检查，视觉数值需要运行并检查图像。':checks.note);
  }
  const runtime=draft.normalization_report;
  if(runtime){
    const templates=runtime.templates||runtime.matched_template;
    body+=`<section><strong>标准化运行报告</strong>${runtime.profile_version?`<p>样式版本：${esc(runtime.profile_version)}</p>`:''}<p>模板：${esc(templates?readable(templates):'未匹配图种模板，保留原始几何布局')}</p></section>`;
    const warningLabels={
      'missing_template: preserve multi-panel, twin-axis or non-Cartesian geometry':'当前图不匹配单图模板，已保留多子图、双轴或非笛卡尔坐标的几何布局。',
      'font_weight_unverified: installed CJK font lacks the requested heavy face':'已安装的中文字体缺少要求的粗体字形，字重效果尚未确认。',
      'multiple_colorbars: no single colorbar template':'图中有多条色条，未应用单色条位置模板。',
    };
    body+=reviewList('运行提示',runtime.warnings,value=>warningLabels[readable(value)]||readable(value));
    body+=reviewList('字体替代及未确认效果',runtime.font_substitutions,item=>{
      if(typeof item!=='object'||item===null)return readable(item);
      return [item.text?'文字：'+item.text:'',item.requested_family?'要求字体：'+item.requested_family:'',item.requested_weight!==undefined?'要求字重：'+item.requested_weight:'',item.selected_family?'实际选用：'+item.selected_family:'',item.reason?'原因：'+item.reason:''].filter(Boolean).join('\n');
    });
    body+=reviewList('已移除图上方标题',runtime.removed_titles);
  }
  const font=draft.font_audit;
  if(font){
    const used=[...new Set(asList(font.fonts).map(x=>x.actual_family+'（'+x.font_file+'）'))];
    body+=reviewList('导出图片实际字体',used);
    body+=reviewList('缺失原字体与替代',font.substitutions,item=>item.requested_family+' → '+item.selected_family+'：'+item.text);
    body+=reviewList('无法显示的字符',font.missing_glyphs,item=>item.font+' 缺少 '+item.characters+'：'+item.text);
  }
  return body?`<details class="draftReview"><summary>修改理解与检查结果</summary>${body}</details>`:'';
}
const statusNames={preview_ready:'候选 · 待审阅',candidate:'候选',needs_clarification:'需要你确认',needs_context:'需要补充上下文',cannot_complete:'无法完成',validation_failed:'检查未通过',font_unverified:'字体效果未达要求',no_visible_change:'图像变化未达要求',axis_unmet:'坐标轴未达要求',render_failed:'渲染失败',agent_failed:'生成失败',scope_rejected:'超出允许范围',revision_conflict:'正式版本已变化',applied:'已应用',discarded:'已放弃',already_compliant:'已满足要求'};
statusNames.cancelled='已停止';
statusNames.answer='回复';
function renderDraft(draft,session,context,interactive=true){
  const active=interactive&&session.active_drafts?.[draft.chart_id]===draft.id;
  const open=interactive&&session.status!=='closed';
  const ready=open&&(draft.can_apply??(!!draft.image_url&&!!draft.code&&!['applied','discarded','rendering'].includes(draft.status)));
  const continuable=open&&(draft.can_continue??(!!draft.image_url&&!!draft.code))&&!['applied','discarded','rendering'].includes(draft.status);
  const overrides=warningIds(draft),layoutOverride=false;
  const files=typeof draft.code==='string'?{'候选代码.py':draft.code}:draft.code||{};
  const name=esc(draft.display_name||chartName(context.project,draft.chart));
  const image=draft.image_url,previous=draft.baseline_image_url;
  const preview=image?`<div class="draftPreview"><div class="draftPreviewLabel">修改后版本 · 点击图片查看大图</div><a class="draftImageLink" href="${esc(image)}" target="_blank" rel="noopener" title="打开修改后的完整图片"><img class="draftImage" loading="lazy" src="${esc(image)}" alt="${name} 修改后预览"><span class="draftImageMissing" hidden>本轮未生成可用图片，请查看下方原因。</span></a>${previous?`<details class="draftPrevious"><summary>查看上一版的图</summary><a class="draftImageLink" href="${esc(previous)}" target="_blank" rel="noopener" title="打开上一版完整图片"><img class="draftImage" loading="lazy" src="${esc(previous)}" alt="${name} 修改前预览"><span class="draftImageMissing" hidden>上一版图片暂时无法读取。</span></a></details>`:''}</div>`:'';
  const chooseReason=interactive?'此版本缺少可用图片或代码':'请先打开此会话';
  const applyReason=interactive?'此版本缺少可用图片或代码':'请先打开此会话';
  const actions=open&&image&&!['applied','discarded'].includes(draft.status)?`<div class="draftActions"><button data-draft-action="activate" data-draft-id="${esc(draft.id)}" data-blocked="${!continuable}" ${continuable?'':`disabled title="${chooseReason}"`}>选此版本继续更改</button><button class="primary" data-draft-action="apply" data-draft-id="${esc(draft.id)}" data-blocked="${!ready}" ${ready?'':`disabled title="${applyReason}"`}>应用此版</button><button data-draft-action="discard" data-draft-id="${esc(draft.id)}" data-blocked="${!open}" ${open?'':'disabled title="请先打开此会话"'}>放弃</button>${draft.status==='validation_failed'?`<button data-draft-action="recheck" data-draft-id="${esc(draft.id)}" data-blocked="false">重新检查此版</button>`:''}${layoutOverride?`<button class="layoutOverride" data-layout-override="${esc(draft.id)}">仍按要求执行</button>`:''}</div>${!ready&&open?`<p class="draftActionHint">${continuable?'此版可继续修改；应用所需的图片或代码尚不可用。':'此版尚未生成可用图片或代码；请查看下方原因。'}</p>`:''}${layoutOverride?'<p class="hint">请先展开“请留意”查看布局问题；点击表示接受所列冲突，其他要求继续保留。</p>':''}`:'';
  return `<article class="draftCard ${active?'activeDraft':''}" data-draft="${esc(draft.id)}"><div class="draftHeader"><strong>${name}</strong><span class="draftStatus">${esc(statusNames[draft.status]||draft.status)}${active?' · 继续修改的起点':''}</span></div>${preview}${actions}<p class="draftSummary">${esc(readable(draft.summary))}</p>${warningsHTML(draft)}${draft.reason?`<p class="draftReason">${esc(readable(draft.reason))}</p>`:''}${renderDraftReview(draft)}${Object.keys(files).length?`<details class="draftCode"><summary>查看候选代码（${Object.keys(files).length} 个文件）</summary>${Object.entries(files).map(([path,code])=>`<strong>${esc(path)}</strong><pre>${esc(typeof code==='object'?code.content:code)}</pre>`).join('')}</details>`:''}</article>`;
}
function renderChat(){
  const context=chatContext(),activeSession=state.chatSessions.get(context.key),list=state.chatSessionLists.get(context.key)||[];
  state.chatDisplayProject=context.project;
  $('chatSessionPicker').innerHTML=list.length?list.map((s,i)=>`<option value="${esc(s.id)}" ${s.id===activeSession?.id?'selected':''}>${esc(s.title||(s.created_at?new Date(s.created_at).toLocaleString('zh-CN'):'会话 '+(list.length-i)))}${s.saved_at?' · 已保存':''} · ${(s.turns||[]).length} 轮</option>`).join(''):'<option value="">发送后创建会话</option>';
  const byId=new Map((state.projectChatHistory.get(context.project)||[]).map(session=>[session.id,session]));
  if(activeSession)byId.set(activeSession.id,activeSession);
  const timeline=[];
  for(const session of byId.values())for(const [turnIndex,turn] of (session.turns||[]).entries())timeline.push({session,turn,turnIndex,time:typeof turn.created_at==='number'?turn.created_at*1000:Date.parse(turn.created_at||session.created_at)||0});
  timeline.sort((a,b)=>a.time-b.time||a.turnIndex-b.turnIndex);
  let html=activeSession?.status==='closed'?'<div class="bubble assistant">当前目标会话已结束。继续发送会从当前正式图新建会话。</div>':activeSession?.status==='interrupted'?'<div class="bubble error">当前目标会话的上一轮生成中断，先前成功候选仍保留。</div>':'';
  for(const {session,turn,turnIndex,time} of timeline){
    const interactive=!!context.key&&session.id===activeSession?.id;
    const names=(session.charts||[]).map(item=>chartName(context.project,typeof item==='string'?item:item.chart)).join('、');
    const available=(session.charts||[]).every(item=>projectInfo(context.project)?.charts.includes(typeof item==='string'?item:item.chart));
    html+=`<div class="chatTurnMeta" data-session-id="${esc(session.id)}"><span>${esc(names||'项目改图')} · ${esc(time?new Date(time).toLocaleString('zh-CN'):'历史记录')}</span>${!interactive&&available?`<button type="button" data-open-chat-session="${esc(session.id)}">打开此会话</button>`:''}</div>`;
    html+=`<div class="bubble user">${esc(turn.user_message||turn.prompt||'生成标准化候选')}</div>`;
    const rendered=new Set();
    for(const result of turn.results||[]){
      const draft=(session.drafts||[]).find(item=>item.id===result.draft_id);
      if(draft){if(result.status==='already_compliant'&&result.reason)html+=`<div class="bubble assistant">${esc(readable(result.reason))}</div>`;html+=renderDraft(draft,session,context,interactive);rendered.add(draft.id);}
      else if(result.status==='answer')html+=`<div class="bubble assistant result-answer"><strong>回复</strong>${esc(result.message||'')}</div>`;
      else html+=`<div class="bubble assistant result-${esc(result.status)}"><strong>${esc(result.display_name||chartName(context.project,result.chart))} · ${esc(statusNames[result.status]||result.status)}</strong>${esc(readable(result.summary||result.reason||result.question||result.message))}${result.question&&readable(result.question)!==readable(result.summary||result.reason||result.question||result.message)?'<p>'+esc(readable(result.question))+'</p>':''}${warningsHTML(result)}</div>`;
    }
    for(const draft of (session.drafts||[]).filter(item=>item.turn_id===turn.id&&!rendered.has(item.id)))html+=renderDraft(draft,session,context,interactive);
    if(interactive&&turn.operation==='chat_edit'&&turn.results?.length&&turn.results.every(item=>item.status==='revision_conflict'))html+=`<button type="button" class="retryStale" data-retry-turn="${turnIndex}">从最新正式版重试这轮修改</button>`;
  }
  if(!timeline.length)html+='<div class="bubble assistant">当前项目还没有 Chat 改图记录。选中要修改的图并输入要求；候选图会先显示在这里，应用后才会更新中央图集。</div>';
  if(state.projectChatErrors.has(context.project))html+=`<div class="bubble error">读取项目 Chat 历史失败：${esc(state.projectChatErrors.get(context.project))}</div>`;
  if(state.chatErrors.has(context.key))html+=`<div class="bubble error">${esc(state.chatErrors.get(context.key))}</div>`;
  if(state.chatPending.has(context.key)&&activeSession?.turns?.at(-1)?.user_message!==state.chatPending.get(context.key))html+=`<div class="bubble user">${esc(state.chatPending.get(context.key))}</div>`;
  if(state.chatBusy.has(context.key)||activeSession?.status==='running'){const phase={preparing:'准备图表资料',model_request:'等待模型生成代码',rendering:'渲染并检查候选图',repairing:'修正候选图'}[activeSession?.progress?.stage]||'正在提交请求';const started=chatStartedAt.get(context.key)||activeSession?.progress?.started_at*1000;const elapsed=started?` · 已等待 ${Math.max(0,Math.floor((Date.now()-started)/1000))} 秒`:'';html+=`<div class="bubble assistant chatProgress">${esc(phase)}…${esc(elapsed)}<br>中央图集继续保留已应用版本。</div>`;}
  $('messages').innerHTML=html;
  $('messages').querySelectorAll('.draftImage').forEach(img=>img.onerror=()=>{img.hidden=true;img.nextElementSibling.hidden=false;img.parentElement.removeAttribute('href');});
  $('messages').querySelectorAll('[data-draft-action]').forEach(button=>button.onclick=()=>draftAction(button.dataset.draftAction,button.dataset.draftId));
  $('messages').querySelectorAll('[data-layout-override]').forEach(button=>button.onclick=()=>acceptLayoutException(button.dataset.layoutOverride));
  $('messages').querySelectorAll('[data-retry-turn]').forEach(button=>button.onclick=()=>retryStaleTurn(Number(button.dataset.retryTurn)));
  $('messages').querySelectorAll('[data-open-chat-session]').forEach(button=>button.onclick=()=>openProjectChatSession(button.dataset.openChatSession));
  updateChatControls();$('messages').scrollTop=$('messages').scrollHeight;
}
async function openProjectChatSession(id){
  const project=state.project,summary=(state.projectChatHistory.get(project)||[]).find(session=>session.id===id);
  if(!summary)return;
  state.selectedCharts=new Set((summary.charts||[]).map(item=>typeof item==='string'?item:item.chart));
  updateSelection();
  const context=chatContext();
  try{await loadChatSessions(context,id);const session=await api(sessionEndpoint(context,id));if(state.project!==project||state.chatKey!==context.key)return;storeSession(context,session);state.chatReferences.set(context.key,new Set(referenceRoutes(session)));renderChatReferences();renderChat();const heading=$('messages').querySelector(`[data-session-id="${CSS.escape(id)}"]`);heading?.scrollIntoView({block:'nearest'});}catch(error){state.chatErrors.set(context.key,error.message);if(state.project===project&&state.chatKey===context.key)renderChat();}
}
async function retryStaleTurn(index){
  const context=chatContext(),session=state.chatSessions.get(context.key),turn=session?.turns?.[index];
  if(!turn||turn.operation!=='chat_edit'||!turn.results?.length||!turn.results.every(item=>item.status==='revision_conflict')||state.chatBusy.has(context.key))return;
  try{
    const fresh=await postJSON(sessionEndpoint(context),{charts:context.charts,reference_charts:selectedReferences(context.key)});
    storeSession(context,fresh);
    if(context.key===state.chatKey)renderChat();
    await generateChat({user_message:turn.user_message},'turns',context);
  }catch(error){state.chatErrors.set(context.key,error.message);if(context.key===state.chatKey)renderChat();}
}
async function pollChatProgress(){
  const context=chatContext(),session=state.chatSessions.get(context.key);
  // A new POST is still pending while the cached session remains "open".
  if(!session||(!state.chatBusy.has(context.key)&&session.status!=='running')||state.chatPolling.has(context.key))return;
  state.chatPolling.add(context.key);
  try{
    const updated=await api(sessionEndpoint(context,session.id));
    // A completed POST or a different session must win over a late GET.
    if(state.chatSessions.get(context.key)===session){
      storeSession(context,updated);
      if(state.chatKey===context.key)renderChat();
    }
  }catch(error){
    state.chatErrors.set(context.key,'会话暂时无法同步：'+error.message);
    if(state.chatKey===context.key)renderChat();
  }finally{state.chatPolling.delete(context.key);}
}

$('stopChat').onclick=async()=>{
  const context=chatContext(),session=state.chatSessions.get(context.key);
  if(!session)return;
  $('stopChat').disabled=true;$('stopChat').textContent='正在停止…';
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
  try{
    const result=await api(sessionEndpoint(context,session.id,'stop'),{method:'POST',
      headers:{'Content-Type':'application/json'},body:'{}',signal:controller.signal});
    alertStatus(result.message);
    void pollChatProgress();
  }catch(error){state.chatErrors.set(context.key,error.name==='AbortError'?'停止请求未能在 8 秒内确认，请重试；不要重复提交改图。':error.message);renderChat();}
  finally{clearTimeout(timer);$('stopChat').disabled=false;$('stopChat').textContent='停止本轮';}
};
const updateChatControlsBeforeStop=updateChatControls;
updateChatControls=function(){
  updateChatControlsBeforeStop();
  const context=chatContext(),session=state.chatSessions.get(context.key);
  $('stopChat').hidden=!(session&&(state.chatBusy.has(context.key)||session.status==='running'));
  const disabled=!session||state.chatBusy.has(context.key)||session.status==='running'||state.chatLoads.has(context.key);
  $('saveChatSession').disabled=disabled;$('deleteChatSession').disabled=disabled;$('chatSessionTitle').disabled=disabled;
  if($('chatSessionTitle').dataset.sessionId!==session?.id){$('chatSessionTitle').dataset.sessionId=session?.id||'';$('chatSessionTitle').value=session?.title||'';}
};

async function manageChatSession(action){
  const context=chatContext(),session=state.chatSessions.get(context.key);
  if(!session||state.chatBusy.has(context.key)||session.status==='running')return;
  if(action==='delete'&&!confirm('删除当前会话及其未应用候选？已应用的图、代码、数据不变。记录移入本机回收目录。'))return;
  state.chatBusy.add(context.key);updateChatControls();
  try{
    const result=await postJSON(sessionEndpoint(context,session.id,action),action==='save'?{title:$('chatSessionTitle').value}:{confirm_session_id:session.id});
    if(action==='save'){storeSession(context,result);alertStatus('会话已保存，可从会话列表重新打开');}
    else{
      for(const [key,value] of state.chatSessions)if(value.id===session.id)state.chatSessions.delete(key);
      for(const [key,list] of state.chatSessionLists)state.chatSessionLists.set(key,list.filter(s=>s.id!==session.id));
      state.projectChatHistory.set(context.project,(state.projectChatHistory.get(context.project)||[]).filter(s=>s.id!==session.id));
      state.chatErrors.delete(context.key);
      await refreshProjectChats(context.project);
      alertStatus('会话已移入本机回收目录；正式图表未改变');
    }
  }catch(error){state.chatErrors.set(context.key,error.message);}
  finally{state.chatBusy.delete(context.key);if(state.chatKey===context.key)renderChat();}
}
$('saveChatSession').onclick=()=>manageChatSession('save');
$('deleteChatSession').onclick=()=>manageChatSession('delete');

async function generateChat(body,action='turns',context=chatContext()){
  if(!context.key||state.chatBusy.has(context.key)||state.chatSessions.get(context.key)?.status==='running')return false;
  state.chatBusy.add(context.key);state.chatErrors.delete(context.key);
  chatStartedAt.set(context.key,Date.now());
  state.chatPending.set(context.key,body.user_message||'使用 '+body.skill_id+' 生成标准化候选');
  if(context.project===state.project)renderChat();
  let session;
  try{
    session=await ensureChatSession(context);
    if(action==='turns')body={...body,reference_charts:selectedReferences(context.key),target_panels:typeof panelTargetFor==='function'?panelTargetFor(context):{}};
    let result=await postJSON(sessionEndpoint(context,session.id,action),body);
    storeSession(context,result);
    const results=result.turns?.at(-1)?.results||[];
    if(results.length&&results.every(item=>item.status==='revision_conflict')&&!session.drafts?.length){
      // No candidate exists to preserve; start from the current applied files once.
      session=await postJSON(sessionEndpoint(context),{charts:context.charts,reference_charts:selectedReferences(context.key)});
      storeSession(context,session);
      result=await postJSON(sessionEndpoint(context,session.id,action),body);
      storeSession(context,result);
    }
    if(context.project===state.project)renderChat();
    if(state.chatKey===context.key)alertStatus('候选处理完成，请在 Chat 中审阅');
    return true;
  }catch(error){
    state.chatErrors.set(context.key,error.message);
    if(session){try{storeSession(context,await api(sessionEndpoint(context,session.id)));}catch(_){/* Keep the last successfully loaded session. */}}
    if(context.project===state.project)renderChat();
    return false;
  }finally{
    state.chatBusy.delete(context.key);state.chatPending.delete(context.key);
    chatStartedAt.delete(context.key);
    if(context.project===state.project)renderChat();
  }
}
async function draftAction(action,id){const context=chatContext(),session=state.chatSessions.get(context.key);if(!session||state.chatBusy.has(context.key)||session.status==='running')return;const draft=session.drafts.find(d=>d.id===id);if(!draft)return;state.chatBusy.add(context.key);state.chatErrors.delete(context.key);updateChatControls();try{const result=await postJSON(sessionEndpoint(context,session.id,`drafts/${encodeURIComponent(id)}/${action}`),{});storeSession(context,result);if(action==='apply'){const cacheKey=context.project+'/'+draft.chart,old=state.previews.get(cacheKey);if(old)URL.revokeObjectURL(old);state.previews.delete(cacheKey);await updateCard(context.project,draft.chart);if(state.project===context.project&&state.chart===draft.chart){const detail=await api(chartEndpoint(context.project,draft.chart,'detail'));if(state.project===context.project&&state.chart===draft.chart){state.detail=detail;$('editor').value=detail.code;drawHistory();drawData();if(typeof renderPanelControls==='function')renderPanelControls();}}}if(context.project===state.project)renderChat();if(state.chatKey===context.key)alertStatus(action==='apply'?'已应用候选，正式图片与代码已更新':action==='activate'?'下一轮将从所选候选继续':action==='recheck'?'已使用当前规则重新检查，未调用模型':'候选已放弃');}catch(error){state.chatErrors.set(context.key,error.message);}finally{state.chatBusy.delete(context.key);if(context.project===state.project)renderChat();}}
async function acceptLayoutException(id){const session=state.chatSessions.get(state.chatKey),draft=session?.drafts.find(d=>d.id===id);if(!draft)return;const ids=warningIds(draft);if(!ids.length)return;const quote=`对于“${draft.display_name||draft.chart}”，我已了解上方列出的布局问题，仍按上一轮要求执行，并接受这些重叠或裁切。其他图保持不变。`;await generateChat({user_message:quote,layout_exception:{chart_id:draft.chart_id,warning_ids:ids,authorization_quote:quote}});}
$('chatForm').onsubmit=async e=>{e.preventDefault();const message=$('prompt').value.trim(),context=chatContext();if(!message||!context.key||state.chatBusy.has(context.key)||state.chatSessions.get(context.key)?.status==='running')return;$('prompt').value='';const ok=await generateChat({user_message:message},'turns',context);if(!ok&&state.chatKey===context.key&&!$('prompt').value)$('prompt').value=message;};
$('prompt').onkeydown=e=>{if(e.key!=='Enter'||e.shiftKey||e.isComposing||e.keyCode===229)return;e.preventDefault();if(!e.repeat)$('chatForm').requestSubmit();};
$('newChatSession').onclick=async()=>{const context=chatContext();if(!context.key||state.chatBusy.has(context.key)||state.chatSessions.get(context.key)?.status==='running')return;state.chatBusy.add(context.key);updateChatControls();try{const session=await postJSON(sessionEndpoint(context),{charts:context.charts,reference_charts:selectedReferences()});storeSession(context,session);state.chatErrors.delete(context.key);}catch(error){state.chatErrors.set(context.key,error.message);}finally{state.chatBusy.delete(context.key);if(state.chatKey===context.key)renderChat();}};
$('chatSessionPicker').onchange=async e=>{const context=chatContext(),id=e.target.value;if(!id)return;state.chatBusy.add(context.key);updateChatControls();try{const session=await api(sessionEndpoint(context,id));storeSession(context,session);state.chatReferences.set(context.key,new Set(referenceRoutes(session)));if(state.chatKey===context.key)renderChatReferences();}catch(error){state.chatErrors.set(context.key,error.message);}finally{state.chatBusy.delete(context.key);if(state.chatKey===context.key)renderChat();}};
function showProject(project,clearChart=false){const p=projectInfo(project);if(!p)return;const changed=state.project!==project;if(changed||clearChart){state.project=project;state.chart=null;state.detail=null;if(changed)state.selectedCharts.clear();if(changed)drawGallery();else document.querySelectorAll('.chartCard').forEach(card=>card.classList.remove('active'));}state.openProjects.add(project);$('breadcrumb').textContent=`${p.name.toUpperCase()} / CHARTS`;$('chartTitle').textContent=p.name;$('description').textContent=p.description||`项目中有 ${p.charts.length} 张图。可勾选多张图进行统一修改。`;$('galleryTitle').textContent=p.name;$('galleryCount').textContent=`${p.charts.length} 张图`;$('refresh').disabled=!state.chart;$('svg').hidden=!state.chart;$('pdf').hidden=!state.chart;drawTree();updateSelection();tab('figure');}
function drawGallery(){state.galleryVersion++;galleryQueue.length=0;document.querySelectorAll('.chartCard').forEach(card=>galleryObserver.unobserve(card));const p=projectInfo(state.project);$('gallery').innerHTML=p?.charts.length?orderedCharts(p).map(chart=>`<article class="chartCard" data-chart="${esc(chart)}"><div class="chartCardTop"><label class="chartSelect"><input class="chartCheck" type="checkbox" aria-label="选择 ${esc(chart)}"> 选择</label><span class="chartName" title="${esc(chart)}">${esc(chartName(state.project,chart))}</span></div><button type="button" class="chartOpen" aria-label="打开 ${esc(chart)}"><div class="chartImage"><span class="chartLoading">等待图片…</span></div></button><div class="chartCardActions"><button type="button" class="cardDetail">查看代码与数据 ↗</button><button type="button" class="cardData">直接查看 CSV</button><button type="button" class="cardHistory">修改历史</button><button type="button" class="cardFinalize" title="保留当前代码与图片，清理这张图在应用中的旧版本文件">完成并清理</button></div></article>`).join(''):'<div class="galleryEmpty">这个项目还没有图表。展开左侧项目，可新建绘图或添加 CSV。</div>';
  document.querySelectorAll('.chartCard').forEach(card=>{const chart=card.dataset.chart;card.querySelector('.chartCheck').onchange=e=>{e.stopPropagation();e.target.checked?state.selectedCharts.add(chart):state.selectedCharts.delete(chart);updateSelection();};card.querySelector('.chartOpen').onclick=()=>select(state.project,chart);card.querySelector('.cardDetail').onclick=()=>openChartDetails(state.project,chart,'code');card.querySelector('.cardData').onclick=()=>openChartDetails(state.project,chart,'data');card.querySelector('.cardHistory').onclick=()=>openHistory(state.project,chart);card.querySelector('.cardFinalize').onclick=()=>finalizeChart(state.project,chart);const cached=state.previews.get(state.project+'/'+chart);if(cached){card.querySelector('.chartImage').innerHTML=`<img src="${cached}" alt="${esc(chart)} 图像预览">`;fitChartCanvas(card,card.querySelector('img'));}else galleryObserver.observe(card);});updateSelection();}
async function openChartDetails(project,chart,view){await select(project,chart,view);}
const galleryQueue=[];let galleryActive=0;
const galleryRequests=new Set();
async function fetchGalleryImage(url){
  const controller=new AbortController();galleryRequests.add(controller);
  const timer=setTimeout(()=>controller.abort(),165000);
  try{
    const response=await fetch(url,{signal:controller.signal});
    if(!response.ok){const body=await response.json();throw new Error(body.error||`HTTP ${response.status}`);}
    return await response.blob();
  }finally{clearTimeout(timer);galleryRequests.delete(controller);}
}
const drawGalleryBeforeCancellation=drawGallery;
drawGallery=function(){
  for(const controller of galleryRequests)controller.abort();
  drawGalleryBeforeCancellation();
};
function runGalleryQueue(){while(galleryActive<2&&galleryQueue.length){const item=galleryQueue.shift();galleryActive++;loadCard(item).finally(()=>{galleryActive--;runGalleryQueue();});}}
const galleryObserver=new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting)continue;galleryObserver.unobserve(entry.target);galleryQueue.push({card:entry.target,project:state.project,chart:entry.target.dataset.chart,version:state.galleryVersion});}runGalleryQueue();},{root:null,rootMargin:'350px'});
async function loadCard({card,project,chart,version,force=false,requested=false}){
  if(version!==state.galleryVersion)return;
  const requestId=String(Number(card.dataset.previewRequest||0)+1);card.dataset.previewRequest=requestId;
  const slot=card.querySelector('.chartImage');
  const importWarning=projectInfo(project)?.chart_warnings?.[chart];
  const diagnostic=(projectInfo(project)?.chart_diagnostic_previews||[]).includes(chart);
  if(diagnostic&&!card.querySelector('.chartImportWarning')){const note=document.createElement('p');note.className='chartImportWarning';note.textContent='布局警告预览：'+importWarning;card.append(note);}
  if(importWarning&&!diagnostic&&!force&&!requested){slot.innerHTML='<span class="chartError">导入成功，此图试绘未通过，尚无可用预览。可查看代码和数据，修复后点击“重新渲染当前图”。</span>';const note=document.createElement('p');note.className='chartImportWarning';note.textContent='导入时试绘警告：'+importWarning.trim().split('\n').pop();note.title=importWarning;slot.append(note);return;}
  if(!force&&!requested&&projectInfo(project)?.data_source_type==='plot_bundle'&&(!projectInfo(project)?.chart_metadata?.[chart]||projectInfo(project).chart_metadata[chart].status==='pending')){slot.innerHTML='<span class="chartLoading">点击图卡按需生成 Bundle 图片</span>';return;}
  slot.innerHTML='<span class="chartLoading">正在读取图片；缓存失效时需重新绘制…</span>';
  try{
    const blob=await fetchGalleryImage(chartEndpoint(project,chart,'preview')+'?v='+Date.now()+(force?'&force=1':''));
    const url=URL.createObjectURL(blob);
    if(version!==state.galleryVersion||card.dataset.previewRequest!==requestId){URL.revokeObjectURL(url);return;}
    const key=project+'/'+chart,prior=state.previews.get(key);if(prior)URL.revokeObjectURL(prior);state.previews.set(key,url);
    slot.innerHTML='';const img=document.createElement('img');img.src=url;img.alt=chart+(diagnostic?' 布局警告预览':' 图像预览');img.loading='lazy';fitChartCanvas(card,img);slot.append(img);
  }catch(e){
    if(version!==state.galleryVersion||card.dataset.previewRequest!==requestId)return;
    slot.innerHTML='';const message=document.createElement('span');message.className='chartError';
    message.textContent=e.name==='AbortError'?'图片读取超时或已取消，请重试。':'渲染失败：'+e.message;
    const retry=document.createElement('button');retry.type='button';retry.textContent='重新读取图片';
    retry.onclick=event=>{event.stopPropagation();loadCard({card,project,chart,version,requested:true});};slot.append(message,retry);
  }
}
async function preview(force=false){if(!state.chart)return;const card=[...document.querySelectorAll('.chartCard')].find(x=>x.dataset.chart===state.chart);if(card)await loadCard({card,project:state.project,chart:state.chart,version:state.galleryVersion,force,requested:true});await refreshChartNames();alertStatus('已渲染 · '+new Date().toLocaleTimeString('zh-CN'));}
async function select(project,chart,view='figure'){const request=++state.detailRequest;showProject(project);state.chart=chart;state.detail=null;drawTree();const p=projectInfo(project);$('breadcrumb').textContent=`${p.name.toUpperCase()} / CHARTS / ${chart.toUpperCase()}`;$('chartTitle').textContent=chartName(project,chart);$('description').textContent=p.description||`项目共 ${p.charts.length} 张图`;$('filename').textContent=chart+'.py';$('refresh').disabled=false;$('svg').hidden=false;$('pdf').hidden=false;$('svg').href=endpoint('svg');$('pdf').href=endpoint('pdf');document.querySelectorAll('.chartCard').forEach(card=>card.classList.toggle('active',card.dataset.chart===chart));updateSelection();if(view==='code')$('editor').value='正在加载代码…';if(view==='data')$('dataInfo').textContent='正在加载 CSV 数据…';tab(view);if(view!=='figure')document.querySelector('main').scrollTo({top:0,behavior:'smooth'});try{const detail=await api(chartEndpoint(project,chart,'detail'));if(request!==state.detailRequest||state.project!==project||state.chart!==chart)return false;state.detail=detail;$('editor').value=state.detail.code;drawHistory();drawData();if(typeof renderPanelControls==='function'){renderPanelControls();drawPanelSections();}tab(view);if(view==='figure'){const card=[...document.querySelectorAll('.chartCard')].find(x=>x.dataset.chart===chart);card?.scrollIntoView({block:'nearest',behavior:'smooth'});if(p.data_source_type==='plot_bundle'&&card)await loadCard({card,project,chart,version:state.galleryVersion,requested:true});}alertStatus('已选择 '+chartName(project,chart));return true;}catch(e){if(request!==state.detailRequest||state.project!==project||state.chart!==chart)return false;alertStatus(e.message);if(view==='code')$('editor').value=e.message;if(view==='data')$('dataInfo').textContent=e.message;return false;}}
async function post(action,body){return api(endpoint(action),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
async function apply(code,note,baseRevision){const project=state.project,chart=state.chart;try{$('saveCode').disabled=true;const r=await postChart(project,chart,'apply',{code,note,base_revision:baseRevision});await updateCard(project,chart);if(state.project===project&&state.chart===chart){const detail=await api(chartEndpoint(project,chart,'detail'));if(state.project===project&&state.chart===chart){state.detail=detail;$('editor').value=detail.code;drawHistory();drawData();if(typeof renderPanelControls==='function')renderPanelControls();alertStatus(r.message||'已保存代码并更新图片');}}return true;}catch(e){alertStatus('保存或重绘失败：'+e.message);return false;}finally{$('saveCode').disabled=false;}}
async function restore(id){if(!confirm('将此历史版本恢复为新的当前版本？原版本仍保留。'))return;try{await post('restore',{id});await refreshChartNames();await select(state.project,state.chart);await preview();drawHistory();bubble('已恢复历史版本。');}catch(e){bubble(e.message,'error');}}
async function openHistory(project,chart){await select(project,chart);if(!state.detail)return;state.historyChart={project,chart};drawHistory();$('historyDialog').showModal();}
async function refreshProjectChats(project){
  const belongs=key=>{try{return JSON.parse(key)[0]===project;}catch(_){return false;}};
  const active=chatContext(),preferredId=state.chatSessions.get(active.key)?.id;
  await Promise.allSettled([...state.chatLoads].filter(([key])=>belongs(key)).map(([,task])=>task));
  if(state.projectChatLoads.has(project))await Promise.allSettled([state.projectChatLoads.get(project)]);
  for(const cache of [state.chatSessions,state.chatSessionLists,state.chatReferences,state.chatErrors])for(const key of cache.keys())if(belongs(key))cache.delete(key);
  state.projectChatHistory.delete(project);state.projectChatLoaded.delete(project);state.projectChatErrors.delete(project);
  if(state.project===project)await loadProjectChatHistory(project);
  const current=chatContext();if(current.project===project&&current.key){await loadChatSessions(current,current.key===active.key?preferredId:undefined);if(state.chatKey===current.key){renderChatReferences();renderChat();}}
}
async function finalizeChart(project,chart){if(!confirm(`清理 ${chart} 的旧版本文件？当前代码和图片会保留；已有 Git 提交仍可追溯。`))return;try{await postChart(project,chart,'finalize',{});await refreshProjectChats(project);if(state.project===project&&state.chart===chart){const detail=await api(chartEndpoint(project,chart,'detail'));if(state.project===project&&state.chart===chart){state.detail=detail;drawHistory();}}alertStatus(`${chart} 的历史文件已清理，相关改图会话已更新`);}catch(e){bubble(e.message,'error');}}
$('closeHistory').onclick=()=>$('historyDialog').close();
$('finalizeHistory').onclick=async()=>{const target=state.historyChart;if(!target)return;await finalizeChart(target.project,target.chart);};
$('saveCode').onclick=()=>{if(state.chart)apply($('editor').value,'手动编辑绘图代码',state.detail?.revision);};
$('refresh').onclick=async()=>{try{await preview(true);}catch(e){alertStatus(e.message);bubble(e.message,'error');}};
async function postChart(project,chart,action,body){return api(chartEndpoint(project,chart,action),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
async function updateCard(project,chart){await refreshChartNames();if(project!==state.project)return;const card=[...document.querySelectorAll('.chartCard')].find(x=>x.dataset.chart===chart);if(card)await loadCard({card,project,chart,version:state.galleryVersion});}
function forgetProjectPreviews(project){for(const [key,url] of state.previews){if(key.startsWith(project+'/')){URL.revokeObjectURL(url);state.previews.delete(key);}}}
async function batchNormalize(skillId,context=chatContext()) { await generateChat({skill_id:skillId},'normalize',context); }
$('batchNormalize').onclick=chooseSkill;
$('batchEdit').onclick=()=>{if(!state.selectedCharts.size)return;$('prompt').focus();$('prompt').placeholder=`输入对所选 ${state.selectedCharts.size} 张图的修改要求，逐图生成候选预览…`;document.querySelector('.right').scrollIntoView({block:'nearest',behavior:'smooth'});};
$('selectAllCharts').onchange=e=>selectAllCharts(e.target.checked);
document.querySelectorAll('.tab').forEach(e=>e.onclick=()=>tab(e.dataset.tab));
async function reloadSkills(){const r=await api('/api/normalization-skills');state.skills=r.skills;$('skillCount').textContent=`已保存 ${r.skills.length} 个 Skill，可查看、删除或上传`;renderSkillList();}
function renderSkillList(){$('skillList').innerHTML=state.skills.length?state.skills.map(s=>`<div class="skillRow"><strong>${esc(s.name)}</strong><small>${esc(s.id)}</small><button data-view-skill="${esc(s.id)}">查看</button><button data-delete-skill="${esc(s.id)}">删除</button></div>`).join(''):'<p class="hint">还没有 Skill，请上传 SKILL.md。</p>';document.querySelectorAll('[data-view-skill]').forEach(e=>e.onclick=async()=>{try{const s=await api('/api/normalization-skills/'+encodeURIComponent(e.dataset.viewSkill));$('skillText').textContent=s.content+'\n\n--- style-profile.v1.json ---\n'+JSON.stringify(s.profile,null,2);$('skillText').closest('details').open=true;}catch(err){alert(err.message);}});document.querySelectorAll('[data-delete-skill]').forEach(e=>e.onclick=async()=>{if(!confirm(`删除 Skill ${e.dataset.deleteSkill}？已保存的图表不会改变。`))return;try{await api('/api/normalization-skills/'+encodeURIComponent(e.dataset.deleteSkill),{method:'DELETE'});await reloadSkills();}catch(err){alert(err.message);}});}
async function chooseSkill(){const context=chatContext();if(!context.charts.length)return;try{await reloadSkills();$('chooseSkillTarget').textContent=`对所选 ${context.charts.length} 张图生成标准化候选，审阅后逐图应用`;$('chooseSkillList').innerHTML=state.skills.length?state.skills.map(s=>`<button class="skillChoice" data-skill="${esc(s.id)}">${esc(s.name)} <small>${esc(s.id)}</small></button>`).join(''):'<p class="hint">请先在左侧上传一个绘图标准化 Skill。</p>';$('chooseSkillList').querySelectorAll('[data-skill]').forEach(e=>e.onclick=()=>{$('chooseSkillDialog').close();batchNormalize(e.dataset.skill,context);});$('chooseSkillDialog').showModal();}catch(e){alertStatus(e.message);}}
$('showSkill').onclick=async()=>{await reloadSkills();$('skillDialog').showModal();};$('closeSkill').onclick=()=>$('skillDialog').close();$('closeChooseSkill').onclick=()=>$('chooseSkillDialog').close();
$('uploadSkill').onclick=async()=>{const file=$('skillFile').files[0];if(!file){alert('请选择 SKILL.md 文件。');return;}try{const profileFile=$('skillProfileFile').files[0];const profile=profileFile?JSON.parse(await profileFile.text()):{};await api('/api/normalization-skills',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:$('skillId').value.trim(),name:$('skillName').value.trim(),content:await file.text(),profile})});$('skillName').value='';$('skillId').value='';$('skillFile').value='';$('skillProfileFile').value='';await reloadSkills();alertStatus('绘图标准化 Skill 已上传');}catch(e){alert(e.message);}};
async function reloadProjects(){const r=await api('/api/projects');state.projects=r.projects;if(state.project){const current=state.project;state.project=null;showProject(current);}else drawTree();return r;}
function closeCreateMenu(){$('createMenu').classList.add('hide');$('newProject').setAttribute('aria-expanded','false');}
$('newProject').onclick=e=>{e.stopPropagation();const open=$('createMenu').classList.toggle('hide')===false;$('newProject').setAttribute('aria-expanded',String(open));};
document.addEventListener('click',e=>{if(!e.target.closest('.createMenuWrap'))closeCreateMenu();});
$('createProject').onclick=async()=>{closeCreateMenu();const id=prompt('项目 ID（英文字母、数字、下划线或连字符）：');if(!id)return;const name=prompt('项目显示名称：',id)||id;try{await api('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,name})});await reloadProjects();showProject(id);alertStatus('已创建项目 '+id);}catch(e){alert(e.message);}};
async function newChart(project){if(!project){alert('请先创建或选中项目。');return;}const name=prompt('新图名称（英文字母、数字或下划线）：');if(!name)return;try{await api(`/api/projects/${encodeURIComponent(project)}/charts`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});await reloadProjects();await select(project,name);}catch(e){alert(e.message);}}

$('standardizeProject').onclick=()=>{
  closeCreateMenu();
  $('standardizeProjectName').value='';
  $('projectSourcePath').value='';
  $('standardizeDialog').showModal();
};
$('closeStandardize').onclick=()=>$('standardizeDialog').close();
$('startStandardize').onclick=async()=>{
  const projectName=$('standardizeProjectName').value.trim();
  const sourceDir=$('projectSourcePath').value.trim();
  if(!projectName){alert('请填写项目名称。');return;}
  if(!sourceDir){alert('请填写源项目目录。');return;}
  try{
    const result=await api('/api/project-standardizer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_name:projectName,source_dir:sourceDir})});
    $('standardizeDialog').close();
    await reloadProjects();
    if(result.project){
      showProject(result.project);
      alertStatus(`已标准化：${result.project}`);
    }
  }catch(err){alertStatus(err.message); bubble(err.message,'error');}
};

$('uploadPackage').onclick=()=>{
  closeCreateMenu();
  const mode=$('uploadProjectMode');
  mode.innerHTML='<option value="__new__">＋ 新建项目</option>'+state.projects.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}（${esc(p.id)}）</option>`).join('');
  mode.value='__new__';$('newProjectFields').hidden=false;
  $('uploadProjectName').value='';$('uploadProjectId').value='';
  $('codeFolder').value='';$('dataFolder').value='';$('imageFolder').value='';
  $('codeFolderStatus').textContent='尚未选择';$('dataFolderStatus').textContent='尚未选择';$('imageFolderStatus').textContent='尚未选择';
  $('uploadDialog').showModal();
};
$('closeUpload').onclick=()=>$('uploadDialog').close();
$('uploadProjectMode').onchange=e=>{$('newProjectFields').hidden=e.target.value!=='__new__';};
$('codeFolder').onchange=e=>{$('codeFolderStatus').textContent=e.target.files.length?`${e.target.files.length} 个 Python 文件`:'尚未选择';};
$('dataFolder').onchange=e=>{$('dataFolderStatus').textContent=e.target.files.length?`${e.target.files.length} 个数据文件`:'尚未选择';};
$('imageFolder').onchange=e=>{$('imageFolderStatus').textContent=e.target.files.length?`${e.target.files.length} 张原图`:'尚未选择';};
$('startUpload').onclick=async()=>{
  const existing=$('uploadProjectMode').value!=='__new__';
  const chosen=existing?state.projects.find(p=>p.id===$('uploadProjectMode').value):null;
  const name=existing?chosen.name:$('uploadProjectName').value.trim();
  const project_id=existing?chosen.id:$('uploadProjectId').value.trim();
  const codeFiles=[...$('codeFolder').files],dataFiles=[...$('dataFolder').files],imageFiles=[...$('imageFolder').files];
  if(!name||!project_id){alert('请填写项目名称和项目 ID。');return;}
  if(!codeFiles.length||!dataFiles.length){alert('请分别选择代码文件夹和数据文件夹。');return;}
  $('startUpload').disabled=true;alertStatus('Agent 正在归档、拆分并验证…');
  try{
    const code=codeFiles.filter(f=>f.name.endsWith('.py'));
    const data=dataFiles.filter(f=>/\.(csv|tsv|json)$/i.test(f.name));
    const images=imageFiles.filter(f=>/\.(png|jpg|jpeg|svg)$/i.test(f.name));
    if(!code.length||!data.length)throw new Error('所选目录中没有可用的 Python 或数据文件。');
    const totalBytes=[...code,...data,...images].reduce((sum,f)=>sum+f.size,0);
    if(totalBytes>500_000_000)throw new Error('单次上传总大小不能超过 500 MB。');
    alertStatus(`正在上传 ${(totalBytes/1024/1024).toFixed(1)} MB 并拆分…`);
    const form=new FormData();
    form.append('name',name);form.append('project_id',project_id);form.append('existing',String(existing));
    code.forEach(f=>form.append('code_files',f,uploadRelativePath(f)));
    data.forEach(f=>form.append('data_files',f,uploadRelativePath(f)));
    images.forEach(f=>form.append('image_files',f,f.name));
    const r=await api('/api/uploads/import',{method:'POST',body:form});
    $('uploadDialog').close();forgetProjectPreviews(r.project);await reloadProjects();state.openProjects.add(r.project);
    const sync=r.github_synced?'已同步到 GitHub':r.github_error?'GitHub 同步失败：'+r.github_error:'已保存在本地，未推送 GitHub';
    bubble(`项目“${name}”已处理：${r.files} 个数据文件，${r.charts.length} 张图表，${r.images||0} 张上传原图；其余预览会在后台保存。${sync}。`);
    if(r.charts[0])await select(r.project,r.charts[0]);
  }catch(err){bubble(err.message,'error');alertStatus('上传拆分失败');}
  finally{$('startUpload').disabled=false;}
};

let csvImportProject=null;
function importCsv(project){if(!project){alert('请先创建或选中项目。');return;}csvImportProject=project;$('csvFile').click();}
$('csvFile').onchange=async e=>{const f=e.target.files[0],project=csvImportProject;csvImportProject=null;if(!f||!project)return;try{const content=await f.text();await api(`/api/projects/${encodeURIComponent(project)}/data`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:f.name,content})});forgetProjectPreviews(project);const chart=state.project===project?state.chart:null;await reloadProjects();if(chart)await select(project,chart);alertStatus('已导入 '+f.name);}catch(err){alert(err.message);}e.target.value='';};
(async()=>{try{if(window.syncTeamOnOpen)await window.syncTeamOnOpen();const [r]=await Promise.all([api('/api/projects'),reloadSkills()]);state.projects=r.projects;drawTree();alertStatus(`项目目录：${r.root}`);if(r.projects[0]){showProject(r.projects[0].id);if(r.projects[0].charts[0])await select(r.projects[0].id,r.projects[0].charts[0]);}if(!r.llm_enabled)bubble('尚未配置模型 API。点击页面顶部的“API 配置”即可填写；现有图片和代码仍可查看。','configNotice');loadModelConfig().catch(e=>alertStatus('模型配置状态不可用：'+e.message));}catch(e){alertStatus(e.message);}})();

// Load persisted naming metadata while existing previews are being indexed in the background.
let refreshingNames=false;
setInterval(async()=>{if(refreshingNames||!state.projects.some(p=>Object.values(p.chart_metadata||{}).some(m=>m.status==='pending')))return;refreshingNames=true;try{await refreshChartNames();}catch(e){console.warn('Chart names unavailable',e);}finally{refreshingNames=false;}},5000);

// Reconnect to a persisted generation after reloading the page or returning to its targets.
setInterval(pollChatProgress,1500);
