// Extra properties share the existing candidate/confirmation/history workflow.
let componentSelection=new Set(),componentSelectionChart=null;
let componentDragEnabled=false,componentSelectionMode='group';
function syncComponentInteractionControls(){
  for(const select of document.querySelectorAll('[data-component-interaction]'))select.value=componentDragEnabled?'move':'select';
  for(const select of document.querySelectorAll('[data-component-selection-mode]'))select.value=componentSelectionMode;
  for(const img of document.querySelectorAll('img.directEditable'))img.dataset.dragEnabled=String(componentDragEnabled);
  for(const hint of document.querySelectorAll('[data-component-interaction-hint]'))hint.textContent=componentDragEnabled?'已允许拖动：按住选中对象移动；完成后请切回“仅选择”。':'位置已锁定：点击只选择，双击放大子图；Shift+点击可多选。';
  for(const info of document.querySelectorAll('.componentSelectionInfo'))info.textContent=componentSelectionHint();
}
function syncComponentPreviewStatus(){
  const message=$('stylePreviewState')?.textContent||'';
  for(const status of document.querySelectorAll('[data-component-preview-status]'))status.textContent=message;
}
function componentSelectionHint(){return `已选 ${componentSelection.size} 个组件 · Shift+点击多选；${componentDragEnabled?'已允许拖动。':'位置已锁定，需在操作模式中开启拖动。'}位移单位为 pt，缩放 1 为原大小。`;}
function setComponentInteractionMode(property,value){
  for(const img of document.querySelectorAll('img.directEditable'))img._cancelComponentDrag?.();
  if(property==='drag'){componentDragEnabled=value==='move';drawComponentSelection();}
  else{
    componentSelectionMode=value;componentSelection.clear();$('componentInspector')?.remove();
    const img=document.querySelector('.chartCard.active .chartImage img');
    if(img&&stylePreviewData)attachDirectManipulation(img,stylePreviewData);
    drawComponentSelection();
  }
  syncComponentInteractionControls();
}
function componentInteractionToolbar(){
  const bar=document.createElement('div');bar.className='componentInteractionToolbar';
  bar.innerHTML='<label>操作模式 <select data-component-interaction aria-label="操作模式"><option value="select">仅选择（锁定位置）</option><option value="move">允许拖动</option></select></label><label>选择粒度 <select data-component-selection-mode aria-label="选择粒度"><option value="group">整体（组合图形）</option><option value="part">单个组件（线条 / 主体等）</option><option value="subplot">整个子图（含坐标轴和文字）</option><option value="text">文字 / 子图序号（a、b、c…）</option></select></label><small data-component-interaction-hint></small>';
  bar.querySelector('[data-component-interaction]').onchange=event=>setComponentInteractionMode('drag',event.target.value);
  bar.querySelector('[data-component-selection-mode]').onchange=event=>setComponentInteractionMode('selection',event.target.value);
  const status=document.createElement('span');status.dataset.componentPreviewStatus='';status.className='componentPreviewStatus';status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.textContent=$('stylePreviewState')?.textContent||'';bar.append(status);
  return bar;
}
document.querySelector('.galleryToolbar').after(componentInteractionToolbar());
syncComponentInteractionControls();
new MutationObserver(syncComponentPreviewStatus).observe($('stylePreviewState'),{childList:true,subtree:true,characterData:true});
const selectBeforeInteractionMode=select;
select=async function(...args){setComponentInteractionMode('drag','select');return selectBeforeInteractionMode(...args);};
function componentKey(scope){
  if(scope==='text')return selectedTextKey;
  if(scope==='line')return selectedSeriesKey;
  if(scope==='spine')return selectedSpineKey;
  if(scope==='axis')return selectedAxisKey;
  return null;
}
function statisticalGroupForMember(key){return stylePreviewData?.component_groups?.find(group=>(group.members||[]).includes(key)||(group.part_targets||[]).some(part=>part.key===key));}
function componentColorHex(value){
  if(Array.isArray(value)){const rgba=Array.isArray(value[0])?value[0]:value;return rgba.length>=3?'#'+rgba.slice(0,3).map(v=>Math.round(v*255).toString(16).padStart(2,'0')).join(''):null;}
  return cssColorToHex(value);
}
function componentRgba(value){const color=Array.isArray(value?.[0])?value[0]:value;return Array.isArray(color)&&color.length>=3?color:null;}
function pointTargetForKey(key){return stylePreviewData?._rawTargets?.find(target=>target.key===key&&target.point_role);}
function buildConnectionGroups(result){
  const targets=result._rawTargets||result.targets||[],clouds=new Map(),means=[],meanOwners=new Set();
  const reported=new Map();
  for(const target of targets)if(target.connection_members?.length>1){const members=[...target.connection_members].sort();reported.set(members.join('|'),{axis:target.key.match(/^axes_\d+/)?.[0],members});}
  if(reported.size)return [...reported.values()];
  const axisOf=key=>String(key||'').match(/^axes_\d+/)?.[0];
  const pad=Math.max(3,(result.dpi||100)*4/72),epsilon=Math.max(.8,(result.dpi||100)/300);
  for(const target of targets){
    if(target.point_role==='mean'){meanOwners.add(target.owner_key);means.push(target);continue;}
    if(!['regular','outliers'].includes(target.point_role))continue;
    const group=target.point_group||target.owner_key;if(!group)continue;
    if(!clouds.has(group))clouds.set(group,{id:group,axis:axisOf(target.key),points:[],box:[Infinity,Infinity,-Infinity,-Infinity]});
    const cloud=clouds.get(group);
    for(const point of target.hit_path_px||[]){if(!point.every(Number.isFinite))continue;cloud.points.push(point);cloud.box=[Math.min(cloud.box[0],point[0]),Math.min(cloud.box[1],point[1]),Math.max(cloud.box[2],point[0]),Math.max(cloud.box[3],point[1])];}
  }
  const orientations=new Map();
  for(const axis of new Set([...clouds.values()].map(cloud=>cloud.axis))){
    const peers=[...clouds.values()].filter(cloud=>cloud.axis===axis),centers=peers.map(cloud=>[(cloud.box[0]+cloud.box[2])/2,(cloud.box[1]+cloud.box[3])/2]);
    const score=dimension=>{const values=centers.map(point=>point[dimension]),spread=peers.reduce((sum,cloud)=>sum+cloud.box[dimension+2]-cloud.box[dimension],0)/peers.length;return(Math.max(...values)-Math.min(...values))/(spread+epsilon);};
    orientations.set(axis,score(0)>=score(1));
  }
  const statMembers=new Set((result.component_groups||[]).flatMap(group=>[...(group.members||[]),...(group.part_targets||[]).map(part=>part.key)]));
  const candidates=[];
  for(const target of targets){
    const path=target.hit_path_px||[],axis=axisOf(target.key);
    if(target.kind!=='line'||target.added_id||target.group_key||statMembers.has(target.key)||meanOwners.has(target.key)||path.length<2||path.length>32)continue;
    if(path.length===4&&path[0][0]===path[1][0]&&path[2][0]===path[3][0]&&path[1][1]===path[2][1])continue;
    const meanColor=componentColorHex(target.style?.color);
    const matchingMeans=means.filter(item=>axisOf(item.key)===axis&&componentColorHex(item.style?.fill_color)===meanColor);
    if(matchingMeans.length&&path.every(p=>matchingMeans.some(item=>(item.hit_path_px||[]).some(m=>Math.hypot(p[0]-m[0],p[1]-m[1])<=epsilon))))continue;
    const groups=[];
    for(const point of path){
      let matched=null,best=Infinity;
      for(const cloud of clouds.values()){
        if(cloud.axis!==axis)continue;const [x0,y0,x1,y1]=cloud.box;
        const vertical=orientations.get(axis)&&point[0]>=x0-pad&&point[0]<=x1+pad,horizontal=!orientations.get(axis)&&point[1]>=y0-pad&&point[1]<=y1+pad;
        if(!vertical&&!horizontal)continue;
        for(const observed of cloud.points){
          const distance=Math.min(vertical?Math.abs(point[1]-observed[1]):Infinity,horizontal?Math.abs(point[0]-observed[0]):Infinity);
          if(distance<=epsilon&&distance<best){best=distance;matched=cloud.id;}
        }
      }
      if(matched===null){groups.length=0;break;}groups.push(matched);
    }
    if(new Set(groups).size<2)continue;
    const label=typeof target.label==='string'&&!target.label.startsWith('_')?target.label:'';
    candidates.push({key:target.key,axis,groups:new Set(groups),label,color:componentColorHex(target.style?.color)||JSON.stringify(target.style?.color)});
  }
  const namedColors=new Map();
  for(const candidate of candidates)if(candidate.label){const key=JSON.stringify([candidate.axis,candidate.color]);if(!namedColors.has(key))namedColors.set(key,new Set());namedColors.get(key).add(candidate.label);}
  const families=[];
  for(const candidate of candidates){
    const labels=namedColors.get(JSON.stringify([candidate.axis,candidate.color]));
    const cohort=candidate.label||(labels?.size===1?[...labels][0]:'');
    const matches=families.filter(group=>group.axis===candidate.axis&&group.cohort===cohort&&[...candidate.groups].some(key=>group.groups.has(key)));
    const family=matches[0]||{axis:candidate.axis,cohort,groups:new Set(),members:[]};
    if(!matches.length)families.push(family);
    for(const other of matches.slice(1)){for(const key of other.groups)family.groups.add(key);family.members.push(...other.members);families.splice(families.indexOf(other),1);}
    for(const key of candidate.groups)family.groups.add(key);family.members.push(candidate.key);
  }
  return families.filter(group=>group.members.length>1).map(group=>({axis:group.axis,members:group.members}));
}
function connectionGroupForMember(key){return stylePreviewData?._connectionGroups?.find(group=>group.members.includes(key));}
function componentMarkerPath(points,shape,radius,height){
  return points.map(([x,rawY])=>{
    const y=height-rawY,r=shape==='.'?radius*.5:radius;
    if(shape==='o'||shape==='.')return `M${x-r},${y}a${r},${r} 0 1,0 ${2*r},0a${r},${r} 0 1,0 ${-2*r},0Z`;
    if(shape==='+')return `M${x-r},${y}h${2*r}M${x},${y-r}v${2*r}`;
    if(shape==='x')return `M${x-r},${y-r}l${2*r},${2*r}M${x-r},${y+r}l${2*r},${-2*r}`;
    let vertices={s:[[-1,-1],[1,-1],[1,1],[-1,1]],D:[[0,-1],[1,0],[0,1],[-1,0]],d:[[0,-1],[.6,0],[0,1],[-.6,0]],
      '^':[[0,-1],[1,1],[-1,1]],v:[[-1,-1],[1,-1],[0,1]],'<':[[1,-1],[1,1],[-1,0]],'>':[[-1,-1],[1,0],[-1,1]],
      P:[[-.33,-1],[.33,-1],[.33,-.33],[1,-.33],[1,.33],[.33,.33],[.33,1],[-.33,1],[-.33,.33],[-1,.33],[-1,-.33],[-.33,-.33]],
      X:[[-1,-.6],[-.6,-1],[0,-.4],[.6,-1],[1,-.6],[.4,0],[1,.6],[.6,1],[0,.4],[-.6,1],[-1,.6],[-.4,0]]}[shape];
    if(!vertices)vertices=Array.from({length:10},(_,i)=>{const a=-Math.PI/2+i*Math.PI/5,k=i%2?.4:1;return[Math.cos(a)*k,Math.sin(a)*k];});
    return vertices.map(([px,py],i)=>`${i?'L':'M'}${x+px*r},${y+py*r}`).join('')+'Z';
  }).join('');
}
function offlineComponentPreview(property,value,keys){
  if(!['color','fill_color','edge_color','linewidth','alpha','fill_alpha','edge_alpha','marker_shape','marker_size'].includes(property)||!stylePreviewData?.render_size_px)return;
  const img=document.querySelector('#subplotZoomDialog .subplotZoomFrame img')||document.querySelector('.chartCard.active .chartImage img');if(!img)return;
  const host=img.parentElement,rect=chartImageRect(img),hostRect=host.getBoundingClientRect(),size=stylePreviewData.render_size_px;
  let svg=host.querySelector('svg.offlineComponentPreview');
  if(!svg){svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('offlineComponentPreview');svg.setAttribute('aria-hidden','true');svg.style.cssText='position:absolute;pointer-events:none;z-index:5';host.append(svg);}
  svg.style.left=(rect.left-hostRect.left)+'px';svg.style.top=(rect.top-hostRect.top)+'px';svg.style.width=rect.width+'px';svg.style.height=rect.height+'px';svg.setAttribute('viewBox',`0 0 ${size[0]} ${size[1]}`);svg.setAttribute('preserveAspectRatio','none');
  const expanded=new Set(keys.flatMap(key=>stylePreviewData.component_groups?.find(group=>group.key===key)?.members||[key]));
  for(const target of stylePreviewData._rawTargets||stylePreviewData.targets||[]){
    const groupKey=keys.find(key=>{const group=stylePreviewData.component_groups?.find(group=>group.key===key);return group?.members?.includes(target.key)||(target.point_role&&group?.locked_selection&&group?.members?.includes(target.owner_key));});
    const pointOwner=target.point_role&&(keys.includes(target.owner_key)||groupKey);
    if((!expanded.has(target.key)&&!pointOwner)||!(target.hit_path_px||[]).length)continue;
    const id='offline-'+target.key.replace(/[^a-zA-Z0-9_-]/g,'-'),old=svg.querySelector('#'+id);old?.remove();
    const path=document.createElementNS('http://www.w3.org/2000/svg','path'),points=target.hit_path_px;
    path.id=id;path.setAttribute('d',points.map((point,index)=>(index?'L':'M')+point[0]+' '+(size[1]-point[1])).join(' '));
    const inherited={...(groupKey?baseInteractiveStyle.component_styles?.[groupKey]:pointOwner?baseInteractiveStyle.component_styles?.[target.owner_key]:{})};
    if(target.point_role&&groupKey){delete inherited.fill_alpha;delete inherited.fill_color;}
    const effective={...inherited,...(baseInteractiveStyle.component_styles?.[target.key]||{})};
    if(target.point_role){
      const rendered=target.style||{},face=componentRgba(rendered.fill_color),hollow=face&&(face[3]===0||face.slice(0,3).every(c=>c>.999));
      path.setAttribute('d',componentMarkerPath(points,effective.marker_shape||rendered.marker_shape||'o',(effective.marker_size??rendered.marker_size??6)*(stylePreviewData.dpi||96)/144,size[1]));
      path.setAttribute('fill',effective.fill_color||(!hollow&&effective.color)||componentColorHex(rendered.fill_color)||'none');
      path.setAttribute('stroke',effective.edge_color||effective.color||componentColorHex(rendered.edge_color)||'#111');
      path.setAttribute('stroke-width',(effective.linewidth??rendered.linewidth??1)*(stylePreviewData.dpi||96)/72);
      path.setAttribute('fill-opacity',effective.fill_alpha??effective.alpha??face?.[3]??1);
      path.setAttribute('stroke-opacity',effective.edge_alpha??effective.alpha??componentRgba(rendered.edge_color)?.[3]??1);
      svg.append(path);continue;
    }
    const patch=target.kind==='patch'||target.kind==='heatmap';
    if(patch){path.setAttribute('fill',effective.color||effective.fill_color||componentColorHex(target.style?.facecolor)||'none');path.setAttribute('stroke',effective.edge_color||'none');path.setAttribute('fill-opacity',effective.fill_alpha??effective.alpha??componentRgba(target.style?.facecolor)?.[3]??1);}
    else{path.setAttribute('fill','none');path.setAttribute('stroke',effective.color||effective.edge_color||componentColorHex(target.style?.color)||'#111');path.setAttribute('stroke-width',Math.max(.5,(effective.linewidth??target.style?.linewidth??1)*(stylePreviewData.dpi||96)/72));path.setAttribute('stroke-linejoin','round');path.setAttribute('stroke-linecap','round');path.setAttribute('stroke-opacity',effective.edge_alpha??effective.alpha??1);}
    svg.append(path);
  }
  $('stylePreviewState').textContent='已在本地即时预览，后台正在校准图例和正式渲染…';
}
function updateComponents(property,value,keys=[...componentSelection]){
  if(['dx','dy'].includes(property))keys=componentMovementKeys(stylePreviewData,keys);
  const styles=baseInteractiveStyle.component_styles||{};
  if(['color','linewidth','linestyle','alpha'].includes(property))keys=[...new Set(keys.flatMap(key=>{
    const group=connectionGroupForMember(key);if(!group)return [key];
    // A Line2D may own both the stroke and its markers. Keep marker styling
    // unchanged while updating the connecting stroke through existing APIs.
    for(const point of stylePreviewData._rawTargets||[]){
      if(!point.point_role||!group.members.includes(point.owner_key))continue;
      const rendered=point.style||{},keep={};
      if(property==='color'||property==='alpha'){
        for(const [field,alpha]of [['fill_color','fill_alpha'],['edge_color','edge_alpha']]){
          if(property==='color'){const hex=componentColorHex(rendered[field]);if(hex)keep[field]=hex;}
          if(rendered[field]?.length===4)keep[alpha]=rendered[field][3];
        }
      }
      if(property==='linewidth'&&rendered.linewidth!=null)keep.linewidth=rendered.linewidth;
      if(Object.keys(keep).length)styles[point.key]={...keep,...(styles[point.key]||{})};
    }
    for(const member of group.members)if(styleSeriesStyles[member]&&['color','linewidth'].includes(property))delete styleSeriesStyles[member][property];
    return group.members;
  }))];
  const pointScope=$('componentInspector')?.querySelector('[data-point-scope]')?.value;
  if(pointScope&&pointScope!=='one')keys=[...new Set(keys.flatMap(key=>{
    const point=pointTargetForKey(key);if(!point)return [key];
    const group=point.point_group||point.owner_key;
    return (stylePreviewData._rawTargets||[]).filter(target=>target.point_role&&(target.point_group||target.owner_key)===group
      &&(pointScope==='group_all'?['regular','outliers'].includes(target.point_role):pointScope==='group_outliers'?target.point_role==='outliers':target.point_role==='mean')).map(target=>target.key);
  }))];
  const scope=$('componentInspector')?.querySelector('[data-axis-color-scope]')?.value;
  if(['color','alpha'].includes(property)&&scope==='axis'&&selectedTextKey){const match=selectedTextKey.match(/^(axes_\d+)\.([xy])tick_/);if(match){const prefix=match[1]+'.'+match[2];for(const [key,spec]of Object.entries(styles))if(key.startsWith(prefix+'tick_'))delete spec[property];keys=[prefix+'axis_text'];}}
  if(property==='scale'&&keys.some(key=>key.includes('.spine_'))){for(const key of keys){if(key.includes('.spine_')){const [axis,side]=key.split('.spine_');styles[axis]={...(styles[axis]||{}),[side==='left'||side==='right'?'y_scale':'x_scale']:value};if(styles[key])delete styles[key].scale;}else styles[key]={...(styles[key]||{}),scale:value};}baseInteractiveStyle.component_styles=styles;scheduleInteractiveStylePreview();return;}
  for(const key of keys){
    const group=stylePreviewData?.component_groups?.find(item=>item.key===key);
    const fillOnly=property==='color'&&/\.(?:box|violin)_\d+$/.test(key),field=fillOnly?'fill_color':property;
    // A new group edit supersedes earlier edits to that same property on its
    // members. Keep unrelated individual properties (fill, size, position, etc.).
    if(group){
      const conflicts=fillOnly?['fill_color']:property==='color'?['color','fill_color','edge_color']:property==='alpha'?['alpha','fill_alpha','edge_alpha']:[property];
      const members=new Set([...(group.members||[]),...(group.part_targets||[]).map(part=>part.key)]);
      for(const member of members)for(const item of Object.keys(styles))if(item===member||item.startsWith(member+'.points_'))for(const field of conflicts)delete styles[item][field];
      if(property==='color'&&styles[key]){if(fillOnly)delete styles[key].color;else{delete styles[key].fill_color;delete styles[key].edge_color;}}
    }
    if(value===undefined){if(styles[key]){delete styles[key][field];if(!Object.keys(styles[key]).length)delete styles[key];}}
    else styles[key]={...(styles[key]||{}),[field]:value};
    // Line strokes and cap markers must both override an inherited group edge.
    if(property==='color'&&(key.includes('.line_')||key.includes('.segment_'))&&statisticalGroupForMember(key))styles[key].edge_color=value;
  }
  baseInteractiveStyle.component_styles=styles;
  offlineComponentPreview(property,value,keys);
  const geometric=new Set(['dx','dy','scale','x_scale','y_scale','width_scale','xlim','ylim']);
  scheduleInteractiveStylePreview(!geometric.has(property));
}
function componentEditableFeatures(targets){
  const marker=targets.some(target=>target.point_role||target.kind==='scatter'||
    (target.kind==='line'&&!['', 'none', 'null'].includes(String(target.style?.marker??'none').toLowerCase())));
  return {
    fill:targets.some(target=>['patch','polygon_collection','scatter'].includes(target.kind)&&!target.key?.includes('.segment_')),
    stroke:targets.some(target=>['line','line_collection','patch','polygon_collection','scatter'].includes(target.kind)),
    marker
  };
}
const openBasicInspector=openComponentInspector;
openComponentInspector=function(event,title,ids,scope='axis'){
  if(scope==='text'&&selectedTextKey?.startsWith('figure.text_'))ids=[];
  const selectedPoint=scope==='line'&&pointTargetForKey(selectedSeriesKey);
  if(selectedPoint){title=selectedPoint.label+'属性';ids=[];}
  const selectedConnection=scope==='line'&&connectionGroupForMember(selectedSeriesKey);
  if(selectedConnection){title='散点连线组属性';ids=[];}
  const selectedGroup=scope==='line'&&stylePreviewData?.component_groups?.find(group=>group.key===selectedSeriesKey);
  const selectedTargets=(selectedGroup?.members||[selectedSeriesKey]).map(key=>
    stylePreviewData?._rawTargets?.find(target=>target.key===key)||selectedGroup?.part_targets?.find(target=>target.key===key)).filter(Boolean);
  const features=componentEditableFeatures(selectedTargets);
  if(scope==='line'&&!features.marker)ids=ids.filter(id=>id!=='markerSize');
  if(selectedGroup)title='整个'+selectedGroup.label+'属性';
  const memberGroup=scope==='line'&&statisticalGroupForMember(selectedSeriesKey);
  if(memberGroup)ids=[];
  else if(scope==='line'&&selectedSeriesKey&&!selectedSeriesKey.includes('.line_'))ids=ids.filter(id=>id==='markerSize'&&!selectedGroup);
  openBasicInspector(event,title,ids,scope);
  if(scope==='text'){const row=$('componentInspector').querySelector('input[type=number]')?.closest('label');if(row)row.querySelector('span').textContent='当前文字字号';}
  const chart=state.project+'/'+state.chart,key=title==='图例属性'&&selectedAxisKey?selectedAxisKey+'.legend':componentKey(scope)||(scope==='axis'?selectedAxisKey:null);
  if(componentSelectionChart!==chart){componentSelection.clear();componentSelectionChart=chart;}
  if(!key){componentSelection.clear();return;}
  if(event.shiftKey){if(componentSelection.has(key))componentSelection.delete(key);else componentSelection.add(key);}
  else if(!componentSelection.has(key)||componentSelection.size===1)componentSelection=new Set([key]);
  const panel=$('componentInspector'),body=panel.querySelector('.componentInspectorBody');
  const info=document.createElement('small');info.className='componentSelectionInfo';
  info.textContent=componentSelectionHint();
  body.append(info);
  const spec=baseInteractiveStyle.component_styles?.[key]||{};
  const add=(name,property,type='number',initial='',constraints={},targetKeys=null)=>{
    const row=document.createElement('label'),label=document.createElement('span'),input=document.createElement(type==='multiline'?'textarea':'input');
    label.textContent=name;if(type!=='multiline')input.type=type;else input.rows=3;input.dataset.componentProp=property;
    input.value=spec[property]??initial;for(const [attr,val]of Object.entries(constraints))input.setAttribute(attr,val);
    input.addEventListener('input',()=>{
      if(type==='number'&&(input.value===''||!input.validity.valid))return;
      updateComponents(property,type==='number'?Number(input.value):input.value,targetKeys||undefined);
    });row.append(label,input);body.append(row);return input;
  };
  const isText=scope==='text',isArtist=scope==='line';
  if(isText){
    const rendered=stylePreviewData?.texts?.find(item=>item.key===key);
    if(key.startsWith('figure.text_'))add('文字字号','font_size','number',rendered?.fontsize||12,{min:1,max:200,step:.5});
    if(/\.([xy])tick_/.test(key)){
      const row=document.createElement('label'),label=document.createElement('span'),select=document.createElement('select');
      label.textContent='颜色应用范围';select.dataset.axisColorScope='';
      for(const [value,text]of [['one','仅该刻度'],['axis',key.includes('.x')?'所有 X 轴刻度':'所有 Y 轴刻度']]){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}
      select.onchange=()=>{const color=body.querySelector('[data-component-prop=color]');if(color)updateComponents('color',color.value);};row.append(label,select);body.append(row);
    }
    const match=key.match(/^(axes_\d+)\.([xy])tick_/),axisColor=match?baseInteractiveStyle.component_styles?.[match[1]+'.'+match[2]+'axis_text']?.color:null;
    add('文字颜色','color','color',axisColor||'#111111');
    add('字体名称','font_family','text','DejaVu Sans');
    // Existing label/title fields retain their original handlers. Generic text gets a content field.
    if(!ids.some(id=>['quickTitle','quickXLabel','quickYLabel'].includes(id)))add('文字内容','text','multiline',rendered?.text||'');
  }
  const linePart=!selectedPoint&&memberGroup&&(key.includes('.line_')||key.includes('.segment_'));
  if(isArtist&&selectedConnection){
    const rendered=stylePreviewData._rawTargets.find(item=>item.key===key)?.style||{};
    add('连线颜色','color','color',componentColorHex(rendered.color)||'#777777');
    add('连线粗细','linewidth','number',rendered.linewidth??1,{min:0,max:50,step:.25});
    const row=document.createElement('label'),label=document.createElement('span'),select=document.createElement('select');
    label.textContent='连线线型';select.dataset.componentProp='linestyle';
    for(const [value,text]of [['-','实线'],['--','虚线'],['-.','点划线'],[':','点线']]){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}
    select.value=spec.linestyle??rendered.linestyle??'-';select.onchange=()=>updateComponents('linestyle',select.value);row.append(label,select);body.append(row);
    const note=document.createElement('small');note.dataset.connectionGroupInfo='';note.textContent=`同组 ${selectedConnection.members.length} 条连线的颜色、粗细、线型和透明度将一起更新。`;body.append(note);
  }
  if(isArtist&&selectedPoint){
    const rendered=selectedPoint.style||{},row=document.createElement('label'),label=document.createElement('span'),select=document.createElement('select');
    label.textContent='修改范围';select.dataset.pointScope='';
    const options=selectedPoint.point_role==='mean'?[['one','仅当前均值点'],['group_mean','该组均值点']]:[
      ['group_all','该组所有散点'],['group_outliers','仅该组离群散点']];
    for(const [value,text]of options){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}
    if(selectedPoint.point_role==='outliers')select.value='group_outliers';
    row.append(label,select);body.append(row);
    const shapeRow=document.createElement('label'),shapeLabel=document.createElement('span'),shape=document.createElement('select');
    shapeLabel.textContent='点的形状';shape.dataset.componentProp='marker_shape';
    for(const [value,text]of [['','保持原形状'],['o','圆形'],['s','正方形'],['D','菱形'],['d','窄菱形'],['^','上三角'],['v','下三角'],['<','左三角'],['>','右三角'],['P','实心加号'],['X','实心叉号'],['+','加号'],['x','叉号'],['*','星形'],['.','小圆点']]){const option=document.createElement('option');option.value=value;option.textContent=text;shape.append(option);}
    shape.value=spec.marker_shape??rendered.marker_shape??'';
    shape.onchange=()=>{updateComponents('marker_shape',shape.value||undefined);syncPointFill();};shapeRow.append(shapeLabel,shape);body.append(shapeRow);
    const fill=add('点填充色','fill_color','color',componentColorHex(rendered.fill_color)||'#111111');
    const syncPointFill=()=>{fill.closest('label').hidden=['+','x','1','2','3','4','|','_'].includes(shape.value||rendered.marker_shape);};syncPointFill();
    const edge=add('点边框色','edge_color','color',componentColorHex(rendered.edge_color)||'#111111');
    if(fill&&rendered.fill_color?.length===4)fill.dataset.renderedAlpha=rendered.fill_color[3];
    if(rendered.edge_color?.length===4)edge.dataset.renderedAlpha=rendered.edge_color[3];
    add('点大小 pt','marker_size','number',rendered.marker_size??6,{min:0,max:100,step:.5});
    add('点边框粗细','linewidth','number',rendered.linewidth??1,{min:0,max:50,step:.25});
    const note=document.createElement('small');note.dataset.pointClassification='';note.textContent=(selectedPoint.point_group_label?'当前组：'+selectedPoint.point_group_label+'。':'')+'修改只作用于当前组，其他组保持不变。'+(selectedPoint.rule==='display_iqr'?'离群点按同组样本的 1.5×IQR 区分，仅用于编辑分组，不删除数据。':'均值点独立编辑。');body.append(note);
  }
  if(isArtist&&componentSelectionMode==='group'&&!selectedGroup&&!selectedPoint&&!selectedConnection){const note=document.createElement('small');note.dataset.componentGroupStatus='';note.textContent='当前为独立组件，未识别到可靠的组合分组。';body.append(note);}
  if(isArtist&&linePart&&!selectedConnection){
    const rendered=stylePreviewData?._rawTargets?.find(item=>item.key===key)?.style||{};
    add('线条颜色','color','color',componentColorHex(rendered.color)||'#111111');
    add('线条粗细','linewidth','number',rendered.linewidth??'',{min:0,max:50,step:.25});
    if(features.marker&&!key.includes('.segment_'))add('标记大小 pt','marker_size','number',rendered.markersize??'',{min:0,max:100,step:.5});
  }
  if(isArtist&&!selectedPoint&&!selectedConnection&&!key.includes('.line_')&&!key.includes('.image_')&&!linePart){
    const renderedStyles=(selectedGroup?.members||[key]).map(member=>stylePreviewData?._rawTargets?.find(target=>target.key===member)?.style).filter(Boolean);
    const fillRgba=renderedStyles.map(style=>componentRgba(style.facecolor)).find(Boolean),edgeRgba=renderedStyles.map(style=>componentRgba(style.edgecolor)).find(Boolean);
    const linkedBand=selectedGroup?.locked_selection&&selectedGroup?.linked_properties?.includes('color');
    if(linkedBand){
      const stroke=renderedStyles.map(style=>componentColorHex(style.color)).find(Boolean)||componentColorHex(fillRgba)||'#1f77b4';
      const color=add('线段与填充区域颜色','color','color',stroke);color.dataset.skipOpacity='true';
      add('填充区域不透明度（0～1）','fill_alpha','number',fillRgba?.[3]??.2,{min:0,max:1,step:.05});
      const lineKey=(selectedGroup.members||[]).find(member=>stylePreviewData?._rawTargets?.find(target=>target.key===member)?.kind==='line');
      const lineStyle=stylePreviewData?._rawTargets?.find(target=>target.key===lineKey)?.style||{};
      if(lineKey)add('中心线粗细','linewidth','number',lineStyle.linewidth??1,{min:0,max:50,step:.25},[lineKey]);
      const seriesPoint=(stylePreviewData._rawTargets||[]).find(point=>point.point_role&&selectedGroup.members.includes(point.owner_key));
      if(seriesPoint){
        const row=document.createElement('label'),label=document.createElement('span'),shape=document.createElement('select');
        label.textContent='该组全部均值点形状';shape.dataset.componentProp='marker_shape';
        for(const [value,text]of [['o','圆点'],['s','方形'],['D','菱形'],['^','上三角'],['v','下三角'],['<','左三角'],['>','右三角'],['P','实心加号'],['X','实心叉号'],['+','加号'],['x','叉号'],['*','星形'],['.','小圆点']]){const option=document.createElement('option');option.value=value;option.textContent=text;shape.append(option);}
        shape.value=spec.marker_shape??seriesPoint.style?.marker_shape??'o';shape.onchange=()=>updateComponents('marker_shape',shape.value);row.append(label,shape);body.append(row);
      }
      const note=document.createElement('small');note.dataset.linkedBandInfo='';note.textContent='该组线条、阴影和均值点边框颜色联动；空心点保留白色或透明填充。形状修改作用于该组全部均值点，其他组保持不变。';body.append(note);
    }else{
      if(selectedGroup)add(key.includes('.box_')||key.includes('.violin_')?'组别填充色':'整体颜色','color','color','#111111');
      const fill=features.fill?add(key.includes('.box_')?'箱体填充色':key.includes('.violin_')?'小提琴主体填充色':'填充色','fill_color','color',componentColorHex(fillRgba)||'#1f77b4'):null;
      const edge=features.stroke?add(key.includes('.box_')?'整体边框颜色（箱体、须线、端帽、中位线）':selectedGroup?'整体边框 / 统计线颜色':features.fill?'边框颜色':'线条颜色','edge_color','color',componentColorHex(edgeRgba)||componentColorHex(renderedStyles[0]?.color)||'#111111'):null;
      if(fill&&fillRgba?.length===4)fill.dataset.renderedAlpha=fillRgba[3];
      if(edge&&edgeRgba?.length===4)edge.dataset.renderedAlpha=edgeRgba[3];
    }
    if(key.includes('.box_')){const note=document.createElement('small');note.textContent='当前选中一个完整箱型；移动时对应散点、配对连线端点、组别刻度及标签一起跟随。整体边框修改会覆盖其中各条线之前的边框设置，填充色单独控制。';body.append(note);}
    if(key.includes('.box_'))add('箱体胖瘦倍数','width_scale','number',1,{min:.05,max:20,step:.05});
    if(key.includes('.violin_')){const note=document.createElement('small');note.textContent='当前选中一个完整小提琴：主体、极值线、均值/中位线及分位线一起编辑。';body.append(note);add('小提琴胖瘦倍数','width_scale','number',1,{min:.05,max:20,step:.05});}
    if(key.includes('.mean_error_')&&features.marker)add('均值点直径 pt','marker_size','number',10,{min:0,max:100,step:.5});
    if(!linkedBand&&features.stroke)add('边框 / 线条粗细','linewidth','number','',{min:0,max:50,step:.25});
  }
  if(scope==='axis'||scope==='spine'){
    const ai=Number(key.match(/^axes_(\d+)/)[1]),axisKey='axes_'+ai,axis=stylePreviewData?.axis_ranges?.[ai];
    for(const dimension of ['x','y']){
      const addTick=(name,property,initial)=>{const row=document.createElement('label'),label=document.createElement('span'),input=document.createElement('input');label.textContent=name;input.type='number';input.min=0;input.max=100;input.step=.5;input.value=baseInteractiveStyle.component_styles?.[axisKey]?.[property]??initial;input.dataset.tickProperty=property;input.oninput=()=>{if(input.value!==''&&input.validity.valid)updateComponents(property,Number(input.value),[axisKey]);};row.append(label,input);body.append(row);};
      addTick(dimension.toUpperCase()+' 轴小刻度线长度 pt',dimension+'_tick_length',4);
      addTick(dimension.toUpperCase()+' 轴小刻度线粗细 pt',dimension+'_tick_width',1);
      const values=baseInteractiveStyle.component_styles?.[axisKey]?.[dimension+'lim']||axis?.[dimension+'lim'];
      const ticks=stylePreviewData?.axes?.[ai]?.tick_texts?.[dimension==='x'?0:1]||[];
      if(!values||ticks.some(text=>text.trim()!==''&&!Number.isFinite(Number(text.replace(/−/g,'-')))))continue;
      const row=document.createElement('label'),label=document.createElement('span');label.textContent=dimension.toUpperCase()+' 轴范围';row.append(label);
      const inputs=values.map(v=>{const input=document.createElement('input');input.type='number';input.step='any';input.value=v;input.dataset.axisRange=dimension;row.append(input);return input;});
      for(const input of inputs)input.addEventListener('input',()=>{const pair=inputs.map(i=>Number(i.value));if(inputs.some(i=>i.value===''||!i.validity.valid)||pair[0]===pair[1])return;updateComponents(dimension+'lim',pair,[axisKey]);});body.append(row);
    }
  }
  add('水平位移 pt','dx','number',0,{step:1,min:-5000,max:5000});
  add('垂直位移 pt','dy','number',0,{step:1,min:-5000,max:5000});
  const side=key.split('.spine_')[1],axisKey=key.split('.')[0],axisScale=side?baseInteractiveStyle.component_styles?.[axisKey]?.[side==='left'||side==='right'?'y_scale':'x_scale']:null;
  add(side?(side==='left'||side==='right'?'Y 轴及图形纵向缩放倍数':'X 轴及图形横向缩放倍数'):'统一缩放倍数','scale','number',axisScale??1,{step:.05,min:.05,max:20});
  drawComponentSelection();
  const reset=document.createElement('button');reset.type='button';reset.textContent='清除多选，保留当前组件';reset.onclick=()=>{componentSelection=new Set([key]);drawComponentSelection();info.textContent='已选 1 个组件 · '+key;};body.append(reset);
  panel.querySelector('strong').textContent=componentSelection.size>1?`批量编辑 ${componentSelection.size} 个组件`:title;
  addRgbColorControls(panel);
  panel.style.top=Math.max(8,Math.min(event.clientY+12,window.innerHeight-panel.getBoundingClientRect().height-12))+'px';
  panel.style.left=Math.max(8,Math.min(event.clientX+12,window.innerWidth-panel.getBoundingClientRect().width-12))+'px';
};
const attachBasicManipulation=attachDirectManipulation;
function componentSelectionBounds(result,key){
  let box=result.component_groups?.find(item=>item.key===key)?.bbox||result.texts?.find(item=>item.key===key)?.bbox;
  const target=(result._rawTargets||result.targets||[]).find(item=>item.key===key);
  if(!box&&target?.hit_path_px?.length){
    const xs=target.hit_path_px.map(p=>p[0]),ys=target.hit_path_px.map(p=>p[1]),radius=target.point_role?(target.style?.marker_size||6)*(result.dpi||100)/144:0;
    box=[Math.min(...xs)-radius,Math.min(...ys)-radius,Math.max(...xs)+radius,Math.max(...ys)+radius];
  }
  if(!box&&/^axes_\d+$/.test(key)){
    box=result.axes?.[Number(key.slice(5))]?.bbox_px;
    const labels=(result.texts||[]).filter(text=>text.subplot_key===key).map(text=>text.bbox);
    if(box&&labels.length){const boxes=[box,...labels];box=[Math.min(...boxes.map(b=>b[0])),Math.min(...boxes.map(b=>b[1])),Math.max(...boxes.map(b=>b[2])),Math.max(...boxes.map(b=>b[3]))];}
  }
  if(!box&&key.includes('.spine_'))box=result.axes?.[Number(key.match(/^axes_(\d+)/)[1])]?.spines?.[key.split('.spine_')[1]];
  if(!box&&key.endsWith('.legend'))box=result.legends?.find(item=>item.key===key)?.bbox;
  return box;
}
function componentMovementKeys(result,keys){
  const targets=result._rawTargets||result.targets||[],lookup=new Map(targets.map(target=>[target.key,target]));
  return [...new Set(keys.flatMap(key=>{
    const target=lookup.get(key);if(!target)return [key];
    const peers=target.point_move_members||(['regular','outliers'].includes(target.point_role)?targets.filter(peer=>['regular','outliers'].includes(peer.point_role)&&peer.point_group===target.point_group&&peer.point_group).map(peer=>peer.key):[]);
    return [key,...peers,...(target.move_connection_members||[])];
  }))];
}
function componentDragKeys(result,keys){
  keys=componentMovementKeys(result,keys);
  const axes=new Set(keys.filter(key=>/^axes_\d+$/.test(key)));
  return keys.filter(key=>axes.has(key)||!axes.has(result.texts?.find(t=>t.key===key)?.subplot_key||key.match(/^axes_\d+/)?.[0]));
}
function componentPendingDragOffset(img,key){
  const current=baseInteractiveStyle.component_styles?.[key]||{},rendered=img._componentRenderedOffsets?.[key]||{};
  return [(current.dx||0)-(rendered.dx||0),(current.dy||0)-(rendered.dy||0)];
}
function componentSelectedDragHit(img,result,event){
  if(!componentSelection.size||event.shiftKey)return false;
  const rect=chartImageRect(img),size=result.render_size_px,dpi=result.dpi||100;
  const x=(event.clientX-rect.left)*size[0]/rect.width,y=(rect.top+rect.height-event.clientY)*size[1]/rect.height;
  const px=8*size[0]/rect.width,py=8*size[1]/rect.height;
  return [...componentSelection].some(key=>{const box=componentSelectionBounds(result,key);if(!box)return false;
    const [dx,dy]=componentPendingDragOffset(img,key).map(value=>value*dpi/72);
    return x>=box[0]+dx-px&&x<=box[2]+dx+px&&y>=box[1]+dy-py&&y<=box[3]+dy+py;
  });
}
function selectComponentDragTarget(img,result,event,fallback){
  const rect=chartImageRect(img),size=result.render_size_px,p={x:(event.clientX-rect.left)*size[0]/rect.width,y:(rect.top+rect.height-event.clientY)*size[1]/rect.height};
  const inside=box=>box&&p.x>=box[0]&&p.x<=box[2]&&p.y>=box[1]&&p.y<=box[3];
  if(componentSelectionMode==='subplot'){
    const candidates=(result.axes||[]).map((axis,i)=>({key:'axes_'+i,box:typeof subplotPlotBox==='function'?subplotPlotBox(axis,result):axis.bbox_px}))
      .filter(item=>(!result.allowedAxisKeys||result.allowedAxisKeys.includes(item.key))&&inside(item.box));
    candidates.sort((a,b)=>(a.box[2]-a.box[0])*(a.box[3]-a.box[1])-(b.box[2]-b.box[0])*(b.box[3]-b.box[1]));
    let key=candidates[0]?.key;
    if(!key){const label=result.texts?.find(text=>inside(text.bbox));key=label?.subplot_key||label?.key.match(/^axes_\d+/)?.[0];}
    if(!key){componentSelection.clear();drawComponentSelection();return;}
    selectSubplot(img,result,key);
    openComponentInspector(event,'整个子图 '+(Number(key.slice(5))+1)+' 属性',['showGrid','fontSize','borderWidth','borderColor','quickTitle','quickXLabel','quickYLabel'],'axis');
    const family=typeof subplotFamily==='function'?subplotFamily(result,key):[key];
    for(const member of family)if(componentSelection.has(key))componentSelection.add(member);else componentSelection.delete(member);
    drawComponentSelection();return;
  }
  const text=(result.texts||[]).find(text=>inside(text.bbox)&&(componentSelectionMode==='text'||text.key.startsWith('figure.text_')));
  if(text){
    const axis=text.subplot_key||text.key.match(/^axes_\d+/)?.[0];if(axis)selectSubplot(img,result,axis);
    $('fontSize').value=baseInteractiveStyle.text_styles?.[text.key]?.font_size??text.fontsize??'';
    selectedTextKey=text.key;openComponentInspector(event,'文字 / 子图标识「'+text.text+'」属性',text.key.startsWith('figure.')?[]:['fontSize'],'text');return;
  }
  if(componentSelectionMode==='text'){componentSelection.clear();drawComponentSelection();return;}
  fallback(event);
}
function componentDragAnnotationDelta(model,keys,dx,dy){
  const before=model.participant_shifts||[[0,0],[0,0]],delta=model.participants.map(group=>group.some(key=>keys.includes(key))?[dx,dy]:[0,0]);
  const d=model.category_dimension,q=1-d;
  const extreme=values=>model.quantitative_side>0?Math.max(...values):Math.min(...values);
  const quantitative=model.shared_quantitative?extreme(before.map((p,i)=>p[q]+delta[i][q]))-extreme(before.map(p=>p[q])):delta[0][q];
  return model.weights.map(w=>{const p=[0,0];p[d]=(1-w)*delta[0][d]+w*delta[1][d];p[q]=quantitative;return p;});
}
function createComponentDragPreview(img,result,keys){
  img._componentDragPreview?.remove();
  const frame=img.parentElement,host=frame.closest?.('.subplotZoomViewport')||frame;
  if(host!==frame)host.style.position='relative';
  const rect=chartImageRect(img),hr=host.getBoundingClientRect(),size=result.render_size_px,dpi=result.dpi||100;
  host.querySelectorAll('.componentDragPreview').forEach(node=>node.remove());
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('componentDragPreview');
  svg.setAttribute('aria-hidden','true');svg.setAttribute('viewBox',`0 0 ${size[0]} ${size[1]}`);svg.setAttribute('preserveAspectRatio','none');
  svg.style.cssText=`position:absolute;pointer-events:none;z-index:7;overflow:visible;left:${rect.left-hr.left+(host.scrollLeft||0)}px;top:${rect.top-hr.top+(host.scrollTop||0)}px;width:${rect.width}px;height:${rect.height}px;`;
  const groups=(result.component_groups||[]).filter(group=>keys.includes(group.key));
  const rawTargets=result._rawTargets||result.targets||[],targetLookup=new Map(rawTargets.map(target=>[target.key,target]));
  const pointOwners=new Set(rawTargets.filter(target=>target.point_role).map(target=>target.owner_key));
  const selected=new Set(keys),members=new Set(groups.flatMap(group=>[...(group.members||[]),...(group.move_members||[]),...(group.part_targets||[]).map(p=>p.key)]));
  const axisSelected=key=>keys.some(axis=>/^axes_\d+$/.test(axis)&&key.startsWith(axis+'.'));
  const nodes=[];
  const pathD=points=>points.map(([x,y],i)=>(i?'L':'M')+x+' '+(size[1]-y)).join(' ');
  const addPath=(points,style={},point=false)=>{
    const node=document.createElementNS('http://www.w3.org/2000/svg','path');
    node.setAttribute('d',point?componentMarkerPath(points,style.marker_shape||'o',(style.marker_size||6)*dpi/144,size[1]):pathD(points));
    node.setAttribute('fill',style.fill||'none');node.setAttribute('fill-opacity',style.fillOpacity??.6);
    node.setAttribute('stroke',style.stroke||'#00a67d');node.setAttribute('stroke-width',Math.max(.8,(style.linewidth||1)*dpi/72));
    node.setAttribute('stroke-linejoin','round');node.setAttribute('stroke-linecap','round');svg.append(node);return node;
  };
  for(const key of keys.filter(key=>/^axes_\d+$/.test(key))){
    const box=componentSelectionBounds(result,key);if(!box)continue;
    const [x0,y0,x1,y1]=box,crop=document.createElementNS('http://www.w3.org/2000/svg','svg');
    crop.setAttribute('x',x0);crop.setAttribute('y',size[1]-y1);crop.setAttribute('width',x1-x0);crop.setAttribute('height',y1-y0);
    crop.setAttribute('viewBox',`${x0} ${size[1]-y1} ${x1-x0} ${y1-y0}`);crop.setAttribute('overflow','hidden');
    const bitmap=document.createElementNS('http://www.w3.org/2000/svg','image');bitmap.setAttribute('href',img.currentSrc||img.src||result.image);
    bitmap.setAttribute('width',size[0]);bitmap.setAttribute('height',size[1]);bitmap.setAttribute('opacity',.8);crop.append(bitmap);svg.append(crop);nodes.push({node:crop});
  }
  for(const target of rawTargets){
    if(axisSelected(target.key))continue;
    const linkedVertices=selected.has(target.key)?null:target.point_move_vertices?.map(peers=>peers.some(key=>selected.has(key)||members.has(key)));
    if(!selected.has(target.key)&&!members.has(target.key)&&!members.has(target.owner_key)&&!selected.has(target.owner_key)&&!linkedVertices?.some(Boolean))continue;
    if(!target.hit_path_px?.length)continue;
    if(target.kind==='scatter'&&!target.point_role&&pointOwners.has(target.key))continue;
    const style=target.style||{},point=!!target.point_role||target.kind==='scatter';
    const filled=point||['patch','polygon_collection','heatmap'].includes(target.kind);
    const node=addPath(target.hit_path_px,{...style,fill:filled?componentColorHex(point?style.fill_color:style.facecolor)||'none':'none',
      fillOpacity:point?componentRgba(style.fill_color)?.[3]??1:.55,stroke:componentColorHex(point?style.edge_color:style.color||style.edgecolor)||'#00a67d'},point);
    nodes.push(linkedVertices?.some(Boolean)?{node,linkedVertices,points:target.hit_path_px}:{node});
  }
  const addText=(record,delta=null)=>{
    const node=document.createElementNS('http://www.w3.org/2000/svg','text'),b=record.bbox;
    node.setAttribute('x',b[0]);node.setAttribute('y',size[1]-b[1]);node.setAttribute('fill','#111');node.setAttribute('font-size',(record.fontsize||8)*dpi/72);
    node.setAttribute('paint-order','stroke');node.setAttribute('stroke','white');node.setAttribute('stroke-width',.6*dpi/72);node.textContent=record.text;svg.append(node);nodes.push({node,delta});
  };
  const annotationModels=new Map(groups.flatMap(group=>(group.annotation_links||[]).map(model=>[model.key,model])));
  for(const model of annotationModels.values()){
    if(selected.has(model.key))continue;
    const target=targetLookup.get(model.key),text=result.texts?.find(t=>t.key===model.key);
    if(target?.hit_path_px?.length){const node=addPath(target.hit_path_px,{stroke:componentColorHex(target.style?.color)||'#111',linewidth:target.style?.linewidth||1});nodes.push({node,model,points:target.hit_path_px});}
    else if(text)addText(text,(dx,dy)=>componentDragAnnotationDelta(model,keys,dx,dy)[0]);
  }
  for(const group of groups)for(const anchor of group.category_anchors||[]){
    const delta=(dx,dy)=>anchor.dimension===0?[dx,0]:[0,dy];
    for(const key of anchor.tick_keys||[]){const text=result.texts?.find(t=>t.key===key);if(text&&!selected.has(key))addText(text,delta);}
    for(const points of anchor.tick_paths_px||[])nodes.push({node:addPath(points,{stroke:'#333'}),delta});
  }
  const categoryAxes=new Set(groups.flatMap(group=>(group.category_anchors||[]).map(anchor=>group.key.split('.')[0]+':'+anchor.dimension)));
  for(const identity of categoryAxes){
    const [axisKey,dim]=identity.split(':'),d=Number(dim),axis=result.axes?.[Number(axisKey.slice(5))];
    const positions=new Map();
    for(const group of result.component_groups||[])if(group.key.startsWith(axisKey+'.'))for(const anchor of group.category_anchors||[]){
      if(anchor.dimension!==d||!anchor.tick_paths_px?.length)continue;
      const p=anchor.tick_paths_px[0][0][d],old=positions.get(p);positions.set(p,{p,selected:keys.includes(group.key)||old?.selected});
    }
    const samples=[...positions.values()];if(!samples.length)continue;
    for(const side of d===0?['bottom','top']:['left','right']){
      const b=axis?.spines?.[side];if(!b)continue;
      const points=d===0?[[b[0],side==='bottom'?b[3]:b[1]],[b[2],side==='bottom'?b[3]:b[1]]]
        :[[side==='left'?b[2]:b[0],b[1]],[side==='left'?b[2]:b[0],b[3]]];
      const node=addPath(points,{stroke:'#00a67d',linewidth:1.3});node.setAttribute('stroke-dasharray',`${3*dpi/72} ${2*dpi/72}`);
      nodes.push({node,spine:(dx,dy)=>{const delta=(d===0?dx:dy)*dpi/72,old=samples.map(s=>s.p),next=samples.map(s=>s.p+(s.selected?delta:0));
        return points.map((p,i)=>{const result=[...p];result[d]+=i?Math.max(...next)-Math.max(...old):Math.min(...next)-Math.min(...old);return result;});}});
    }
  }
  for(const text of result.texts||[])if(selected.has(text.key)&&!axisSelected(text.key)&&!keys.includes(text.subplot_key))addText(text);
  for(const key of keys){
    const box=componentSelectionBounds(result,key);
    if(box){const [x0,y0,x1,y1]=box,node=addPath([[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]],{stroke:'#00a67d',linewidth:1});node.setAttribute('stroke-dasharray',`${4*dpi/72} ${3*dpi/72}`);nodes.push({node});}
  }
  const movingLayer=document.createElementNS('http://www.w3.org/2000/svg','g');
  for(const item of nodes)if(!item.spine&&!item.model&&!item.delta&&!item.linkedVertices)movingLayer.append(item.node);
  svg.append(movingLayer);host.append(svg);
  const preview={update(dx,dy){
    movingLayer.setAttribute('transform',`translate(${dx*dpi/72} ${-dy*dpi/72})`);
    for(const item of nodes){
      if(item.spine)item.node.setAttribute('d',pathD(item.spine(dx,dy)));
      else if(item.linkedVertices)item.node.setAttribute('d',pathD(item.points.map((p,i)=>item.linkedVertices[i]?[p[0]+dx*dpi/72,p[1]+dy*dpi/72]:p)));
      else if(item.model){const moves=componentDragAnnotationDelta(item.model,keys,dx,dy);item.node.setAttribute('d',pathD(item.points.map((p,i)=>[p[0]+moves[i][0]*dpi/72,p[1]+moves[i][1]*dpi/72])));}
      else if(item.delta){const shift=item.delta(dx,dy);item.node.setAttribute('transform',`translate(${shift[0]*dpi/72} ${-shift[1]*dpi/72})`);}
    }
  },remove(){svg.remove();if(img._componentDragPreview===preview)delete img._componentDragPreview;}};
  img._componentDragPreview=preview;return preview;
}
attachDirectManipulation=function(img,result){
  img._cancelComponentDrag?.();
  img._componentDragPreview?.remove();
  img.parentElement?.querySelectorAll('.componentDragPreview').forEach(node=>node.remove());
  img.parentElement?.querySelectorAll('.offlineComponentPreview').forEach(node=>node.remove());
  result._rawTargets??=result.targets||[];
  result._connectionGroups??=buildConnectionGroups(result);
  result.targets=result._rawTargets;
  {
    const activeGroups=(result.component_groups||[]).filter(group=>componentSelectionMode==='group'||group.locked_selection);
    const members=new Map(activeGroups.flatMap(group=>[...(group.members||[]),...(group.move_members||[])].map(key=>[key,group])));
    result.targets=result._rawTargets.map(target=>{
      const group=members.get(target.key)||result.component_groups?.find(item=>item.key===target.group_key),key=group?.key||target.group_key;
      return key&&(componentSelectionMode==='group'||group?.locked_selection)?{...target,key,label:group?.label||'整体图形'}:target;
    });
    for(const group of activeGroups){for(const path of group.hit_paths_px||[])result.targets.push({key:group.key,label:group.label,kind:'line',hit_path_px:path});}
  }
  attachBasicManipulation(img,result);
  img._componentRenderedOffsets=Object.fromEntries(Object.entries(baseInteractiveStyle.component_styles||{}).map(([key,spec])=>[key,{dx:spec.dx||0,dy:spec.dy||0}]));
  img.dataset.dragEnabled=String(componentDragEnabled);
  drawComponentSelection();
  const basicClick=img.onclick,click=event=>selectComponentDragTarget(img,result,event,basicClick);let suppress=false;
  img.onclick=event=>{if(suppress){suppress=false;event.preventDefault();event.stopPropagation();return;}click(event);};
  img.onpointerdown=(event,fromHandle=false)=>{
    if(event.button!==0||!componentDragEnabled)return;
    const reuseSelection=fromHandle||componentSelectedDragHit(img,result,event);
    if(!reuseSelection)click(event);suppress=true;
    if(!componentSelection.size)return;
    event.preventDefault();event.stopPropagation();img.setPointerCapture(event.pointerId);
    img._componentDragging=true;
    const rect=chartImageRect(img),dpi=result.dpi||100,keys=componentDragKeys(result,[...componentSelection]),styles=baseInteractiveStyle.component_styles||{};
    const starts=Object.fromEntries(keys.map(key=>[key,{dx:styles[key]?.dx||0,dy:styles[key]?.dy||0}]));
    const pending=componentPendingDragOffset(img,keys[0]);
    let dx=0,dy=0,moved=false,preview=null,animation=null,lastStatus=0;
    const paint=()=>{
      animation=null;if(!moved)return;
      if(!preview){document.querySelectorAll?.('.componentSelectionBox').forEach(node=>node.remove());if(keys.some(key=>/^axes_\d+$/.test(key)))document.querySelectorAll?.('.subplotSelectionBox').forEach(node=>node.remove());preview=createComponentDragPreview(img,result,keys);}
      preview.update(dx+pending[0],dy+pending[1]);img.style.cursor='grabbing';
      const now=Date.now();if(now-lastStatus>100){$('stylePreviewState').textContent=`实时预览位置：水平 ${dx.toFixed(1)} pt，垂直 ${dy.toFixed(1)} pt；松开确认位移`;lastStatus=now;}
    };
    img.onpointermove=move=>{
      moved=moved||Math.hypot(move.clientX-event.clientX,move.clientY-event.clientY)>2;
      dx=(move.clientX-event.clientX)/rect.width*result.render_size_px[0]/dpi*72;
      dy=-(move.clientY-event.clientY)/rect.height*result.render_size_px[1]/dpi*72;
      if(moved&&animation===null){if(typeof requestAnimationFrame==='function')animation=requestAnimationFrame(paint);else paint();}
    };
    const cleanup=(keepPreview=false)=>{
      if(animation!==null){cancelAnimationFrame(animation);animation=null;}
      if(!keepPreview){preview?.remove();drawComponentSelection();}
      img._componentDragging=false;
      const deferred=img._deferredStylePreview;delete img._deferredStylePreview;
      img.onpointermove=null;img.onpointerup=null;img.onpointercancel=null;img.style.cursor='';img._cancelComponentDrag=null;
      if(img.hasPointerCapture(event.pointerId))img.releasePointerCapture(event.pointerId);
      if(deferred&&!keepPreview)scheduleInteractiveStylePreview(!stylePreviewNeedsFull);
    };
    img._cancelComponentDrag=()=>{cleanup();suppress=false;};
    const finish=()=>{
      if(animation!==null){cancelAnimationFrame(animation);animation=null;}
      if(moved)paint();
      cleanup(moved);
      if(!moved){if(reuseSelection&&!fromHandle)click(event);return;}
      const next=baseInteractiveStyle.component_styles||{};
      for(const key of keys)next[key]={...(next[key]||{}),dx:starts[key].dx+dx,dy:starts[key].dy+dy};
      baseInteractiveStyle.component_styles=next;scheduleInteractiveStylePreview();
      const panel=$('componentInspector');if(panel){const x=panel.querySelector('[data-component-prop="dx"]'),y=panel.querySelector('[data-component-prop="dy"]');if(x)x.value=(starts[keys[0]].dx+dx).toFixed(1);if(y)y.value=(starts[keys[0]].dy+dy).toFixed(1);}
    };
    img.onpointerup=finish;img.onpointercancel=()=>img._cancelComponentDrag?.();
  };
};

function drawComponentSelection(){
  document.querySelectorAll('.componentSelectionBox').forEach(node=>node.remove());
  const img=document.querySelector('#subplotZoomDialog .subplotZoomFrame img')||document.querySelector('.chartCard.active img');if(!img||!stylePreviewData)return;
  const result=stylePreviewData,rect=chartImageRect(img),host=img.parentElement,hr=host.getBoundingClientRect(),size=result.render_size_px;
  if(!size)return;
  for(const key of componentSelection){
    const bounds=componentSelectionBounds(result,key);if(!bounds)continue;
    const offset=componentPendingDragOffset(img,key).map(value=>value*(result.dpi||100)/72),box=bounds.map((v,i)=>v+offset[i%2]);
    const mark=document.createElement('div');mark.className='componentSelectionBox';mark.style.cssText=`position:absolute;pointer-events:none;z-index:6;border:3px dashed #00a67d;box-shadow:0 0 0 1px #fff;left:${rect.left-hr.left+box[0]/size[0]*rect.width-5}px;top:${rect.top-hr.top+(size[1]-box[3])/size[1]*rect.height-5}px;width:${(box[2]-box[0])/size[0]*rect.width+10}px;height:${(box[3]-box[1])/size[1]*rect.height+10}px`;host.append(mark);
    if(componentDragEnabled){const grip=document.createElement('span');grip.textContent='✥ 拖动';grip.style.cssText='position:absolute;left:-3px;top:-22px;padding:3px 8px;background:#008b6a;color:white;font-size:11px;line-height:16px;border-radius:4px;cursor:grab;pointer-events:auto;white-space:nowrap;touch-action:none;user-select:none';grip.onpointerdown=event=>img.onpointerdown(event,true);grip.onclick=event=>{event.preventDefault();event.stopPropagation();};mark.append(grip);}
  }
}

function addRgbColorControls(panel){
  for(const color of panel.querySelectorAll('input[type=color]')){
    const wrap=document.createElement('div'),rgb=document.createElement('input');wrap.className='rgbColorControls';rgb.type='text';rgb.dataset.rgbInput='';rgb.setAttribute('aria-label','RGB 颜色');
    const sync=()=>{const hex=color.value;rgb.value=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)).join(', ');};sync();
    color.addEventListener('input',sync);rgb.oninput=()=>{
      const match=rgb.value.trim().match(/^(?:rgb\(\s*)?(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)?$/i),values=match?.slice(1).map(Number);
      const valid=values&&values.every(n=>n>=0&&n<=255);rgb.setCustomValidity(valid?'':'请输入 0～255 的 R, G, B');
      if(valid){color.value='#'+values.map(n=>n.toString(16).padStart(2,'0')).join('');color.dispatchEvent(new Event('input',{bubbles:true}));}
    };wrap.append(rgb);
    const palette=document.createElement('div');palette.className='componentPalette';
    for(const hex of ['#111111','#ffffff','#ff0000','#00aa55','#0066ff','#ff9900','#9933cc','#777777']){const button=document.createElement('button');button.type='button';button.title=hex;button.setAttribute('aria-label','色卡 '+hex);button.style.cssText='width:18px;height:18px;padding:0;border:1px solid #888;background:'+hex;button.onclick=()=>{color.value=hex;color.dispatchEvent(new Event('input',{bubbles:true}));};palette.append(button);}
    wrap.append(palette);
    if(color.dataset.skipOpacity==='true'){color.closest('label').append(wrap);continue;}
    const property=color.dataset.componentProp==='fill_color'?'fill_alpha':color.dataset.componentProp==='edge_color'?'edge_alpha':'alpha';
    const selected=[...componentSelection][0],spec=baseInteractiveStyle.component_styles?.[selected]||{};
    const current=spec[property]??spec.alpha??Number(color.dataset.renderedAlpha??1);
    const controls=document.createElement('div'),title=document.createElement('span'),slider=document.createElement('input'),number=document.createElement('input');
    controls.className='opacityControls';title.textContent='透明度 %';slider.type='range';number.type='number';
    for(const input of [slider,number]){input.min=0;input.max=100;input.step=1;input.value=Math.round((1-current)*100);input.setAttribute('aria-label','透明度百分比');}
    number.dataset.opacityProperty=property;
    const change=input=>{if(input.value===''||!input.validity.valid)return;slider.value=number.value=input.value;updateComponents(property,1-Number(input.value)/100);};
    slider.oninput=()=>change(slider);number.oninput=()=>change(number);controls.append(title,slider,number);wrap.append(controls);
    const hint=document.createElement('small');hint.textContent='0% 不透明，100% 完全透明';wrap.append(hint);
    color.closest('label').append(wrap);
  }
}
