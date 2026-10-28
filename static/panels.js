// Source navigation is read on demand; edits stay in the chart's own entry.
const panelSelections = new Map();
let panelLoadedSource = null;
let panelLoadVersion = 0;
function panelTargetFor(context) {
  if(context.charts.length!==1)return {};
  const chart=context.charts[0],id=panelSelections.get(context.project+'/'+chart);
  return id?{[chart]:id}:{};
}
function renderPanelControls(){
  const context=chatContext(),single=context.charts.length===1&&context.charts[0]===state.chart;
  const index=single?state.detail?.panel_index:null,key=state.project+'/'+state.chart;
  const selected=panelSelections.get(key)||'';
  $('panelTarget').innerHTML='<option value="">整张图</option>'+(index?.panels||[]).map(p=>`<option value="${esc(p.id)}">${esc(p.label||'图 '+p.id)} · 轴 ${esc(p.axis_labels.join(', '))}</option>`).join('');
  $('panelTarget').value=(index?.panels||[]).some(p=>p.id===selected)?selected:'';
  if(index&&!$('panelTarget').value)panelSelections.delete(key);
  $('panelTarget').disabled=!index||state.chatBusy.has(context.key)||state.chatSessions.get(context.key)?.status==='running';
  $('viewPanelCode').disabled=!index;
  $('setPanelMapping').disabled=!index;
  const panel=index?.panels.find(p=>p.id===$('panelTarget').value);
  $('panelTargetInfo').textContent=!index?'选择单张图后可定位子图。':index.warning||
    (panel?`${panel.label||'图 '+panel.id} → 内部轴 ${panel.axis_labels.join(', ')}；修改后重绘整张图。`:'当前修改整张图；可选择子图并查看对应实现。');
  $('panelTargetInfo').className=index?.warning?'panelWarning':'';
  $('panelTarget').onchange=()=>{panelSelections.set(key,$('panelTarget').value);panelLoadedSource=null;panelLoadVersion++;renderPanelControls();drawPanelSections();};
  $('viewPanelCode').onclick=()=>{tab('code');drawPanelSections();$('panelSourceDetails').open=true;document.querySelector('main')?.scrollTo({top:0,behavior:'instant'});};
  $('setPanelMapping').onclick=async()=>{
    const current=Object.fromEntries((index.panels||[]).map(p=>[p.id,p.axis_labels]));
    const value=prompt('请输入可见面板到内部轴标签的 JSON 对应关系。可用轴标签：'+(index.axis_label_candidates.join(', ')||'请从源码 set_label 核对')+'。例如 {"a":["a","b"],"b":["c"]}',JSON.stringify(current));
    if(value===null)return;
    try{const result=await postChart(state.project,state.chart,'panel-mapping',{mapping:JSON.parse(value)});state.detail.panel_index=result;renderPanelControls();drawPanelSections();alertStatus('已保存子图对应关系；新一轮会读取最新映射。');}catch(e){alertStatus(e.message);}
  };
  $('panelSourceSection').onchange=loadPanelSource;
  $('savePanelSource').onclick=savePanelSource;
}
function drawPanelSections(){
  panelLoadedSource=null;panelLoadVersion++;
  const index=state.detail?.panel_index,selected=panelSelections.get(state.project+'/'+state.chart);
  const panel=index?.panels.find(p=>p.id===selected),refs=new Set(panel?.source_sections||[]);
  const rank=new Map((panel?.source_sections||[]).map((id,i)=>[id,i]));
  const sections=[...(index?.sections||[])].sort((a,b)=>(rank.get(a.id)??10000)-(rank.get(b.id)??10000));
  $('panelSourceSection').innerHTML=sections.map(s=>`<option value="${esc(s.id)}">${refs.has(s.id)?'相关 · ':''}${esc(s.path)}:${s.start_line}–${s.end_line} ${esc(s.symbols.join(', '))}</option>`).join('');
  $('panelSource').value='';$('savePanelSource').disabled=true;
  $('panelSourceStatus').textContent=panel?`图 ${panel.id} 对应轴 ${panel.axis_labels.join(', ')}。代码可能包含共用函数，修改时请核对其他子图。`:'完整源码按代码段列出；原始文件完整保存在项目中。';
  if(sections.length)loadPanelSource();
}
async function loadPanelSource(){
  const project=state.project,chart=state.chart,version=++panelLoadVersion;
  const section=state.detail?.panel_index?.sections.find(s=>s.id===$('panelSourceSection').value);
  if(!section)return;
  panelLoadedSource=null;$('savePanelSource').disabled=true;$('panelSourceStatus').textContent='正在读取源码…';
  try{
    const result=await postChart(project,chart,'panel-source',section);
    if(version!==panelLoadVersion||project!==state.project||chart!==state.chart)return;
    panelLoadedSource={...section,...result,project,chart};$('panelSource').value=result.content;
    const editable=section.path.startsWith('lib/native/')&&section.path.includes('/code/');
    $('panelSource').readOnly=!editable;$('savePanelSource').disabled=!editable;
    $('panelSourceStatus').textContent=`${section.path}:${section.start_line}–${section.end_line}。`+(editable?'可编辑此段；保存会在当前图入口记录局部修改并重绘，原文件保留。':'此文件作为上下文查看；请在下方整图入口修改。');
  }catch(e){if(version===panelLoadVersion)$('panelSourceStatus').textContent=e.message;}
}
async function savePanelSource(){
  const source=panelLoadedSource;if(!source||source.project!==state.project||source.chart!==state.chart)return;
  if($('panelSource').value===source.content){alertStatus('代码没有变化');return;}
  if($('editor').value!==state.detail.code){alertStatus('整图入口有未保存修改，请先保存再修改子图源码');return;}
  $('savePanelSource').disabled=true;
  try{
    const proposal=await postChart(source.project,source.chart,'panel-edit',{...source,content:$('panelSource').value,base_revision:state.detail.revision});
    const ok=await apply(proposal.code,'手动修改子图绘制代码',proposal.revision);
    if(ok){renderPanelControls();drawPanelSections();}
  }catch(e){alertStatus('局部修改失败：'+e.message);}finally{$('savePanelSource').disabled=false;}
}
