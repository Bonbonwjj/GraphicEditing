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
  for (const key of ['name', 'email']) {
    document.getElementById('collab-' + key).value = collabState[key] || '';
  }
  document.getElementById('collabTarget').textContent = collabState.target_ready
    ? `${collabState.remote} · ${collabState.branch} · projects/`
    : `${collabState.remote || ''} · 团队分支待平台维护者确认`;
  for (const id of ['connectCollaboration', 'publishCollaboration']) {
    document.getElementById(id).disabled = !collabState.target_ready;
  }
  document.getElementById('collabStatus').textContent = teamSyncNotice || (collabState.configured
    ? `已连接 ${collabState.remote} · ${collabState.branch} · 协作者 ${collabState.name}`
    : '打开或刷新页面时自动获取团队版本；首次提交前请保存协作者身份。');
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
    if (collabState && !collabState.target_ready) {
      for (const id of ['connectCollaboration', 'publishCollaboration']) document.getElementById(id).disabled = true;
    }
  }
}
document.getElementById('connectCollaboration').onclick = event => collabAction(event.target, async () => {
  const body = {};
  for (const key of ['name', 'email']) body[key] = document.getElementById('collab-' + key).value.trim();
  await collabRequest('collaboration', body);
  await loadCollaboration();
});
window.syncTeamOnOpen = async () => {
  const indicator = document.getElementById('teamSyncStatus');
  indicator.textContent = '正在获取团队最新版本…';
  try {
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
document.getElementById('publishCollaboration').onclick = event => collabAction(event.target, async () => {
  const result = await collabRequest('collaboration/publish', {message: document.getElementById('publishMessage').value});
  document.getElementById('collabStatus').textContent = `已发布 ${result.files} 个文件 · ${result.author} · ${result.revision.slice(0, 10)}`;
  document.getElementById('publishMessage').value = '';
});
