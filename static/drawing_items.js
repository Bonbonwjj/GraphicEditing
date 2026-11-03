let pendingDrawingItem=null,lastDeletedItems=null;
function addDrawingItem(kind){
  if(!state.chart||!stylePreviewData?.axes?.length){alertStatus('请先打开图表并等待交互准备完成');return;}
  const axis=Number((subplotZoomAxis||selectedAxisKey||'axes_0').slice(5));
  if(!subplotZoomAxis&&!selectedAxisKey&&stylePreviewData.axes.length>1){alertStatus('请先点击要添加对象的子图，或进入子图放大窗口');return;}
  const ident=crypto.randomUUID().replace(/-/g,'');
  baseInteractiveStyle.added_items={...(baseInteractiveStyle.added_items||{}),[ident]:{kind,axis,text:kind==='text'?'新建文本':'',x:kind==='text'?.5:.25,y:.5,x2:.75,y2:.5}};
  pendingDrawingItem=ident;scheduleInteractiveStylePreview();
}
function deleteDrawingSelection(){
  const keys=[...componentSelection].filter(key=>/\.(?:line_\d+|annotation_\d+|xlabel|ylabel|title_[012]|legend_text_\d+)$/.test(key));
  if(!keys.length){alertStatus('请先选中文本或线条');return;}
  lastDeletedItems=keys.map(key=>({project:state.project,chart:state.chart,key,spec:{...(baseInteractiveStyle.component_styles?.[key]||{})}}));
  updateComponents('hidden',true,keys);componentSelection.clear();$('componentInspector')?.remove();
}
function undoDrawingDelete(){
  if(!lastDeletedItems||lastDeletedItems[0]?.project!==state.project||lastDeletedItems[0]?.chart!==state.chart){alertStatus('没有待撤销的删除');return;}
  const styles=baseInteractiveStyle.component_styles||{};
  for(const {key,spec}of lastDeletedItems)styles[key]=spec;
  baseInteractiveStyle.component_styles=styles;lastDeletedItems=null;scheduleInteractiveStylePreview();
}
function drawingToolbar(){
  const bar=document.createElement('span');bar.className='drawingItemToolbar';
  for(const [label,action]of [['＋ 文本框',()=>addDrawingItem('text')],['＋ 线条',()=>addDrawingItem('line')],['删除选中文本/线条',deleteDrawingSelection],['撤销删除',undoDrawingDelete],['确认修改',()=>showStyleComparison()]]){
    const button=document.createElement('button');button.type='button';button.textContent=label;button.onclick=action;bar.append(button);
  }return bar;
}
document.querySelector('.galleryToolbar').after(drawingToolbar());
new MutationObserver(()=>{const host=document.querySelector('.subplotZoomToolbar');if(host&&!host.querySelector('.drawingItemToolbar'))host.append(drawingToolbar());}).observe(document.body,{childList:true,subtree:true});
const inspectBeforeDrawingItems=openComponentInspector;
openComponentInspector=function(...args){
  inspectBeforeDrawingItems(...args);
  const key=componentKey(args[3]||'axis'),panel=$('componentInspector');
  if(!key||!panel)return;
  const body=panel.querySelector('.componentInspectorBody');
  if(/\.line_\d+$/.test(key)){
    const row=document.createElement('label'),name=document.createElement('span'),select=document.createElement('select');name.textContent='线型';select.dataset.lineStyle='';
    for(const [value,label]of [['solid','实线'],['dashed','虚线'],['dotted','点线'],['dashdot','点划线']]){const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);}
    select.value=baseInteractiveStyle.component_styles?.[key]?.linestyle||'solid';select.onchange=()=>updateComponents('linestyle',select.value);row.append(name,select);body.prepend(row);
  }
  if(/\.(?:line_\d+|annotation_\d+|xlabel|ylabel|title_[012]|legend_text_\d+)$/.test(key)){
    const remove=document.createElement('button');remove.type='button';remove.textContent='删除选中对象';remove.dataset.deleteDrawingItem='';remove.onclick=deleteDrawingSelection;body.append(remove);
  }
  if(!$('subplotZoomDialog')){panel.style.top=Math.max(8,Math.min(140,window.innerHeight-panel.getBoundingClientRect().height-12))+'px';panel.style.left=Math.max(8,window.innerWidth-panel.getBoundingClientRect().width-16)+'px';}
};
const attachBeforeDrawingItems=attachDirectManipulation;
attachDirectManipulation=function(img,result){
  attachBeforeDrawingItems(img,result);
  if(!pendingDrawingItem)return;
  const text=result.texts?.find(item=>item.added_id===pendingDrawingItem),line=result.targets?.find(item=>item.added_id===pendingDrawingItem),item=text||line;
  if(!item)return;
  pendingDrawingItem=null;
  const image=document.querySelector('#subplotZoomDialog .subplotZoomFrame img')||document.querySelector('.chartCard.active img');
  if(!image)return;
  const axisKey=item.key.split('.')[0];selectSubplot(image,result,axisKey);componentSelection=new Set([item.key]);
  if(text){selectedTextKey=item.key;$('fontSize').value=text.fontsize||12;openComponentInspector({clientX:250,clientY:180},'文本框属性',['fontSize'],'text');}
  else{selectedSeriesKey=item.key;$('lineColor').value=cssColorToHex(line.style?.color)||'#111111';$('useLineColor').checked=true;$('lineWidth').value=line.style?.linewidth??2;openComponentInspector({clientX:250,clientY:180},'新增线条属性',['lineWidth','lineColor','useLineColor'],'line');}
};

document.addEventListener('keydown',event=>{
  if(event.key==='Delete'&&componentSelection.size&&!event.target.closest('input,textarea,select,[contenteditable="true"]')){event.preventDefault();deleteDrawingSelection();}
});
