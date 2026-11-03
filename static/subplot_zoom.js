// Use the full-resolution bitmap with a clipped viewport. Keeping its full
// image coordinates lets the existing hit tests and drag distances stay valid.
let subplotZoomAxis=null,subplotInspectorTimer=null,pendingSubplotPoint=null;
const subplotStatus=document.createElement('span');subplotStatus.id='subplotInteractionStatus';subplotStatus.className='dim';
const subplotList=document.createElement('select');subplotList.id='subplotQuickPick';subplotList.setAttribute('aria-label','选择子图并放大');subplotList.disabled=true;
const subplotZoomButton=document.createElement('button');
subplotZoomButton.id='zoomSelectedSubplot';subplotZoomButton.type='button';
subplotZoomButton.textContent='放大当前子图';subplotZoomButton.disabled=true;
$('viewOriginalPixels').after(subplotZoomButton,subplotList,subplotStatus);
subplotList.onchange=()=>{if(subplotList.value){selectedAxisKey=subplotList.value;openSubplotZoom();}};
const selectSubplotBeforeZoom=selectSubplot;
selectSubplot=function(img,result,key){
  selectSubplotBeforeZoom(img,result,key);
  subplotZoomButton.disabled=false;subplotZoomButton.textContent='放大子图 '+(Number(key.slice(5))+1);
};
function closeSubplotZoom(){
  const dialog=$('subplotZoomDialog');if(!dialog)return;
  dialog.querySelector('#componentInspector')?.remove();dialog.close();dialog.remove();subplotZoomAxis=null;
}
function subplotCrop(result,key){
  const axis=result.axes?.[Number(key.slice(5))],size=result.render_size_px;
  if(!axis||!size)return null;
  const boxes=subplotFamily(result,key).map(k=>result.axes[Number(k.slice(5))].bbox_px);
  const b=[Math.min(...boxes.map(b=>b[0])),Math.min(...boxes.map(b=>b[1])),Math.max(...boxes.map(b=>b[2])),Math.max(...boxes.map(b=>b[3]))],pad=20;
  return [Math.max(0,b[0]-pad),Math.max(0,size[1]-b[3]-pad),Math.min(size[0],b[2]+pad),Math.min(size[1],size[1]-b[1]+pad)];
}
function sizeSubplotZoom(fit=false){
  const dialog=$('subplotZoomDialog');if(!dialog||!stylePreviewData)return;
  const crop=subplotCrop(stylePreviewData,subplotZoomAxis);if(!crop)return;
  const viewport=dialog.querySelector('.subplotZoomViewport'),frame=dialog.querySelector('.subplotZoomFrame'),img=frame.querySelector('img'),slider=dialog.querySelector('[data-subplot-zoom]'),size=stylePreviewData.render_size_px;
  if(fit){const factor=Math.min((viewport.clientWidth-32)/(crop[2]-crop[0]),(viewport.clientHeight-32)/(crop[3]-crop[1]));slider.value=Math.max(10,Math.min(400,Math.round(factor*100)));}
  const scale=Number(slider.value)/100;
  frame.style.width=(crop[2]-crop[0])*scale+'px';frame.style.height=(crop[3]-crop[1])*scale+'px';
  img.style.cssText=`position:absolute;max-width:none;max-height:none;width:${size[0]*scale}px;height:${size[1]*scale}px;left:${-crop[0]*scale}px;top:${-crop[1]*scale}px;object-fit:fill;`;
  dialog.querySelector('[data-subplot-percent]').textContent=slider.value+'%';
}
function updateSubplotZoom(result){
  const dialog=$('subplotZoomDialog');if(!dialog)return;
  if(dialog.dataset.chart!==state.project+'/'+state.chart){closeSubplotZoom();return;}
  const image=dialog.querySelector('.subplotZoomFrame img');
  image.src=result.image;sizeSubplotZoom();
  const family=subplotFamily(result,subplotZoomAxis),focused={...result,allowedAxisKeys:family};
  const belongs=item=>family.includes(axisKeyFromObject(item.key));
  for(const field of ['texts','targets','legends','component_groups'])focused[field]=(result[field]||[]).filter(belongs);
  focused._rawTargets=(result._rawTargets||result.targets||[]).filter(belongs);
  const fullData=stylePreviewData;attachDirectManipulation(image,focused);stylePreviewData=fullData;
}
function openSubplotZoom(){
  if(!selectedAxisKey||!stylePreviewData?.image){alertStatus('请先等待交互准备完成，再点击要放大的子图');return;}
  const key=selectedAxisKey;closeSubplotZoom();subplotZoomAxis=key;
  const dialog=document.createElement('dialog');dialog.id='subplotZoomDialog';dialog.dataset.chart=state.project+'/'+state.chart;
  dialog.innerHTML='<div class="subplotZoomToolbar"><strong></strong><label>切换子图 <select data-subplot-picker></select></label><label>缩放 <input data-subplot-zoom type="range" min="10" max="400" step="1" value="100"></label><span data-subplot-percent></span><button type="button" data-subplot-fit>适合窗口</button><button type="button" data-subplot-close>返回整图</button></div><div class="subplotZoomWorkspace"><div class="subplotZoomViewport"><div class="subplotZoomFrame"><img data-subplot-image="true" alt="放大的可编辑子图"></div></div><aside class="subplotZoomInspector"><p>点击线条、文字、统计图形或坐标轴进行修改；Shift+点击可多选。确认后仍保存到原来的整张 figure。</p></aside></div>';
  const picker=dialog.querySelector('[data-subplot-picker]');
  for(let i=0;i<stylePreviewData.axes.length;i++){const option=document.createElement('option');option.value='axes_'+i;option.textContent='子图 '+(i+1);picker.append(option);}picker.value=key;
  const title=()=>dialog.querySelector('strong').textContent='放大编辑 · 子图 '+(Number(subplotZoomAxis.slice(5))+1);
  picker.onchange=()=>{subplotZoomAxis=picker.value;selectedAxisKey=picker.value;componentSelection.clear();dialog.querySelector('#componentInspector')?.remove();title();updateSubplotZoom(stylePreviewData);sizeSubplotZoom(true);};
  dialog.querySelector('[data-subplot-close]').onclick=closeSubplotZoom;
  dialog.querySelector('[data-subplot-fit]').onclick=()=>sizeSubplotZoom(true);
  dialog.querySelector('[data-subplot-zoom]').oninput=()=>sizeSubplotZoom();
  dialog.addEventListener('cancel',event=>{event.preventDefault();closeSubplotZoom();});
  dialog.querySelector('.subplotZoomToolbar').append(componentInteractionToolbar());
  document.body.append(dialog);syncComponentInteractionControls();dialog.showModal();title();
  updateSubplotZoom(stylePreviewData);sizeSubplotZoom(true);
  // Show the selected subplot's controls initially, then let direct clicks
  // choose smaller components in the enlarged view.
  const img=dialog.querySelector('img');selectSubplot(img,stylePreviewData,key);
  openComponentInspector({clientX:0,clientY:0},'子图 '+(Number(key.slice(5))+1)+' 属性',['showGrid','fontSize','quickTitle','quickXLabel','quickYLabel'],'axis');
}
subplotZoomButton.onclick=openSubplotZoom;
const attachBeforeSubplotZoom=attachDirectManipulation;
attachDirectManipulation=function(img,result){
  attachBeforeSubplotZoom(img,result);
  if(img.dataset.subplotImage)return;
  installPendingSubplotClick(img);
  subplotStatus.textContent='子图交互已就绪，可双击放大';subplotList.disabled=false;subplotList.innerHTML='<option value="">选择子图并放大…</option>';
  (result.axes||[]).forEach((axis,i)=>{const option=document.createElement('option');option.value='axes_'+i;option.textContent='子图 '+(i+1)+(axis.axis_label?' · '+axis.axis_label:'');subplotList.append(option);});
  if(pendingSubplotPoint&&pendingSubplotPoint.project===state.project&&pendingSubplotPoint.chart===state.chart){const point=pendingSubplotPoint;pendingSubplotPoint=null;zoomAtNormalizedPoint(point.x,point.y,result);}
  updateSubplotZoom(result);
};
const inspectorBeforeSubplotZoom=openComponentInspector;
openComponentInspector=function(...args){
  inspectorBeforeSubplotZoom(...args);
  const dialog=$('subplotZoomDialog'),inspector=$('componentInspector');
  clearTimeout(subplotInspectorTimer);
  if(dialog&&inspector){inspector.style.visibility='';inspector.style.pointerEvents='';dialog.querySelector('.subplotZoomInspector').append(inspector);inspector.classList.add('insideSubplotZoom');}
  else if(inspector){inspector.style.visibility='hidden';inspector.style.pointerEvents='none';subplotInspectorTimer=setTimeout(()=>{if(inspector.isConnected){inspector.style.visibility='';inspector.style.pointerEvents='';}},350);}
};
const selectBeforeSubplotZoom=select;
select=async function(...args){closeSubplotZoom();clearTimeout(subplotInspectorTimer);pendingSubplotPoint=null;subplotList.disabled=true;subplotList.innerHTML='';subplotStatus.textContent='正在准备子图交互…';subplotZoomButton.disabled=true;return selectBeforeSubplotZoom(...args);};

function zoomAtNormalizedPoint(x,y,result){
  const px=x*result.render_size_px[0],py=(1-y)*result.render_size_px[1];
  const candidates=(result.axes||[]).map((axis,i)=>({key:'axes_'+i,b:subplotPlotBox(axis,result)})).filter(item=>px>=item.b[0]&&px<=item.b[2]&&py>=item.b[1]&&py<=item.b[3]);
  // Labels can lie in a neighboring subplot's margin. Plot rectangles win;
  // only fall back to the exact clicked label when outside all plot areas.
  if(!candidates.length){
    for(const text of result.texts||[]){const b=text.bbox;if(px>=b[0]&&px<=b[2]&&py>=b[1]&&py<=b[3]){const key=axisKeyFromObject(text.key);if(key)candidates.push({key,b});}}
  }
  candidates.sort((a,b)=>(a.b[2]-a.b[0])*(a.b[3]-a.b[1])-(b.b[2]-b.b[0])*(b.b[3]-b.b[1]));
  if(!candidates.length){subplotStatus.textContent='未命中子图，请使用子图列表选择';return;}
  selectedAxisKey=candidates[0].key;openSubplotZoom();
}
function installPendingSubplotClick(img){
  img.ondblclick=event=>{
    event.preventDefault();event.stopPropagation();clearTimeout(subplotInspectorTimer);$('componentInspector')?.remove();
    const r=chartImageRect(img),point={project:state.project,chart:state.chart,x:(event.clientX-r.left)/r.width,y:(event.clientY-r.top)/r.height};
    if(stylePreviewData?.axes?.length){zoomAtNormalizedPoint(point.x,point.y,stylePreviewData);}
    else{pendingSubplotPoint=point;subplotStatus.textContent='已记录要放大的位置，交互就绪后自动打开…';}
  };
}
async function loadCachedInteraction(project,chart,request){
  try{
    const result=await api(chartEndpoint(project,chart,'interaction'));
    if(!result.ready||request!==state.detailRequest||project!==state.project||chart!==state.chart)return false;
    const img=document.querySelector('.chartCard.active .chartImage img');if(!img)return false;
    result.image=img.src;result._project=project;result._chart=chart;result._revision=state.detail.revision;result._styleFingerprint=JSON.stringify(collectInteractiveStyle());
    stylePreviewData=result;attachDirectManipulation(img,result);return true;
  }catch(error){console.warn('子图交互缓存不可用',error);return false;}
}

function subplotPlotBox(axis,result){
  if(axis.plot_bbox_px)return axis.plot_bbox_px;
  if(axis.position){const p=axis.position,s=result.render_size_px;return [p[0]*s[0],p[1]*s[1],(p[0]+p[2])*s[0],(p[1]+p[3])*s[1]];}
  return axis.bbox_px;
}
function subplotFamily(result,key){
  const axis=result.axes?.[Number(key.slice(5))];if(!axis)return [key];
  const chosen=subplotPlotBox(axis,result);
  return result.axes.map((item,i)=>({key:'axes_'+i,b:subplotPlotBox(item,result)})).filter(item=>item.b.every((v,i)=>Math.abs(v-chosen[i])<2)).map(item=>item.key);
}

function subplotHitFamily(result,point){
  const candidates=(result.axes||[]).map((axis,i)=>({key:'axes_'+i,b:subplotPlotBox(axis,result)})).filter(item=>point.x>=item.b[0]&&point.x<=item.b[2]&&point.y>=item.b[1]&&point.y<=item.b[3]);
  candidates.sort((a,b)=>(a.b[2]-a.b[0])*(a.b[3]-a.b[1])-(b.b[2]-b.b[0])*(b.b[3]-b.b[1]));
  return candidates.length?subplotFamily(result,candidates[0].key):null;
}
