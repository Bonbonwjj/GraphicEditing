/* Local folder/path inputs and observable asynchronous code splitting. */
function importProgressText(job, now=Date.now()/1000) {
  const elapsed=Math.max(0,Math.floor((job.finished_at||now)-(job.started_at||now)));
  const count=job.total?`已处理 ${job.completed||0} / ${job.total} 个代码文件`:job.status==='completed'?`已生成 ${job.result?.charts?.length||0} 张图表`:'正在统计文件';
  const stage={queued:'任务已接收 · 等待开始',inspecting:'正在检查代码与数据',copying:'正在复制数据',splitting:'正在拆分代码',saving:'正在保存结果',completed:'成功：拆分完成',failed:'失败：拆分未完成',uploading:'正在上传文件'}[job.stage]||'正在处理';
  return `${stage} · 已用时 ${elapsed} 秒\n${job.message||''}${job.current_file?'\n当前文件：'+job.current_file:''}${['splitting','saving','completed'].includes(job.stage)?'\n'+count:''}`;
}
if(typeof module!=='undefined'&&module.exports)module.exports={importProgressText};
else (()=>{
  const key='plot-forge-upload-job';
  let busy=false,job=null,pollTimer=null;
  const originalOpen=$('uploadPackage').onclick;
  const selectedFiles=kind=>$(kind+'SelectedFiles').files.length?$(kind+'SelectedFiles').files:$(kind+'Folder').files;
  function storage(value){try{if(value)sessionStorage.setItem(key,value);else sessionStorage.removeItem(key);}catch(e){}}
  function controls(value){
    busy=value;
    $('uploadDialog').querySelectorAll('input,select,button').forEach(el=>{if(el.id!=='closeUpload')el.disabled=value;});
    $('startUpload').textContent=value?'正在拆分…':'开始拆分并上传';
    $('closeUpload').textContent=value?'关闭（后台继续）':'关闭';
  }
  function draw(){
    if(!job)return;
    $('uploadProgress').hidden=false;
    $('uploadProgressText').textContent=importProgressText(job);
    $('uploadProgressText').className=job.status==='failed'?'error':'';
    const bar=$('uploadProgressBar');
    if(job.total){bar.max=job.total;bar.value=job.completed||0;}
    else bar.removeAttribute('value');
    bar.setAttribute('aria-label',job.stage==='uploading'?'文件上传进度':'已处理代码文件数');
  }
  async function completed(result){
    controls(false);storage(null);draw();
    forgetProjectPreviews(result.project);await reloadProjects();state.openProjects.add(result.project);
    bubble(`拆分完成：${result.files} 个数据文件，${result.charts.length} 张图表。已保存在本机。`);
    if(result.errors?.length)$('uploadProgressConnection').textContent='部分文件使用了回退处理：'+result.errors.map(x=>x.file+'：'+x.error).join('；');
    if(result.charts[0])await select(result.project,result.charts[0]);
    alertStatus('代码拆分完成，可查看图集；普通预览在后台生成。');
  }
  async function poll(){
    if(!job?.id)return;
    try{
      job=await api('/api/uploads/jobs/'+encodeURIComponent(job.id));draw();
      $('uploadProgressConnection').textContent='进度每 1 秒更新。模型返回前无法估算当前文件的完成百分比。';
      if(job.status==='completed'){await completed(job.result);return;}
      if(job.status==='failed'){controls(false);storage(null);alertStatus('拆分失败，请查看弹窗内原因。');return;}
    }catch(e){if(e.message.includes('任务不存在或后台已重启')){job={...job,status:'failed',stage:'failed',message:e.message};controls(false);storage(null);draw();return;}$('uploadProgressConnection').textContent='进度查询失败：'+e.message+'；后台可能仍在处理，请勿重复提交，稍后自动重试。';}
    pollTimer=setTimeout(poll,1000);
  }
  setInterval(()=>{if(busy)draw();},1000);
  $('uploadPackage').onclick=()=>{
    if(busy){$('uploadDialog').showModal();draw();return;}
    originalOpen();for(const kind of ['code','data','image']){$(kind+'FolderPath').value='';$(kind+'SelectedFiles').value='';}
    if(!job)$('uploadProgress').hidden=true;
  };
  for(const kind of ['code','data','image']){
    $(kind+'BrowseLocal').onclick=async()=>{
      const button=$(kind+'BrowseLocal');button.disabled=true;
      $(kind+'FolderStatus').textContent='请选择文件夹；也可以直接粘贴路径。';
      try{
        const result=await postJSON('/api/workspace/pick-folder',{});
        if(result.path){$(kind+'FolderPath').value=result.path;$(kind+'Folder').value='';$(kind+'SelectedFiles').value='';$(kind+'FolderStatus').textContent='已选择本机目录';}
        else $(kind+'FolderStatus').textContent='已取消选择，可重新选择或粘贴路径。';
      }catch(e){$(kind+'FolderStatus').textContent=e.message;}
      finally{button.disabled=false;}
    };
    $(kind+'FolderPath').oninput=()=>{$(kind+'Folder').value='';$(kind+'SelectedFiles').value='';};
    const original=$(kind+'Folder').onchange;
    $(kind+'Folder').onchange=e=>{$(kind+'FolderPath').value='';$(kind+'SelectedFiles').value='';original(e);};
    $(kind+'SelectedFiles').onchange=()=>{$(kind+'FolderPath').value='';$(kind+'Folder').value='';$(kind+'FolderStatus').textContent=`已选择 ${selectedFiles(kind).length} 个文件`;};
  }
  $('startUpload').onclick=async()=>{
    if(busy)return;
    const existing=$('uploadProjectMode').value!=='__new__';
    const chosen=existing?state.projects.find(p=>p.id===$('uploadProjectMode').value):null;
    const name=existing?chosen?.name:$('uploadProjectName').value.trim();
    const project_id=existing?chosen?.id:$('uploadProjectId').value.trim();
    if(!name||!project_id){alert('请填写项目名称和项目 ID。');return;}
    for(const kind of ['code','data'])if(!$(kind+'FolderPath').value.trim()&&!selectedFiles(kind).length){alert('请选择代码和数据文件夹，或粘贴完整路径。');return;}
    controls(true);job={status:'working',stage:'uploading',message:'正在收集文件并提交拆分任务…',started_at:Date.now()/1000};draw();
    $('uploadProgressConnection').textContent='提交后将在此显示当前文件和处理进度。';
    const form=new FormData();form.append('name',name);form.append('project_id',project_id);form.append('existing',String(existing));form.append('async','true');
    for(const kind of ['code','data','image']){
      const path=$(kind+'FolderPath').value.trim();
      if(path)form.append(kind+'_path',path);
      else for(const file of selectedFiles(kind))form.append(kind+'_files',file,kind==='image'?file.name:uploadRelativePath(file));
    }
    try{
      const result=await new Promise((resolve,reject)=>{
        const xhr=new XMLHttpRequest();xhr.open('POST','/api/uploads/import');
        xhr.upload.onprogress=e=>{if(e.lengthComputable){job.message=`文件上传 ${Math.round(e.loaded/e.total*100)}%；上传完成后开始拆分。`;draw();}};
        xhr.onerror=()=>reject(new Error('连接中断，提交状态未确认，请检查工程结果后再重试。'));
        xhr.onload=()=>{try{const value=JSON.parse(xhr.responseText);if(xhr.status<200||xhr.status>=300)throw new Error(value.error||'提交失败');resolve(value);}catch(e){reject(e);}};
        xhr.send(form);
      });
      if(!result.id){await completed(result);return;}
      job=result;storage(job.id);draw();await poll();
    }catch(e){job={...job,status:'failed',stage:'failed',message:e.message,finished_at:Date.now()/1000};controls(false);draw();}
  };
  let saved;try{saved=sessionStorage.getItem(key);}catch(e){}
  if(saved){controls(true);job={id:saved,started_at:Date.now()/1000,status:'working',stage:'queued',message:'正在恢复后台拆分进度…'};draw();poll();}
})();
