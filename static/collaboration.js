/* Shared GitHub projects with local drafts and explicit local execution consent. */
const collabDialog = document.getElementById('collaborationDialog');
let collabState = null;
let teamSyncNotice = '';
const collabRequest = async (path, body) => {
  const response = await fetch('/api/' + path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
};
async function loadCollaboration() {
  collabState = await collabRequest('collaboration');
  const direct=collabState.mode==='direct',folder=direct||collabState.mode==='folder';
  document.getElementById('collaborationTitle').textContent=folder?'团队协作 · 公共文件夹':'团队协作 · GitHub 共享项目';
  document.getElementById('collabEmailRow').hidden=folder;
  document.getElementById('collabProjectChoices').hidden=!folder||direct;
  document.getElementById('publishCollaboration').hidden=direct;
  document.getElementById('collabMessageRow').hidden=direct;
  document.getElementById('pullCollaboration').textContent=direct?'刷新共享工程':'获取团队更新';
  document.getElementById('collabIdentityHint').textContent=folder?'填写姓名并选择参与共享的工程，然后保存。仅同步勾选工程，不需要 GitHub 登录。':'首次使用保存协作者姓名和 Git 提交邮箱，使用本机已有的 GitHub Git 登录。';
  document.getElementById('collabAutoHint').textContent=folder?'各自在本地编辑。开始前点击“获取团队更新”；修改后先应用并同步代码，再填写说明、上传。刷新页面不会自动同步。':'打开或刷新页面时自动获取团队最新版本。';
  if(direct){
    document.getElementById('collabIntro').textContent='所有成员直接读写同一个公共工程。正式代码、数据、图片和历史保存到共享盘；程序、模型配置和账号凭据仍各自保留在本机。';
    document.getElementById('collabIdentityHint').textContent='保存协作者姓名，用于记录修改人。无需 GitHub 登录，也无需上传或获取本地副本。';
    document.getElementById('collabAutoHint').textContent='图表修改确认后直接保存到共享盘。其他成员重新选择图表或刷新共享工程即可读取最新内容；刷新前请先保存本次修改。';
    document.getElementById('collabPublishHint').textContent='保存使用跨进程文件锁；正式图表代码已被其他成员修改时，旧页面会停止保存并要求重新加载，避免覆盖他人的修改。';
  }
  document.getElementById('publishCollaboration').textContent=folder?'上传所选工程并合并团队更新':'将全部项目修改合并到团队版本';
  const choices=document.getElementById('collabProjects');choices.replaceChildren();
  if(folder)for(const project of [...new Set([...(collabState.projects||[]),...(collabState.shared_projects||[])])]){
    const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=project;input.dataset.collabProject='';input.checked=collabState.shared_projects.includes(project);label.append(input,document.createTextNode(' '+project));choices.append(label);
  }
  for (const key of ['name', 'email']) {
    document.getElementById('collab-' + key).value = collabState[key] || '';
  }
  document.getElementById('collabTarget').textContent = folder?`${collabState.path} · projects/ · ${collabState.available?'可访问':'未连接'}`:collabState.target_ready
    ? `${collabState.remote} · ${collabState.branch} · projects/`
    : `${collabState.remote || ''} · 团队分支待平台维护者确认`;
  updateCollabButtons();
  document.getElementById('collabStatus').textContent = teamSyncNotice || (collabState.configured
    ? folder?`协作者 ${collabState.name} · 共享工程：${collabState.shared_projects.join('、')} · ${collabState.available?'共享目录已连接':'请先连接共享盘'}`:`已连接 ${collabState.remote} · ${collabState.branch} · 协作者 ${collabState.name}`
    : '打开或刷新页面时自动获取团队版本；首次提交前请保存协作者身份。');
  if(folder&&!teamSyncNotice&&!collabState.configured)document.getElementById('collabStatus').textContent=direct?'当前直接读写公共工程。可以先保存协作者姓名；共享盘不可访问时需恢复连接，不会切换到本机副本。':'请先保存协作者姓名与共享工程选择；共享盘不可访问时仍可在本机改图。';
}
function updateCollabButtons(){
  const folder=['folder','direct'].includes(collabState?.mode),unavailable=!collabState?.target_ready||(folder&&!collabState.available);
  document.getElementById('connectCollaboration').disabled=!collabState?.target_ready;
  for(const id of ['publishCollaboration','pullCollaboration'])document.getElementById(id).disabled=unavailable;
}
document.getElementById('collaborationButton').onclick = async () => {
  collabDialog.showModal();
  try { await loadCollaboration(); } catch (error) { document.getElementById('collabStatus').textContent = error.message; }
};
document.getElementById('closeCollaboration').onclick = () => collabDialog.close();
async function collabAction(button, action) {
  const buttons = collabDialog.querySelectorAll('button');
  buttons.forEach(item => item.disabled = true);
  document.getElementById('collabStatus').textContent = '正在处理，请稍候…';
  try { await action(); }
  catch (error) { document.getElementById('collabStatus').textContent = error.message; }
  finally {
    buttons.forEach(item => item.disabled = false);
    updateCollabButtons();
  }
}
document.getElementById('connectCollaboration').onclick = event => collabAction(event.target, async () => {
  const body = {};
  for (const key of ['name', 'email']) body[key] = document.getElementById('collab-' + key).value.trim();
  if(collabState?.mode==='folder')body.shared_projects=[...document.querySelectorAll('[data-collab-project]:checked')].map(input=>input.value);
  await collabRequest('collaboration', body);
  teamSyncNotice='';
  await loadCollaboration();
});
window.syncTeamOnOpen = async () => {
  const indicator = document.getElementById('teamSyncStatus');
  indicator.textContent = '正在获取团队最新版本…';
  try {
    collabState=await collabRequest('collaboration');
    if(['folder','direct'].includes(collabState.mode)){
      const direct=collabState.mode==='direct';
      teamSyncNotice=collabState.available?(direct?'正在直接读写公共工程；保存后其他成员可重新选择图表读取更新。':'共享目录可访问；使用“团队协作”手动获取更新或上传。'):`共享目录未连接：${collabState.path}。${direct?'请连接共享盘后重新加载，不会改为本机副本。':'当前使用本机版本。'}`;
      indicator.textContent=collabState.available?(direct?'直接共享工程':'共享文件夹 · 手动同步'):(direct?'共享盘未连接':'共享盘未连接 · 本机版本');indicator.title=teamSyncNotice;
      document.getElementById('collabStatus').textContent=teamSyncNotice;return;
    }
    const result = await collabRequest('collaboration/pull', {});
    teamSyncNotice = `已同步团队版本 ${result.revision.slice(0, 10)}；保留本机未提交修改。`;
    indicator.textContent = '团队版本已同步';
  } catch (error) {
    teamSyncNotice = `团队版本未同步：${error.message}。当前显示本机版本，处理后刷新页面重试。`;
    indicator.textContent = '未同步 · 当前为本机版本';
  }
  indicator.title = teamSyncNotice;
  document.getElementById('collabStatus').textContent = teamSyncNotice;
};
document.getElementById('pullCollaboration').onclick=event=>collabAction(event.target,async()=>{
  if(collabState?.mode==='direct'){
    const project=typeof state!=='undefined'?state.project:null,chart=typeof state!=='undefined'?state.chart:null;
    if(typeof reloadProjects==='function')await reloadProjects();
    if(project&&chart&&typeof select==='function')await select(project,chart);
    document.getElementById('collabStatus').textContent='已重新读取公共工程，当前保存位置：'+collabState.path;return;
  }
  const result=await collabRequest('collaboration/pull',{});
  document.getElementById('collabStatus').textContent=`已获取团队更新 ${result.revision.slice(0,10)}，保留本机未上传修改。重新选择图表可加载更新后的图片与代码。`;
  if(typeof reloadProjects==='function')await reloadProjects();
});
document.getElementById('publishCollaboration').onclick = event => collabAction(event.target, async () => {
  const result = await collabRequest('collaboration/publish', {message: document.getElementById('publishMessage').value});
  document.getElementById('collabStatus').textContent = `已发布 ${result.files} 个文件 · ${result.author} · ${result.revision.slice(0, 10)}`;
  document.getElementById('publishMessage').value = '';
});
