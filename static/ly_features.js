/* Bundle imports and shared-module candidates extend, rather than replace, chart Chat. */
const ly = id => document.getElementById(id);
const lyPost = (path, body) => api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
ly('importBundleButton').onclick = async () => {
  ly('bundleImportDialog').showModal();
  try {
    const settings=await api('/api/data-sources/capabilities');
    ly('bundleRuntimeRoot').value=settings.runtime_source||'';
    ly('bundleAllowedRoot').value=settings.shared_roots?.[0]||'';
  } catch(error) {ly('bundleImportStatus').textContent=error.message;}
};
ly('closeBundleImport').onclick=()=>ly('bundleImportDialog').close();
ly('startBundleImport').onclick=async()=>{
  const button=ly('startBundleImport');button.disabled=true;
  try {
    const project_id=ly('bundleProjectId').value.trim(), name=ly('bundleProjectName').value.trim();
    if(!project_id||!name)throw new Error('请填写项目 ID 和名称');
    if(!ly('bundleTrusted').checked)throw new Error('请先确认 Bundle 来源可信');
    await lyPost('/api/data-sources/settings',{
      shared_roots:(ly('bundleAllowedRoot').value.trim()||(ly('bundleSourceMode').value==='server_path'?ly('bundleServerPath').value.trim():''))?[ly('bundleAllowedRoot').value.trim()||ly('bundleServerPath').value.trim()]:[],
      runtime_source:ly('bundleRuntimeRoot').value.trim()
    });
    ly('bundleImportStatus').textContent='正在校验数据并创建项目…';
    let result;
    if(ly('bundleSourceMode').value==='upload'){
      const files=Array.from(ly('bundleFolder').files).filter(file=>/\.(json|gz)$/i.test(file.name));
      if(!files.length)throw new Error('请选择包含 manifest.json 的 Bundle 文件夹');
      if(files.reduce((sum,file)=>sum+file.size,0)>500_000_000)throw new Error('超过浏览器上传上限，请改用“从本机目录复制”');
      const form=new FormData();
      for(const [key,value] of Object.entries({project_id,name,trusted:'true',share_mode:'embedded'}))form.append(key,value);
      files.forEach(file=>form.append('bundle_files',file,uploadRelativePath(file)));
      result=await api('/api/data-sources/import-upload',{method:'POST',body:form});
    }else{
      result=await lyPost('/api/data-sources/import',{project_id,name,trusted:true,share_mode:'embedded',source_path:ly('bundleServerPath').value.trim()});
    }
    await reloadProjects();state.openProjects.add(result.project);await showProject(result.project,true);
    ly('bundleImportStatus').textContent=`已创建 ${result.charts.length} 张图。数据已复制到本机项目；信任项目后可运行，在“团队协作”发布后其他成员可从 GitHub 拉取。单文件超限会阻止发布，不会丢弃数据。`;
  }catch(error){ly('bundleImportStatus').textContent=error.message;}
  finally{button.disabled=false;}
};

let moduleContext=null;
window.openSharedModule=async(project,id,options={})=>{
  const base=`/api/projects/${encodeURIComponent(project)}/modules/${encodeURIComponent(id)}`;
  try {
    const detail=await api(base+'/detail');
    moduleContext={project,id,base,draft:null};
    ly('sharedModuleTitle').textContent=detail.module.path;
    ly('sharedModuleEditor').value=detail.code;
    ly('sharedModulePrompt').value=options.prompt||'';ly('sharedModulePreviews').replaceChildren();
    ly('moduleForceAll').checked=options.forceAll===true;
    ly('sharedModuleStatus').textContent='编辑只保存在此处；生成候选、人工检查后再应用。';
    ly('moduleReviewed').checked=false;ly('applySharedModule').disabled=true;
    ly('moduleDataReviewed').checked=false;ly('moduleDataReviewWrap').hidden=true;ly('moduleCheckReports').replaceChildren();
    ly('validationChart').replaceChildren(...state.projects.find(p=>p.id===project).charts.map(chart=>{
      const option=document.createElement('option');option.value=chart;option.textContent=chart;return option;
    }));
    if(options.chart)ly('validationChart').value=options.chart;
    ly('moduleHistory').replaceChildren(...detail.history.slice().reverse().map(item=>{
      const button=document.createElement('button');button.textContent=item.note+' · '+item.time;
      button.onclick=async()=>{
        try {
          const restored=await lyPost(base+'/restore-preview',{revision:item.id,chart:ly('validationChart').value,force_all:ly('moduleForceAll').checked});
          ly('sharedModuleEditor').value=restored.source;showModuleDraft(restored);
        }catch(error){ly('sharedModuleStatus').textContent=error.message;}
      };return button;
    }));
    ly('sharedModuleDialog').showModal();
  }catch(error){alertStatus(error.message);}
};
function invalidateModuleDraft(){if(moduleContext)moduleContext.draft=null;ly('applySharedModule').disabled=true;ly('moduleReviewed').checked=false;ly('moduleDataReviewed').checked=false;}
function showModuleDraft(draft){
  moduleContext.draft=draft;ly('moduleReviewed').checked=false;ly('applySharedModule').disabled=true;
  ly('moduleDataReviewed').checked=false;ly('moduleDataReviewWrap').hidden=!draft.requires_data_review;
  ly('moduleCheckReports').replaceChildren(...(draft.checks||[]).map(check=>{
    const row=document.createElement('p');row.textContent=`${check.chart}：数据/几何变化 ${check.changed}，移除 ${check.removed}，新增 ${check.added}，可见性变化 ${check.visibility_changes}，坐标变化 ${check.axes_changes}；布局 ${check.layout_status}（${check.layout_issues.length} 项）。`;return row;
  }));
  ly('sharedModuleStatus').textContent=`检测到 ${draft.changed_locations} 处修改；本轮验证 ${draft.charts.length} 张图，可能影响 ${draft.affected_charts.length} 张：${draft.affected_charts.join('、')}。${draft.limitations} 也可继续编辑后重新生成候选。`;
  ly('sharedModulePreviews').replaceChildren(...draft.charts.map(chart=>{
    const figure=document.createElement('figure'),caption=document.createElement('figcaption'),image=document.createElement('img');
    caption.textContent=chart;image.alt=chart+' 候选图';image.src=moduleContext.base+`/drafts/${draft.id}/image/${encodeURIComponent(chart)}`;
    figure.append(caption,image);return figure;
  }));
}
ly('closeSharedModule').onclick=()=>ly('sharedModuleDialog').close();
ly('sharedModuleEditor').oninput=invalidateModuleDraft;
ly('moduleForceAll').onchange=invalidateModuleDraft;
ly('validationChart').onchange=invalidateModuleDraft;
function updateModuleApply(){ly('applySharedModule').disabled=!moduleContext?.draft||!ly('moduleReviewed').checked||(moduleContext.draft.requires_data_review&&!ly('moduleDataReviewed').checked);}
ly('moduleReviewed').onchange=updateModuleApply;
ly('moduleDataReviewed').onchange=updateModuleApply;
ly('proposeSharedModule').onclick=async()=>{
  const context=moduleContext,original=ly('sharedModuleEditor').value;
  try {
    ly('proposeSharedModule').disabled=true;invalidateModuleDraft();
    const result=await lyPost(context.base+'/propose',{source:ly('sharedModuleEditor').value,prompt:ly('sharedModulePrompt').value,chart:ly('validationChart').value});
    if(moduleContext!==context||ly('sharedModuleEditor').value!==original)return;
    ly('sharedModuleEditor').value=result.code;ly('sharedModuleStatus').textContent=result.reply;
  }catch(error){ly('sharedModuleStatus').textContent=error.message;}
  finally{ly('proposeSharedModule').disabled=false;}
};
ly('previewSharedModule').onclick=async()=>{
  const context=moduleContext,original=ly('sharedModuleEditor').value;
  try {
    ly('previewSharedModule').disabled=true;invalidateModuleDraft();ly('sharedModuleStatus').textContent='正在生成候选，不会覆盖正式模块…';
    const draft=await lyPost(context.base+'/preview',{source:original,chart:ly('validationChart').value,force_all:ly('moduleForceAll').checked});
    if(moduleContext!==context||ly('sharedModuleEditor').value!==original)return;
    showModuleDraft(draft);
  }catch(error){ly('sharedModuleStatus').textContent=error.message;}
  finally{ly('previewSharedModule').disabled=false;}
};
ly('applySharedModule').onclick=async()=>{
  try {
    ly('applySharedModule').disabled=true;
    const draft=moduleContext.draft;
    if(!draft||draft.source!==ly('sharedModuleEditor').value)throw new Error('编辑器已变化，请重新验证');
    await lyPost(moduleContext.base+'/apply',{draft_id:draft.id,acknowledge:ly('moduleReviewed').checked,acknowledge_data_changes:ly('moduleDataReviewed').checked});
    invalidateModuleDraft();await reloadProjects();forgetProjectPreviews(moduleContext.project);
    ly('sharedModuleStatus').textContent='候选已应用，正式版本和历史已更新。需要时可继续编辑，发布到 GitHub 仍需点击团队协作中的发布。';
  }catch(error){ly('sharedModuleStatus').textContent=error.message;}
};
