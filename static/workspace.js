/* Local preparation UI. Never receives OAuth tokens or passwords. */
(() => {
  'use strict';
  // Batch progress is bundled here: no separately served script dependency.
  function batchProgress(value, now=Date.now()/1000) {
    const jobs=value.jobs||[], total=jobs.length;
    const count=states=>jobs.filter(j=>states.includes(j.status)).length;
    const returned=count(['pending_local_run','ready','failed','needs_context','unsupported','validation_failed']);
    const ready=count(['ready']);
    const issues=count(['failed','needs_context','unsupported','validation_failed','blocked','interrupted']);
    const current=value.current==null?-1:jobs.findIndex(j=>j.id===value.current);
    const validating=value.phase==='validation'||value.phase==='merge';
    const attempt=value.attempt;
    const attemptDone=attempt?attempt.returned.length:0;
    const done=validating?ready:attempt?attemptDone:returned;
    const progressTotal=validating?total:attempt?attempt.jobs.length:total;
    const active=current>=0?jobs[current]:null;
    const since=active?.started_at||value.stage_updated_at;
    const elapsed=active&&since?Math.max(0,Math.floor(now-since)):null;
    const elapsedText=elapsed===null?'':` · 已等待 ${Math.floor(elapsed/60)} 分 ${elapsed%60} 秒`;
    const context=count(['needs_context','unsupported']);
    const history=attempt?`本轮已返回 ${attemptDone}/${attempt.jobs.length} · 历史结果保留`:'累计分析已返回（含上次结果）';
    const failed=count(['failed','validation_failed','interrupted']);
    const blocked=count(['blocked','needs_context','unsupported']);
    const succeeded=count(['ready','pending_local_run']);
    const terminal=current<0&&value.phase!=='merge';
    const fallback=failed&&blocked?'失败／被阻止：拆分未成功':failed||value.error?'失败：拆分或验证未成功':blocked?'被阻止：需要处理超限或依赖':succeeded===total&&total?'成功：拆分方案已生成，待本机导出／验证':null;
    const outcome=value.outcome;
    const outcomeStatus=outcome?.status||(terminal?(failed&&blocked?'failed_blocked':failed||value.error?'failed':blocked?'blocked':succeeded===total&&total?'success':'pending'):'working');
    const terminalLabel=outcome&&outcome.status!=='working'&&outcome.status!=='pending'?outcome.label:terminal?fallback:null;
    const reasonLines=(outcome?.reasons||jobs.filter(j=>['failed','validation_failed','interrupted','blocked','needs_context','unsupported'].includes(j.status))).map(j=>(j.files||j.target_files||[j.batch||j.id]).join('、')+'：'+(j.reason||'请查看该批次详情'));
    const stage=value.installed?'成功：全部验证通过，可进入改图':outcome&&!['working','pending'].includes(outcome.status)?outcome.label:value.phase==='merge'?'正在汇总并验证最终图表':
      current>=0?(validating?'本机验证':'模型分析 · 等待返回'):terminalLabel||
      (validating?'本机验证':
      issues?'需要处理依赖或失败批次':returned===total&&total?'待本地导出和验证':'等待确认并开始');
    return {total,progressTotal,done,stage,current,issues,ready,outcomeStatus,
      label:validating?'验证通过批次':'分析已返回批次',
      text:`${stage}${current>=0?' · 批次 '+(current+1)+' / '+total+elapsedText:''}\n${history}${attempt?'':' '+returned+'/'+total}\n成功 ${succeeded} 批 · 失败 ${failed} 批 · 被阻止 ${blocked} 批\n验证通过 ${ready}/${total} · 需处理 ${issues} 批${context?'\n其中 '+context+' 批缺少依赖或不支持，须修正依赖范围后重新确认；重复提交相同源码无法解决。':''}${current>=0&&!attempt?'\n当前服务未记录本轮进度，累计返回数不代表本轮已完成。':''}${terminal&&reasonLines.length?'\n原因：\n'+reasonLines.join('\n'):''}${value.error?'\n汇总错误：'+value.error:''}\n全部验证并汇总通过后，工程才可改图。`};
  }
  // End batch progress calculation.
  const post = (path, body={}) => api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const message = (id, text, error=false) => {$(id).textContent=text; $(id).className=error?'error':'';};
  const originalShow = showModelConfig;
  const originalSelect = select;
  select = async function(...args) {
    const result = await originalSelect(...args);
    if(result !== false) {
      const formats=(projectInfo(state.project)||{}).render_formats||['png','svg','pdf'];
      $('svg').hidden=!formats.includes('svg');$('pdf').hidden=!formats.includes('pdf');
    }
    return result;
  };
  let savedConfig = {}, authStatus = {}, loginTimer;
  const siliconflowUrl = 'https://api.siliconflow.cn/v1/chat/completions';
  function syncApiDestination() {
    const url = $('modelApiUrl').value.trim();
    const local = state.modelPreset || {api_url:'http://10.254.1.138:8080/api/v1/chat/completions',model:'glm-5.3'};
    $('apiEndpointPreset').value = url === local.api_url ? 'local' : url === siliconflowUrl ? 'siliconflow' : 'custom';
    const previous = savedConfig.provider === 'chatgpt' ? savedConfig.api_profile || {} : savedConfig;
    const changed = url !== (previous.api_url || local.api_url);
    $('modelApiKey').placeholder = changed ? '地址已变更，请输入目标服务的 API Key' : '首次配置请输入；留空则保留现有密钥';
    $('testModelConfig').disabled = changed || !savedConfig.key_configured;
    let destination = '请输入完整接口地址';
    try {const target = new URL(url); destination = `请求目标：${target.origin}；保存后生效。${changed ? '请重新输入此服务的 Key。' : ''}`;} catch (_) {}
    $('apiDestinationNotice').textContent = destination;
    updateModelTransportNotice();
  }
  $('modelApiUrl').oninput = syncApiDestination;
  $('apiEndpointPreset').onchange = () => {
    const kind = $('apiEndpointPreset').value;
    if (kind === 'custom') {$('modelApiUrl').focus(); return;}
    const local = state.modelPreset || {api_url:'http://10.254.1.138:8080/api/v1/chat/completions',model:'glm-5.3'};
    const next = kind === 'local' ? local.api_url : siliconflowUrl;
    if ($('modelApiUrl').value.trim() !== next) {$('modelApiKey').value=''; $('modelName').value = kind === 'local' ? local.model : '';}
    $('modelApiUrl').value = next; syncApiDestination();
  };
  const originalPresetClick = $('useCdscPreset').onclick;
  $('useCdscPreset').onclick = event => {if(originalPresetClick) originalPresetClick(event); $('modelApiKey').value=''; syncApiDestination();};
  function providerFields() {
    const oauth = $('modelProvider').value === 'chatgpt';
    $('apiProviderFields').hidden = oauth; $('chatgptSettings').hidden = !oauth;
    for (const id of ['modelApiUrl','modelName','modelMaxOutputTokens']) $(id).required = !oauth;
    $('chatgptModelSelect').required = oauth;
    $('useCdscPreset').hidden = oauth || !state.modelPreset;
    $('clearModelConfig').hidden = oauth;
    $('modelApiHelp').hidden = oauth;
    $('testModelConfig').disabled = oauth ? !(savedConfig.provider==='chatgpt' && authStatus.sharing) : !savedConfig.key_configured;
    if (!oauth) syncApiDestination();
  }
  showModelConfig = function(config) {
    originalShow(config); savedConfig=config;
    $('modelProvider').value=config.provider||'api';
    $('chatgptCodeConsent').checked=!!config.allow_code_upload;
    if(config.provider==='chatgpt') {
      $('chatgptModelSelect').replaceChildren(new Option(config.model,config.model));
      $('modelConfigBadge').textContent=config.key_configured?'ChatGPT 已连接':'ChatGPT 未连接';
      message('modelConfigState','ChatGPT 配置已保存。登录状态与代码发送权限相互独立。');
    }
    providerFields();
    if(config.provider==='chatgpt') refreshAuth().catch(e=>message('chatgptStatus',e.message,true));
  };
  async function refreshAuth() {
    authStatus = await api('/api/chatgpt/status');
    const a=authStatus;
    message('chatgptStatus', [a.connected ? `已连接：${a.account_label}；${a.sharing?'订阅授权已获得':'未获得订阅共享授权'}` : '尚未连接 ChatGPT',
      a.connected ? (a.storage==='keyring'?'凭据已保存在系统密钥库。':'系统密钥库不可用：仅当前后台会话有效，重启须重新登录。') : '', a.message||''].filter(Boolean).join('\n'));
    $('chatgptConnect').disabled=!!a.pending;
    $('chatgptSwitch').disabled=!!a.pending;
    $('chatgptDisconnect').disabled=!a.connected&&!a.pending;
    $('chatgptLoadModels').disabled=!a.sharing;
    if(!a.pending) {$('chatgptLoginLink').hidden=true; clearInterval(loginTimer); loginTimer=null;}
    providerFields();
  }
  $('modelProvider').onchange=()=>{
    providerFields();
    if($('modelProvider').value==='chatgpt') refreshAuth().catch(e=>message('chatgptStatus',e.message,true));
    else if(savedConfig.provider==='chatgpt') {
      const previous=savedConfig.api_profile||{};
      $('modelApiUrl').value=previous.api_url||'';$('modelName').value=previous.model||'';
      $('modelMaxOutputTokens').value=previous.max_output_tokens||16384;
      $('modelVision').checked=!!previous.vision_enabled;updateModelTransportNotice();
      message('modelConfigState','已恢复之前的 API 地址；密钥不会回显。请确认设置后保存。');
      syncApiDestination();
    }
  };
  async function connect(newAccount) {
    if(newAccount && !confirm('连接其他账户会替换本机当前连接。旧账户仍可在 ChatGPT 设置中撤销 Plot Forge 授权。继续？')) return;
    const popup=window.open('about:blank','_blank');
    if(popup) popup.opener=null;
    try {
      const result=await post('/api/chatgpt/connect',{new_account:newAccount});
      const url=new URL(result.url);
      if(url.origin!=='https://auth.openai.com') throw new Error('拒绝打开非官方登录网址');
      $('chatgptLoginLink').href=url.href; $('chatgptLoginLink').hidden=false;
      if(popup) popup.location.replace(url.href);
      await refreshAuth();
      clearInterval(loginTimer); loginTimer=setInterval(()=>refreshAuth().catch(e=>message('chatgptStatus',e.message,true)),2000);
    } catch(e) {if(popup) popup.close(); message('chatgptStatus',e.message,true);}
  }
  $('chatgptConnect').onclick=()=>connect(false);
  $('chatgptSwitch').onclick=()=>connect(true);
  $('chatgptDisconnect').onclick=async()=>{
    if(!confirm('退出本机 ChatGPT 连接，并尝试撤销远端授权？'))return;
    try {await post('/api/chatgpt/disconnect'); await refreshAuth(); await loadModelConfig();}catch(e){message('chatgptStatus',e.message,true);}
  };
  $('chatgptLoadModels').onclick=async()=>{
    const button=$('chatgptLoadModels');button.disabled=true;
    try {const result=await api('/api/chatgpt/models');const chosen=$('chatgptModelSelect').value;
      $('chatgptModelSelect').replaceChildren(...result.models.map(m=>new Option(m.name,m.id)));
      if(result.models.some(m=>m.id===chosen))$('chatgptModelSelect').value=chosen;
      if(!result.models.length)throw new Error('账户未返回可用模型，请检查订阅共享权限。');
      message('modelConfigState','请选择模型并保存配置。');
    }catch(e){message('chatgptStatus',e.message,true);}finally{button.disabled=false;}
  };
  $('modelConfigForm').onsubmit=async event=>{
    event.preventDefault();$('saveModelConfig').disabled=true;
    try {
      const oauth=$('modelProvider').value==='chatgpt';
      const body=oauth?{provider:'chatgpt',model:$('chatgptModelSelect').value,allow_code_upload:$('chatgptCodeConsent').checked,vision_enabled:$('modelVision').checked}:
        {provider:'api',api_url:$('modelApiUrl').value.trim(),model:$('modelName').value.trim(),max_output_tokens:Number($('modelMaxOutputTokens').value),api_key:$('modelApiKey').value,vision_enabled:$('modelVision').checked};
      showModelConfig(await post('/api/model-config',body));
      message('modelConfigState',oauth?'已保存 ChatGPT 模型与发送权限；可用简短测试语句检查连接。':'API 配置已保存；密钥存储状态请见配置提示。');
      alertStatus('模型配置已保存');
    }catch(e){message('modelConfigState',e.message,true);}finally{$('saveModelConfig').disabled=false;$('modelApiKey').value='';}
  };

  let activeProject='', preparing=false, polling=false, lastStatus='';
  let scopeProject='', analysisPreview=null, scopeRequest=0;
  let batchPreview=null,batchStatus=null,batchPlanning=false,batchRequest=0,lastMode='';
  let currentCanOpen=false;
  let nativeAvailable=false;
  let universalAvailable=false;
  let taskStarted=0,taskSubmitting=false,taskMessage='';
  function showTaskProgress(){
    if(!taskStarted)return;
    $('workspaceTaskProgress').hidden=false;
    $('workspaceTaskProgressText').textContent=taskMessage+' · 已用时 '+Math.max(0,Math.floor(Date.now()/1000-taskStarted))+' 秒'+(lastStatus==='working'?'\n任务正在后台运行。模型请求期间无法估算百分比；返回后继续显示批次或验证结果。':'');
  }
  setInterval(()=>{if(taskSubmitting||lastStatus==='working')showTaskProgress();},1000);
  $('workspaceNativeStart').onclick=async()=>{
    if(!activeProject||!$('workspaceNativeConsent').checked)return;
    $('workspaceNativeStart').disabled=true;
    const project=activeProject;
    try{const value=await post(projectRoute('native-prepare'),{consent:true,environment_mode:$('workspaceEnvironmentMode').value});if(activeProject===project)displayStatus(value);}
    catch(e){message('workspaceMessage',e.message,true);$('workspaceNativeStart').disabled=false;}
  };
  $('workspaceNativeConsent').onchange=()=>{$('workspaceNativeStart').disabled=!$('workspaceNativeConsent').checked||lastStatus==='working';};
  $('workspaceUniversalStart').onclick=async()=>{
    if(!activeProject||!$('workspaceUniversalConsent').checked)return;
    $('workspaceUniversalStart').disabled=true;
    const project=activeProject;
    try{const value=await post(projectRoute('universal-prepare'),{consent:true});if(activeProject===project)displayStatus(value);}
    catch(e){message('workspaceMessage',e.message,true);$('workspaceUniversalStart').disabled=false;}
  };
  $('workspaceUniversalConsent').onchange=()=>{$('workspaceUniversalStart').disabled=!$('workspaceUniversalConsent').checked||lastStatus==='working';};
  $('workspaceAdvanced').ontoggle=()=>{
    if($('workspaceAdvanced').open&&activeProject&&scopeProject!==activeProject)
      loadAnalysisOptions({project:activeProject});
  };
  $('workspaceMode').onchange=async()=>{
    cancelDelete();activeProject='';lastStatus='';currentCanOpen=false;
    $('workspacePreparation').hidden=true;
    $('workspaceNewFields').hidden=$('workspaceMode').value!=='new';
    message('workspaceMessage','');
    try{await refreshRecent();}catch(e){message('workspaceMessage',e.message,true);}
  };
  function batchControls() {
    const busy=lastStatus==='working'||batchPlanning;
    $('workspaceBatchPlan').disabled=!activeProject||busy||lastStatus==='ready';
    const retryable=!batchStatus||batchStatus.jobs.some(j=>['pending','failed','interrupted'].includes(j.status));
    $('workspaceBatchStart').disabled=busy||lastStatus==='ready'||!batchPreview||!batchPreview.jobs.some(j=>j.within_limit)||!retryable||!$('workspaceBatchConsent').checked;
    $('workspaceBatchFinalize').disabled=busy||lastStatus==='ready'||!batchStatus||!$('workspaceBatchValidateConsent').checked||!batchStatus.jobs.some(j=>['pending_local_run','validation_failed','ready'].includes(j.status));
  }
  function showBatch(value) {
    if(!value)return;
    const progress=batchProgress(value);
    $('workspaceBatchProgress').hidden=false;
    $('workspaceBatchProgressText').textContent=progress.text;
    $('workspaceBatchProgressText').className=['failed','blocked','failed_blocked'].includes(progress.outcomeStatus)?'error':progress.outcomeStatus==='success'?'taskSuccess':'';
    $('workspaceBatchProgressBar').max=Math.max(progress.progressTotal,1);
    $('workspaceBatchProgressBar').value=progress.done;
    $('workspaceBatchProgressBar').setAttribute('aria-label',progress.label);
    $('workspaceBatchProgressConnection').textContent='状态更新于 '+new Date().toLocaleTimeString()+'；运行期间每 2 秒查询。单批模型内部百分比不可获取。';
    const labels={pending:'待处理',working:'处理中',interrupted:'上次任务中断',pending_local_run:'待本地导出/验证',ready:'已验证',failed:'生成失败',needs_context:'缺少依赖/需核实',unsupported:'不支持',blocked:'依赖超限',validation_failed:'验证未通过'};
    const blocked=value.jobs.filter(j=>!j.within_limit).length;
    $('workspaceBatchSummary').textContent=`覆盖 ${value.source_files} 个源码文件，共 ${value.source_chars.toLocaleString()} 字符；分为 ${value.jobs.length} 批，其中 ${blocked} 批超限待处理。每批最多 180,000 字符；完全相同的源码正文只传一次并保留所有路径，不做摘要或截断。${value.error?'\n汇总错误：'+value.error:''}`;
    $('workspaceBatchDetails').textContent=value.jobs.map(j=>`${j.id} · ${labels[j.status]||(j.within_limit?'可提交':'超限')} · ${j.chars.toLocaleString()} 字符\n${j.reason||''}\n目标文件：\n${j.target_files.join('\n')}\n随批提供的完整源码（含依赖）：\n${j.files.join('\n')}\n警告：${j.warnings.join('\n')||'无'}\n仅发送文件名的数据目录：\n${j.data_catalog.join('\n')||'无'}`).join('\n\n──────────\n\n');
  }
  $('workspaceBatchConsent').onchange=batchControls;
  $('workspaceBatchValidateConsent').onchange=batchControls;
  $('workspaceBatchPlan').onclick=async()=>{
    const project=activeProject,request=++batchRequest;if(!project)return;
    batchPreview=null;batchPlanning=true;$('workspaceBatchConsent').checked=false;batchControls();
    $('workspaceBatchProgress').hidden=false;
    $('workspaceBatchProgressText').textContent='正在本机规划批次（不发送源码）…';
    $('workspaceBatchProgressBar').removeAttribute('value');
    $('workspaceBatchProgressConnection').textContent='';
    $('workspaceBatchSummary').textContent='正在本机规划全部源码及完整依赖，不调用模型…';
    try {
      const result=await post('/api/workspace/projects/'+encodeURIComponent(project)+'/batch-preview');
      if(project!==activeProject||request!==batchRequest)return;
      batchPreview=result;showBatch(batchStatus?.confirmation_token===result.confirmation_token?{...result,...batchStatus}:result);
    }catch(e){if(project===activeProject)message('workspaceBatchSummary',e.message,true);}
    finally{batchPlanning=false;batchControls();}
  };
  $('workspaceBatchStart').onclick=async()=>{
    if(!batchPreview||!$('workspaceBatchConsent').checked)return;
    const project=activeProject;$('workspaceBatchStart').disabled=true;
    $('workspaceBatchProgress').hidden=false;
    $('workspaceBatchProgressText').textContent='正在提交任务并核对源码范围…';
    $('workspaceBatchProgressBar').removeAttribute('value');
    try {const result=await post('/api/workspace/projects/'+encodeURIComponent(project)+'/batch-analyze',{consent:true,confirmation_token:batchPreview.confirmation_token});if(project===activeProject)displayStatus(result);}
    catch(e){message('workspaceBatchSummary',e.message,true);$('workspaceBatchProgressText').textContent='提交未确认：'+e.message+'。请重新打开工程查询状态，不要立即重复提交。';batchControls();}
  };
  $('workspaceBatchFinalize').onclick=async()=>{
    const project=activeProject;if(!$('workspaceBatchValidateConsent').checked)return;
    $('workspaceBatchFinalize').disabled=true;
    try {const result=await post('/api/workspace/projects/'+encodeURIComponent(project)+'/batch-finalize',{consent:true,bundle_root:$('workspaceBatchRoot').value.trim()});if(project===activeProject)displayStatus(result);}
    catch(e){message('workspaceBatchSummary',e.message,true);batchControls();}
  };
  function analysisControls() {
    $('workspaceAnalyze').disabled=lastMode==='batch'||lastStatus==='working'||lastStatus==='ready'||!analysisPreview?.within_limit||!$('workspaceConsent').checked;
    $('workspaceAnalysisScope').disabled=lastStatus==='working'||lastStatus==='ready';
    $('workspaceRename').disabled=lastStatus==='working';
    batchControls();
  }
  async function previewAnalysis() {
    const project=activeProject, request=++scopeRequest, scope=$('workspaceAnalysisScope').value;
    analysisPreview=null;$('workspaceConsent').checked=false;analysisControls();
    $('workspaceAnalysisSummary').textContent='正在本机统计完整源码与静态依赖，不调用模型…';
    $('workspaceAnalysisFiles').textContent='';
    try {
      const plan=await post('/api/workspace/projects/'+encodeURIComponent(project)+'/analysis-preview',{scope});
      if(project!==activeProject||request!==scopeRequest)return;
      analysisPreview=plan;
      message('workspaceAnalysisSummary',`${plan.files.length} 个 Python 文件，共 ${plan.chars.toLocaleString()} 字符 / 单次上限 ${plan.limit.toLocaleString()}。${plan.within_limit?'可提交分析。':'超出上限，请选择更小图组或入口文件。'}\n自动补入 ${plan.added_dependencies.length} 个依赖文件；${plan.omitted_files.length} 个文件不发送正文。${plan.warnings.length?'存在依赖警告，请查看详情。':''}`,!plan.within_limit);
      $('workspaceAnalysisFiles').textContent=plan.files.join('\n')+'\n\n自动补入：\n'+(plan.added_dependencies.join('\n')||'无')+'\n\n依赖检查（不保证动态依赖完整）：\n'+(plan.warnings.join('\n')||'未发现静态检查警告')+'\n\n未发送正文（仍会提供文件名供模型识别缺失依赖）：\n'+(plan.omitted_files.join('\n')||'无')+'\n\n仅发送文件名的数据清单：\n'+(plan.data_catalog.join('\n')||'无');
      analysisControls();
    }catch(e){if(project===activeProject&&request===scopeRequest){message('workspaceAnalysisSummary',e.message,true);analysisControls();}}
  }
  async function loadAnalysisOptions(value) {
    const project=value.project, request=++scopeRequest;scopeProject=project;analysisPreview=null;analysisControls();
    try {
      const result=await api('/api/workspace/projects/'+encodeURIComponent(project)+'/analysis-options');
      if(activeProject!==project||scopeProject!==project||request!==scopeRequest)return;
      $('workspaceAnalysisScope').replaceChildren(...result.options.map(item=>new Option(`${item.kind==='file'?'入口':'目录'} · ${item.scope||'整个工程'} · ${item.chars.toLocaleString()} 字符（未补依赖）`,item.scope)));
      $('workspaceAnalysisScope').value=value.analysis_scope||'';
      await previewAnalysis();
    }catch(e){if(activeProject===project)message('workspaceAnalysisSummary',e.message,true);}
  }
  $('workspaceAnalysisScope').onchange=previewAnalysis;
  $('workspaceConsent').onchange=analysisControls;
  $('workspaceRename').onclick=async()=>{
    const project=activeProject;if(!project)return;
    $('workspaceRename').disabled=true;
    try {
      const result=await post('/api/workspace/projects/'+encodeURIComponent(project)+'/rename',{name:$('workspaceRenameName').value});
      if(activeProject===project){displayStatus(result);$('workspaceRenameName').value=result.display_name;}
      await refreshRecent();await reloadProjects();
      message('workspaceMessage','工程名称已更新；工程 ID、备份目录和修改记录保持不变。');
    }catch(e){message('workspaceMessage',e.message,true);}finally{analysisControls();}
  };
  function importFormChanged() {
    if(preparing)return;
    activeProject='';lastStatus='';scopeProject='';++scopeRequest;analysisPreview=null;
    $('workspacePreparation').hidden=true;$('workspaceConsent').checked=false;
    $('workspaceInventory').textContent='源目录或新副本名称已变更，请重新检查并点击“备份到本机并打开”。';
    message('workspaceMessage','正在编辑新建副本信息；尚未更新已有工程。重命名已有工程请先从上方打开，再使用“保存工程名称”。');
    analysisControls();
  }
  $('standardizeProjectName').oninput=importFormChanged;
  $('projectSourcePath').oninput=importFormChanged;
  let deleteInfo=null, deleting=false, deleteRequest=0;
  const belongsToProject=(key, project)=>{try{return JSON.parse(key)[0]===project;}catch{return false;}};
  function cancelDelete() {
    ++deleteRequest;deleteInfo=null;$('workspaceDeletePanel').hidden=true;
    $('workspaceDeleteName').value='';$('workspaceDeleteConfirm').disabled=true;
  }
  function deleteControls() {
    $('workspaceDelete').disabled=deleting||!$('workspaceRecent').value;
    $('workspaceRecent').disabled=deleting;$('workspaceResume').disabled=deleting;
    $('workspaceDeleteCancel').disabled=deleting;
    $('workspaceDeleteConfirm').disabled=deleting||!deleteInfo||$('workspaceDeleteName').value!==deleteInfo.project;
  }
  $('workspaceRecent').onchange=async()=>{
    cancelDelete();deleteControls();
    const project=$('workspaceRecent').value;
    activeProject='';lastStatus='';scopeProject='';analysisPreview=null;++scopeRequest;
    $('workspacePreparation').hidden=true;analysisControls();
    if(!project)return;
    try {const value=await api('/api/workspace/projects/'+encodeURIComponent(project)+'/status');if($('workspaceRecent').value===project)displayStatus(value);}
    catch(e){message('workspaceMessage',e.message,true);}
  };
  $('workspaceDeleteCancel').onclick=cancelDelete;
  $('workspaceDeleteName').oninput=deleteControls;
  $('workspaceDelete').onclick=async()=>{
    cancelDelete();const project=$('workspaceRecent').value, request=deleteRequest;
    if(!project)return;
    try {
      const info=await api('/api/workspace/projects/'+encodeURIComponent(project)+'/delete-preview');
      if(request!==deleteRequest||$('workspaceRecent').value!==project)return;
      deleteInfo=info;$('workspaceDeletePanel').hidden=false;
      $('workspaceDeleteScope').textContent=`工程：${info.project}\n将永久删除：${info.local_path}\n\n保留原始目录：\n${info.source_paths.length?info.source_paths.join('\n'):'未记录原始地址，无法确认是否另有原件；请先自行备份。仅删除上述工作区目录。'}\n\n${info.scope}`;
      deleteControls();$('workspaceDeleteName').focus();
    }catch(e){message('workspaceMessage',e.message,true);}
  };
  async function forgetDeletedProject(project) {
    // Drain read requests before clearing caches so late history responses cannot
    // resurrect cards from a removed project (including a subsequent re-import).
    await Promise.allSettled([...state.chatLoads].filter(([key])=>belongsToProject(key,project)).map(([,task])=>task));
    if(state.projectChatLoads.has(project))await Promise.allSettled([state.projectChatLoads.get(project)]);
    forgetProjectPreviews(project);state.openProjects.delete(project);
    for(const name of ['chatSessions','chatSessionLists','chatLoads','chatReferences','chatErrors','chatPending','chatPolling','chatBusy']) {
      for(const key of state[name].keys())if(belongsToProject(key,project))state[name].delete(key);
    }
    for(const name of ['projectChatHistory','projectChatLoaded','projectChatLoads','projectChatErrors'])state[name].delete(project);
    if(state.historyChart?.project===project){state.historyChart=null;$('historyDialog').close();}
    if(state.project===project) {
      ++state.detailRequest;state.project=null;state.chart=null;state.detail=null;state.selectedCharts.clear();
      $('editor').value='';$('filename').textContent='chart.py';$('dataInfo').textContent='';
      $('breadcrumb').textContent='PROJECT / CHARTS';$('chartTitle').textContent='请选择一个项目';
      $('description').textContent='工程副本已删除，原始目录保留。';
      $('galleryTitle').textContent='项目图集';$('galleryCount').textContent='0 张图';
      $('refresh').disabled=true;$('svg').hidden=true;$('pdf').hidden=true;
      drawGallery();updateSelection();renderChat();tab('figure');
      $('gallery').textContent='请选择左侧的项目，或打开一个新的本地工程。';
    }
  }
  $('workspaceDeleteConfirm').onclick=async()=>{
    const info=deleteInfo;
    if(deleting||!info||$('workspaceDeleteName').value!==info.project)return;
    if([...state.chatBusy].some(key=>belongsToProject(key,info.project))) {
      message('workspaceMessage','工程正在改图，请完成后再删除。',true);return;
    }
    deleting=true;deleteControls();
    try {
      await post('/api/workspace/projects/'+encodeURIComponent(info.project)+'/delete',{
        confirm_name:info.project,confirmation_token:info.confirmation_token});
      if(activeProject===info.project){activeProject='';lastStatus='';$('workspacePreparation').hidden=true;}
      await forgetDeletedProject(info.project);cancelDelete();
      $('workspaceRecent').value='';await reloadProjects();await refreshRecent();
      message('workspaceMessage',`已删除 ${info.project} 的本机工作副本；原始文件夹和已下载备份保持不变。此删除不可撤销。`);
      alertStatus('工程副本已删除，原始文件夹保留');
    }catch(e){message('workspaceMessage',e.message,true);}
    finally{deleting=false;deleteControls();}
  };
  const projectRoute = suffix => '/api/workspace/projects/'+encodeURIComponent(activeProject)+'/'+suffix;
  function inventoryText(files, skipped=[]) {
    return files.map(f=>`${f.kind==='code'?'[本机源码备份]':'[本机数据备份]'} ${f.path} (${f.bytes} bytes)`).join('\n')+
      (skipped.length?'\n\n疑似凭据文件已跳过：\n'+skipped.join('\n'):'');
  }
  function showResult(value){
    const result=value.batch?.outcome||value.task_outcome;
    const terminal=result&&!['working','pending'].includes(result.status);
    const blocked=['needs_context','unsupported','interrupted'].includes(value.status);
    $('workspaceResultEnter').hidden=value.can_open!==true;
    $('workspaceResultEnter').disabled=value.can_open!==true||!!enteringProject;
    $('workspaceResultEnter').textContent=value.figures?.length?`打开已验证的 ${value.figures.length} 张图`:'打开已验证图表';
    $('workspaceResult').hidden=!(terminal||blocked||value.status==='ready'||value.status==='pending_local_run');
    const failure=terminal?result.status!=='success':blocked;
    $('workspaceResult').className=failure?'taskResultFailure':'taskResultSuccess';
    $('workspaceResultTitle').textContent=`${value.display_name||value.project} · ${result?.label||({ready:'成功：工程已准备完成',pending_local_run:'成功：拆分方案已生成，待本机导出／验证',needs_context:'被阻止：需要补充依赖',unsupported:'被阻止：当前内容不支持',interrupted:'失败：任务中断'}[value.status]||'任务结果')}`;
    const finished=value.batch?.attempt?.finished_at;
    $('workspaceResultSummary').textContent=(result?.total!==undefined?`成功 ${result.succeeded} 批 · 失败 ${result.failed} 批 · 被阻止 ${result.blocked} 批`:(value.reason||''))+(finished?'\n本次任务结束时间：'+new Date(finished*1000).toLocaleString():'');
    const reasons=result?.reasons||[];
    $('workspaceResultReasons').replaceChildren();
    for(const item of reasons){
      const li=document.createElement('li');li.textContent=(item.files?.join('、')||item.batch||'批次')+'：'+item.reason;$('workspaceResultReasons').appendChild(li);
    }
    for(const warning of value.warnings||[]){
      const li=document.createElement('li');li.className='error';
      const lines=warning.trim().split('\n');
      if(lines.length>1){
        const details=document.createElement('details'),summary=document.createElement('summary'),full=document.createElement('pre');
        summary.textContent='警告：'+lines[0].split('：')[0]+'：'+lines[lines.length-1];
        full.textContent=warning;details.append(summary,full);li.append(details);
      }else li.textContent='警告：'+warning;
      $('workspaceResultReasons').appendChild(li);
    }
    if(result?.error){const li=document.createElement('li');li.textContent='汇总错误：'+result.error;$('workspaceResultReasons').appendChild(li);}
    if(failure&&!reasons.length&&value.reason){const li=document.createElement('li');li.textContent=value.reason;$('workspaceResultReasons').appendChild(li);}
    $('workspaceResultNext').textContent=failure?(value.mode==='native'?'已保留项目副本。请查看实际绘图错误和环境警告；版本差异本身不会阻止默认环境试绘。':value.mode==='universal'?'已保留项目副本。请查看未通过入口的实际运行错误、缺失文件或环境依赖；未验证的图不会进入改图列表。':'项目副本仍保留。超时与超限需分别处理；原样重试不会处理超限批次。上方展示的是已保存结果，重新打开工程不会清除。'):value.can_open?'可进入对话改图。':'当前仅完成拆分方案生成，请继续本机导出和验证；尚未生成可直接改图的完整工程。';
    if(!$('workspaceResult').hidden)requestAnimationFrame(()=>$('workspaceResult').scrollIntoView({block:'start',behavior:'smooth'}));
  }
  function displayStatus(value) {
    const changed=activeProject!==value.project;
    if(changed){scopeProject='';analysisPreview=null;++scopeRequest;$('workspaceConsent').checked=false;batchPreview=null;batchStatus=null;++batchRequest;$('workspaceBatchConsent').checked=false;$('workspaceBatchValidateConsent').checked=false;$('workspaceBatchSummary').textContent='';$('workspaceBatchDetails').textContent='';}
    activeProject=value.project; lastStatus=value.status;
    showResult(value);
    if(lastStatus==='working'){
      if(changed||!taskStarted)taskStarted=value.started_at||Date.now()/1000;
      taskMessage=value.reason||'拆分任务正在运行';showTaskProgress();
    }else{
      taskStarted=0;$('workspaceTaskProgress').hidden=true;
    }
    $('workspaceAnalyze').textContent=lastStatus==='working'?'正在拆分…':'用 Skill 分析并生成提取方案';
    $('workspaceBatchStart').textContent=lastStatus==='working'?'正在拆分…':'开始 / 继续整工程拆分';
    if(changed)$('workspaceBatchProgress').hidden=true;
    currentCanOpen=value.can_open===true;
    nativeAvailable=value.native_available===true;
    universalAvailable=value.universal_available===true;
    if(changed){$('workspaceNativeConsent').checked=false;$('workspaceUniversalConsent').checked=false;$('workspaceEnvironmentMode').value=value.environment_mode||'default';}
    $('workspaceEnvironmentMode').disabled=value.status==='working';
    $('workspaceEnvironmentReport').textContent=(value.render_environment?'实际环境：'+(value.render_environment.mode==='strict'?'严格复现独立环境':'平台默认环境')+'\nPython：'+(value.render_environment.python||'以实际容器为准')+'\n':'')+(value.warnings||[]).join('\n');
    $('workspaceNativePanel').hidden=!nativeAvailable||currentCanOpen;
    $('workspaceNativeStart').disabled=!$('workspaceNativeConsent').checked||value.status==='working';
    $('workspaceNativeProgress').value=value.native_progress?.completed||0;
    $('workspaceNativeProgress').max=value.native_progress?.total||7;
    $('workspaceUniversalPanel').hidden=!universalAvailable||currentCanOpen||nativeAvailable;
    $('workspaceUniversalStart').disabled=!$('workspaceUniversalConsent').checked||value.status==='working';
    $('workspaceUniversalSummary').textContent=value.universal_discovery?`静态发现 ${value.universal_discovery.candidate_count} 个候选入口：${value.universal_discovery.entries.join('、')}`:'等待本地静态发现结果。';
    $('workspaceUniversalProgress').value=value.universal_progress?.completed||0;
    $('workspaceUniversalProgress').max=value.universal_progress?.total||Math.max(value.universal_discovery?.candidate_count||1,1);
    const universalFailed=value.mode==='universal'&&value.status==='needs_context';
    $('workspaceBatchPanel').hidden=currentCanOpen||nativeAvailable||(universalAvailable&&!universalFailed);
    $('workspaceAdvanced').hidden=currentCanOpen||nativeAvailable||(universalAvailable&&!universalFailed)||value.mode==='batch';
    $('workspaceBatchValidation').hidden=!(value.batch?.jobs||[]).some(j=>['pending_local_run','validation_failed','ready'].includes(j.status));
    lastMode=value.mode||'';batchStatus=value.batch?{...value.batch,stage_updated_at:value.updated_at}:null;
    if(batchStatus){batchPreview=batchStatus;showBatch(batchStatus);}
    $('workspaceBatchDownload').hidden=!batchStatus||value.status==='working';
    $('workspaceBatchDownload').href=projectRoute('batch.zip');
    if(changed||!$('workspaceRenameName').value)$('workspaceRenameName').value=value.display_name||value.project;
    if([...$('workspaceRecent').options].some(o=>o.value===value.project))$('workspaceRecent').value=value.project;
    $('workspacePreparation').hidden=false;
    $('workspaceProjectTitle').textContent=`工程：${value.display_name||value.project}（ID：${value.project}）`;
    const labels={ready:'成功：已准备完成，可改图',working:'正在拆分／验证',needs_analysis:'待开始或需重试',pending_local_run:'成功：拆分方案已生成，待本机导出／验证',needs_context:'被阻止：需要补充依赖',unsupported:'被阻止：当前依赖不支持',interrupted:'失败：上次任务中断'};
    message('workspacePreparationState',`${value.batch?.outcome?.label||value.task_outcome?.label||labels[value.status]||value.status}\n${value.reason||''}\n本机目录：${value.local_path}${value.analysis_scope?'\n提取范围：'+value.analysis_scope+'（不代表整个工程）':''}`);
    $('workspaceInventory').textContent=inventoryText(value.files||[],value.skipped||[]);
    const generated=(value.generated_files||[]).length===2;
    $('workspaceAnalysisPanel').hidden=value.status==='ready'||lastMode==='batch';
    $('workspaceConsent').parentElement.hidden=lastMode==='batch';$('workspaceAnalyze').hidden=lastMode==='batch';
    analysisControls();
    if($('workspaceAdvanced').open&&scopeProject!==value.project&&value.status!=='ready'&&lastMode!=='batch')loadAnalysisOptions(value);
    const direct=value.mode==='direct';
    const needsValidation=value.status!=='ready'&&(generated||direct);
    $('workspaceBundleLabel').hidden=!needsValidation||direct;
    $('workspaceExecutionLabel').hidden=!needsValidation;
    $('workspaceFinalize').hidden=!needsValidation;
    $('workspaceFinalize').disabled=(!generated&&!direct)||value.status==='working'||value.status==='ready'||value.status==='needs_context';
    $('workspaceBundlePath').disabled=direct;
    $('workspaceBundlePath').placeholder=direct?'已有独立数据，无需另选导出目录':'包含 manifest.json 的目录';
    $('workspaceFinalize').textContent=direct?'验证已有独立绘图代码':'验证数据并准备改图';
    $('workspaceEnter').disabled=!currentCanOpen;
    $('workspacePlan').hidden=!generated;
    $('workspaceRunHint').hidden=!generated||value.status==='ready';
    $('workspacePlan').href=projectRoute('prepare.zip');
    $('workspaceBackup').hidden=value.status!=='ready';$('workspaceBackup').href=projectRoute('backup.zip');
    $('workspaceDetails').textContent=JSON.stringify({mode:value.mode,figures:value.figures,universal_discovery:value.universal_discovery,universal_progress:value.universal_progress,required_local_inputs:value.required_local_inputs,validation:value.validation},null,2);
  }
  async function refreshRecent() {
    const result=await api('/api/workspace/projects');
    if(result.projects.some(p=>typeof p.can_open!=='boolean')){
      message('workspaceMessage','服务仍为旧版本。请等待正在运行的任务结束后重启服务，使新的工程筛选流程生效。',true);
    }
    const select=$('workspaceRecent'), chosen=activeProject||select.value||state.project;
    const opening=$('workspaceMode').value==='open';
    const projects=result.projects.filter(p=>opening?p.can_open===true:p.can_open!==true);
    $('workspaceRecentLabel').textContent=opening?'已有独立绘图工程':'未完成工程（选择后继续，不必重复新建）';
    $('workspaceResume').textContent=opening?'打开并改图':'继续拆分';
    select.replaceChildren(new Option(opening?'选择已拆分工程…':'新建工程，或选择未完成的副本…',''),...projects.map(p=>new Option(`${p.display_name||p.project}（${p.project}）${opening?'':' · '+p.status}`,p.project)));
    if(projects.some(p=>p.project===chosen))select.value=chosen;
    deleteControls();
  }
  async function openWorkspace() {
    closeCreateMenu();cancelDelete();$('standardizeDialog').showModal();
    $('workspaceNewFields').hidden=$('workspaceMode').value!=='new';
    try {await refreshRecent();const project=$('workspaceRecent').value;if(project)displayStatus(await api('/api/workspace/projects/'+encodeURIComponent(project)+'/status'));else $('workspacePreparation').hidden=true;}catch(e){message('workspaceMessage',e.message,true);}
  }
  const openButton=document.createElement('button');openButton.id='openWorkspace';openButton.type='button';openButton.textContent='📁 打开工程';
  $('modelConfigButton').before(openButton);openButton.onclick=openWorkspace;
  $('standardizeProject').textContent='📁 新建并拆分工程';$('standardizeProject').onclick=()=>{$('workspaceMode').value='new';openWorkspace();};
  $('createProject').textContent='＋ 新建并拆分工程';
  $('createProject').onclick=()=>{$('workspaceMode').value='new';openWorkspace();};
  $('workspaceBrowse').onclick=async()=>{
    $('workspaceBrowse').disabled=true;
    try {message('workspaceMessage','请在本机文件夹窗口选择目录；也可直接填写完整地址。');const result=await post('/api/workspace/pick-folder');if(result.path){$('projectSourcePath').value=result.path;importFormChanged();await inspectSource();}}
    catch(e){message('workspaceMessage',e.message,true);}finally{$('workspaceBrowse').disabled=false;}
  };
  async function inspectSource() {
    const result=await post('/api/workspace/inspect',{source:$('projectSourcePath').value.trim()});
    if(!$('standardizeProjectName').value.trim())$('standardizeProjectName').value=result.name;
    $('workspaceInventory').textContent=inventoryText(result.files,result.skipped);
    message('workspaceMessage',`${result.files.length} 个支持文件，${(result.bytes/1024/1024).toFixed(1)} MiB。${result.message}`);
  }
  $('workspaceInspect').onclick=()=>inspectSource().catch(e=>message('workspaceMessage',e.message,true));
  $('startStandardize').onclick=async()=>{
    if(preparing)return;preparing=true;$('startStandardize').disabled=true;
    for(const id of ['standardizeProjectName','projectSourcePath','workspaceBrowse','workspaceInspect'])$(id).disabled=true;
    try {const result=await post('/api/workspace/open',{source:$('projectSourcePath').value.trim(),name:$('standardizeProjectName').value.trim(),allow_local_execution:$('workspaceTrust').checked});
      displayStatus(result);$('workspaceConsent').checked=false;$('workspaceValidateConsent').checked=false;
      message('workspaceMessage',result.reopened?'已打开保存的工程；未覆盖任何修改。':'已建立本机工程副本。未运行原分析，也未发送代码。');
      await refreshRecent();await reloadProjects();
      if(result.can_open){await enter();}
      else if(!result.batch&&!result.native_available&&!result.universal_available&&result.status!=='working'&&!result.generated_files?.length){await $('workspaceBatchPlan').onclick();}
    }catch(e){message('workspaceMessage',e.message,true);}finally{preparing=false;$('startStandardize').disabled=false;for(const id of ['standardizeProjectName','projectSourcePath','workspaceBrowse','workspaceInspect'])$(id).disabled=false;}
  };
  $('workspaceResume').onclick=async()=>{
    const project=$('workspaceRecent').value;if(!project)return;
    try {const value=await api('/api/workspace/projects/'+encodeURIComponent(project)+'/status');displayStatus(value);if(value.can_open)await enter();else if(!value.batch&&!value.native_available&&!value.universal_available&&value.status!=='working'&&!value.generated_files?.length)await $('workspaceBatchPlan').onclick();}catch(e){message('workspaceMessage',e.message,true);}
  };
  $('workspaceAnalyze').onclick=async()=>{
    if(!analysisPreview?.within_limit||!$('workspaceConsent').checked)return;
    $('workspaceAnalyze').disabled=true;
    const project=activeProject;
    try {const result=await post(projectRoute('analyze'),{consent:true,scope:analysisPreview.scope,confirmation_token:analysisPreview.confirmation_token});if(activeProject===project)displayStatus(result);}
    catch(e){message('workspaceMessage',e.message,true);analysisControls();}
  };
  $('workspaceFinalize').onclick=async()=>{
    $('workspaceFinalize').disabled=true;
    try {displayStatus(await post(projectRoute('finalize'),{bundle:$('workspaceBundlePath').value.trim(),allow_local_execution:$('workspaceValidateConsent').checked}));}
    catch(e){message('workspaceMessage',e.message,true);$('workspaceFinalize').disabled=false;}
  };
  let enteringProject='';
  async function enter() {
    if(!activeProject||!currentCanOpen||enteringProject)return;
    const project=activeProject,buttons=[$('workspaceEnter'),$('workspaceResultEnter')];
    const labels=buttons.map(button=>button.textContent);
    enteringProject=project;for(const button of buttons){button.disabled=true;button.textContent='正在打开工程…';}
    message('workspaceMessage','正在加载已验证图表，请稍候…');
    try {
      await reloadProjects();
      if(activeProject!==project)return;
      const p=projectInfo(project);
      if(!p||!p.charts?.length)throw new Error('未找到可打开的已验证图表，请刷新工程状态。');
      showProject(project);
      $('standardizeDialog').close();
      alertStatus('已打开工程，正在加载图表详情…');
      const selected=await select(project,p.charts[0]);
      if(selected!==false&&state.project===project)
        alertStatus('已打开工程，可在右侧对话改图；预览图片在后台加载。');
    } finally {
      enteringProject='';buttons.forEach((button,index)=>{button.textContent=labels[index];button.disabled=!currentCanOpen;});
    }
  }
  $('workspaceEnter').onclick=()=>enter().catch(e=>message('workspaceMessage',e.message,true));
  $('workspaceResultEnter').onclick=$('workspaceEnter').onclick;
  setInterval(async()=>{
    if(taskSubmitting||polling||!$('standardizeDialog').open||!activeProject||lastStatus!=='working')return;
    const project=activeProject;
    polling=true;try{const result=await api(projectRoute('status'));if(project!==activeProject||deleting)return;displayStatus(result);if(lastStatus!=='working')await refreshRecent();}
    catch(e){message('workspaceMessage',e.message,true);$('workspaceBatchProgressConnection').textContent='进度查询失败，显示的是上次状态；后台任务不一定停止。下一轮自动重试。';}finally{polling=false;}
  },2000);
  for(const id of ['workspaceAnalyze','workspaceNativeStart','workspaceUniversalStart','workspaceBatchStart','workspaceBatchFinalize','workspaceFinalize']){
    const original=$(id).onclick;
    $(id).onclick=async(...args)=>{
      if($(id).disabled||taskSubmitting)return;
      taskSubmitting=true;taskStarted=Date.now()/1000;taskMessage='已开始提交拆分 / 验证任务，请稍候';showTaskProgress();
      try{await original(...args);}finally{
        taskSubmitting=false;
        if(lastStatus!=='working'){taskStarted=0;$('workspaceTaskProgress').hidden=true;}
      }
    };
  }
  updateChatControls();
  setTimeout(openWorkspace,100);
})();
