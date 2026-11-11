const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/component_editor.js','utf8');
const implementation=source.slice(source.indexOf('function componentSelectionBounds('),source.indexOf('attachDirectManipulation=function(img,result){'));
const makeNode=tag=>({tag,attrs:{},children:[],style:{},classList:{values:new Set(),add(name){this.values.add(name)}},setAttribute(key,value){this.attrs[key]=value},append(node){if(node.parent)node.parent.children=node.parent.children.filter(n=>n!==node);this.children.push(node);node.parent=this},remove(){this.removed=true;if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this)}});
const descendants=node=>node.children.flatMap(child=>[child,...descendants(child)]);
const translation=node=>node.attrs.transform||(node.parent&&translation(node.parent));
const host=makeNode('host');host.querySelectorAll=selector=>host.children.filter(n=>n.classList.values.has(selector.slice(1)));host.getBoundingClientRect=()=>({left:0,top:0});
const img={parentElement:host};
const model={key:'axes_0.line_9',category_dimension:0,weights:[0,0,1,1],participants:[['axes_0.box_0'],['axes_0.box_1']],participant_shifts:[[0,0],[0,0]],quantitative_side:1,shared_quantitative:true};
const result={dpi:72,render_size_px:[200,200],component_groups:[{key:'axes_0.box_0',bbox:[10,20,30,50],members:['axes_0.patch_0'],
  annotation_links:[model,{...model,key:'axes_0.annotation_0',weights:[.5]}],category_anchors:[{dimension:0,tick_keys:['axes_0.xtick_major_0_1'],tick_paths_px:[[[20,10],[20,5]]]}]}],
  _rawTargets:[{key:'axes_0.patch_0',kind:'patch',hit_path_px:[[10,20],[30,20],[30,50],[10,50],[10,20]],style:{facecolor:[0,1,0,1]}},
    {key:'axes_0.line_9',kind:'line',hit_path_px:[[20,70],[20,80],[120,80],[120,70]],style:{color:'#111111',linewidth:1}}],
  texts:[{key:'axes_0.annotation_0',text:'***',fontsize:8,bbox:[65,85,75,95]},
    {key:'axes_0.xtick_major_0_1',text:'Group A',fontsize:8,bbox:[10,0,30,8]}]};
const ctx=vm.createContext({document:{createElementNS:(_ns,tag)=>makeNode(tag)},chartImageRect:()=>({left:0,top:0,width:200,height:200}),
 componentColorHex:value=>typeof value==='string'?value:'#00aa55',componentRgba:()=>[0,1,0,1],componentMarkerPath:()=>'',result});
vm.runInContext(implementation,ctx);
const preview=ctx.createComponentDragPreview(img,result,['axes_0.box_0']);
preview.update(18,9);
const svg=host.children[0],box=descendants(svg).find(node=>node.attrs.fill==='#00aa55');
assert.equal(translation(box),'translate(18 -9)');
assert.equal(svg.children.find(node=>node.textContent==='***').attrs.transform,'translate(9 -9)');
assert.equal(svg.children.find(node=>node.textContent==='Group A').attrs.transform,'translate(18 0)');
assert(svg.children.some(node=>node.attrs.d==='M38 121 L38 111 L120 111 L120 121'));
const delta=ctx.componentDragAnnotationDelta({...model,weights:[.5],participant_shifts:[[0,12],[0,0]]},['axes_0.box_0'],18,-4);
assert.deepEqual(JSON.parse(JSON.stringify(delta)),[[9,-4]]);
preview.update(36,18);assert.equal(translation(box),'translate(36 -18)');
preview.remove();assert.equal(host.children.length,0);
const rawPreview=ctx.createComponentDragPreview(img,result,['axes_0.patch_0']);rawPreview.update(5,6);
assert(descendants(host.children[0]).some(node=>node.attrs['stroke-dasharray']&&translation(node)==='translate(5 -6)'));
rawPreview.remove();
ctx.componentSelectionMode='group';ctx.componentDragEnabled=true;ctx.componentSelection=new Set(['axes_0.box_0']);
ctx.baseInteractiveStyle={component_styles:{}};ctx.buildConnectionGroups=()=>[];ctx.drawComponentSelection=()=>{};
let scheduled=0,captured=false,selections=0;
ctx.scheduleInteractiveStylePreview=()=>scheduled++;
ctx.$=id=>id==='componentInspector'?null:{};
img.dataset={};img.style={};img.setPointerCapture=()=>captured=true;img.hasPointerCapture=()=>captured;img.releasePointerCapture=()=>captured=false;
ctx.attachDirectManipulation=(image,data)=>{ctx.stylePreviewData=data;image.onclick=()=>{selections++;ctx.componentSelection=new Set(['axes_0.box_0']);}};
vm.runInContext(source.slice(source.indexOf('const attachBasicManipulation=attachDirectManipulation;'),source.indexOf('\nfunction drawComponentSelection(){')),ctx);
ctx.attachDirectManipulation(img,result);
img.onpointerdown({button:0,clientX:10,clientY:100,pointerId:1,preventDefault(){},stopPropagation(){}});
img.onpointermove({clientX:28,clientY:91});
assert.equal(host.children.length,1);assert.equal(scheduled,0);assert.equal(ctx.baseInteractiveStyle.component_styles['axes_0.box_0'],undefined);
img.onpointerup();assert.equal(scheduled,1);assert.equal(captured,false);
assert.equal(ctx.baseInteractiveStyle.component_styles['axes_0.box_0'].dx,18);assert.equal(ctx.baseInteractiveStyle.component_styles['axes_0.box_0'].dy,9);
assert.equal(host.children.length,1); // Destination stays visible until precise rendering arrives.
ctx.attachDirectManipulation(img,result);assert.equal(host.children.length,0);
img.onpointerdown({button:0,clientX:10,clientY:100,pointerId:1,preventDefault(){},stopPropagation(){}});
img.onpointermove({clientX:30,clientY:100});img.onpointercancel();
assert.equal(host.children.length,0);assert.equal(scheduled,1);assert.equal(ctx.baseInteractiveStyle.component_styles['axes_0.box_0'].dx,18);
const panelResult={dpi:72,render_size_px:[200,200],image:'data:image/png;base64,example',
  axes:[{bbox_px:[10,20,90,120]},{bbox_px:[110,20,190,120]}],targets:[],component_groups:[],
  texts:[{key:'figure.text_0',subplot_key:'axes_0',text:'a',bbox:[5,125,15,140],fontsize:10}]};
ctx.selectSubplot=(_img,_result,key)=>{ctx.selectedAxisKey=key;};
ctx.openComponentInspector=(_event,_title,_ids,scope)=>{ctx.componentSelection=new Set([scope==='text'?ctx.selectedTextKey:ctx.selectedAxisKey]);};
ctx.componentSelectionMode='subplot';ctx.attachDirectManipulation(img,panelResult);
img.onpointerdown({button:0,clientX:50,clientY:110,pointerId:1,preventDefault(){},stopPropagation(){}});
img.onpointermove({clientX:70,clientY:100});
let panelGhost=host.children[0];
const crop=descendants(panelGhost).find(node=>node.tag==='svg');
assert(crop);assert.equal(crop.children[0].attrs.href,panelResult.image);
assert.equal(translation(crop),'translate(20 -10)');
assert(descendants(panelGhost).some(node=>node.attrs['stroke-dasharray']&&translation(node)==='translate(20 -10)'));
img.onpointerup();assert.equal(ctx.baseInteractiveStyle.component_styles.axes_0.dx,20);
assert.equal(ctx.baseInteractiveStyle.component_styles.axes_1,undefined);
ctx.componentSelectionMode='text';ctx.componentSelection.clear();ctx.attachDirectManipulation(img,panelResult);
img.onpointerdown({button:0,clientX:10,clientY:65,pointerId:1,preventDefault(){},stopPropagation(){}});
img.onpointermove({clientX:40,clientY:55});
assert.equal(translation(descendants(host.children[0]).find(node=>node.textContent==='a')),'translate(30 -10)');
img.onpointerup();assert.equal(ctx.baseInteractiveStyle.component_styles['figure.text_0'].dx,30);
assert.equal(ctx.baseInteractiveStyle.component_styles.axes_0.dx,20);
assert.deepEqual(Array.from(ctx.componentDragKeys(panelResult,['axes_0','figure.text_0','axes_0.line_0'])),['axes_0']);
// Grabbing the selected rectangle must bypass selection/inspector work, and
// hundreds of mouse events must produce at most one pending visual frame.
ctx.componentSelectionMode='group';ctx.componentSelection=new Set(['axes_0.box_0']);ctx.attachDirectManipulation(img,result);
let frameId=0;const frames=new Map();
ctx.requestAnimationFrame=callback=>{frames.set(++frameId,callback);return frameId;};ctx.cancelAnimationFrame=id=>frames.delete(id);
const flushFrame=()=>{const callbacks=[...frames.values()];frames.clear();callbacks.forEach(callback=>callback());};
const pointer=(x,y)=>({button:0,clientX:x,clientY:y,pointerId:1,preventDefault(){},stopPropagation(){}});
const initialSelections=selections,initialDx=ctx.baseInteractiveStyle.component_styles['axes_0.box_0'].dx;
img.onpointerdown(pointer(20,165));assert.equal(selections,initialSelections);
for(let i=1;i<=100;i++)img.onpointermove(pointer(20+i*.3,165));
assert.equal(frames.size,1);assert.equal(ctx.baseInteractiveStyle.component_styles['axes_0.box_0'].dx,initialDx);
flushFrame();assert(descendants(host.children[0]).some(node=>node.attrs['stroke-dasharray']&&translation(node)==='translate(30 0)'));
img.onpointerup();assert.equal(frames.size,0);assert.equal(ctx.baseInteractiveStyle.component_styles['axes_0.box_0'].dx,initialDx+30);
// Continue from the visible destination before the server returns a new image.
img.onpointerdown(pointer(50,165));assert.equal(selections,initialSelections);
img.onpointermove(pointer(60,165));flushFrame();
assert(descendants(host.children[0]).some(node=>node.attrs['stroke-dasharray']&&translation(node)==='translate(40 0)'));
img.onpointerup();assert.equal(ctx.baseInteractiveStyle.component_styles['axes_0.box_0'].dx,initialDx+40);
// Release before the queued frame: flush the final pointer position once and
// cancel the queued callback so it cannot redraw after release or cancellation.
img.onpointerdown(pointer(60,165));img.onpointermove(pointer(63,165));assert.equal(frames.size,1);
img.onpointerup();assert.equal(frames.size,0);assert.equal(ctx.baseInteractiveStyle.component_styles['axes_0.box_0'].dx,initialDx+43);
img.onpointerdown(pointer(63,165));img.onpointermove(pointer(70,165));img.onpointercancel();
assert.equal(frames.size,0);assert.equal(ctx.baseInteractiveStyle.component_styles['axes_0.box_0'].dx,initialDx+43);
img.onpointerdown(pointer(999,999),true);assert.equal(selections,initialSelections);img.onpointerup();assert.equal(selections,initialSelections);
ctx.document.createElement=tag=>makeNode(tag);ctx.document.querySelector=()=>img;
ctx.document.querySelectorAll=selector=>host.children.filter(node=>node.className===selector.slice(1));
vm.runInContext(source.slice(source.indexOf('function drawComponentSelection(){'),source.indexOf('\nfunction addRgbColorControls(')),ctx);
ctx.drawComponentSelection();
const selectedFrame=host.children.find(node=>node.className==='componentSelectionBox'),grip=selectedFrame.children[0];
assert.equal(grip.textContent,'✥ 拖动');assert(selectedFrame.style.cssText.includes('left:48px'));
let handleStarted=false;img.onpointerdown=(_event,fromHandle)=>{handleStarted=fromHandle;};grip.onpointerdown(pointer(0,0));assert.equal(handleStarted,true);
const a='axes_0.collection_0.points_regular',outlier='axes_0.collection_0.points_outliers',b='axes_0.collection_1.points_regular',l0='axes_0.line_0',l1='axes_0.line_1';
const linkedResult={dpi:72,render_size_px:[200,200],texts:[],_rawTargets:[
  {key:a,point_role:'regular',point_group:'A',point_move_members:[a,outlier],kind:'scatter',hit_path_px:[[20,40]],style:{}},
  {key:outlier,point_role:'outliers',point_group:'A',point_move_members:[a,outlier],kind:'scatter',hit_path_px:[[20,50]],style:{}},
  {key:b,point_role:'regular',point_group:'B',point_move_members:[b],kind:'scatter',hit_path_px:[[120,60],[120,70]],style:{}},
  ...[l0,l1].map((key,i)=>({key,kind:'line',point_move_members:[a,outlier,b],move_connection_members:[l0,l1],point_move_vertices:[[a,outlier],[b]],hit_path_px:[[20,40+10*i],[120,60+10*i]],style:{}}))]};
const pointKeys=ctx.componentDragKeys(linkedResult,[a]);assert.deepEqual(Array.from(pointKeys),[a,outlier]);
const linkedPreview=ctx.createComponentDragPreview(img,linkedResult,pointKeys);linkedPreview.update(12,6);
let linkedSvg=host.children.find(node=>node.classList.values.has('componentDragPreview'));
assert(descendants(linkedSvg).some(node=>node.attrs.d==='M32 154 L120 140'));
assert(descendants(linkedSvg).some(node=>node.attrs.d==='M32 144 L120 130'));linkedPreview.remove();
const lineKeys=ctx.componentDragKeys(linkedResult,[l0]);assert.deepEqual(Array.from(lineKeys),[l0,a,outlier,b,l1]);
const linePreview=ctx.createComponentDragPreview(img,linkedResult,lineKeys);linePreview.update(12,6);
linkedSvg=host.children.find(node=>node.classList.values.has('componentDragPreview'));
assert(descendants(linkedSvg).some(node=>node.attrs.d==='M20 160 L120 140'&&translation(node)==='translate(12 -6)'));linePreview.remove();
console.log('PASS: subplot and panel-letter selection, live bitmap and selection frame, isolated commits, cancellation, and statistical annotation previews.');
console.log('PASS: selected-box and handle grabs skip reselection; 100 moves coalesce to one frame; pending renders allow continuous dragging; final frame and cancellation stay correct.');
console.log('PASS: sample movement expands to same-group outliers and stretches only matching connector endpoints; dragging a connector moves its family and endpoint clouds.');
const summary='axes_0.bar_item_0';
const summaryResult={dpi:72,render_size_px:[200,200],texts:[],component_groups:[{key:summary,movement_only:true,members:['axes_0.patch_0','axes_0.collection_0.segment_0','axes_0.line_0.vertex_0'],bbox:[10,20,30,70]}],_rawTargets:[
 {key:'axes_0.patch_0',movement_group:summary,kind:'patch',hit_path_px:[[10,20],[30,20],[30,60],[10,60]],style:{facecolor:[0,1,0,1]}},
 {key:'axes_0.collection_0.segment_0',movement_group:summary,kind:'line',hit_path_px:[[20,50],[20,70]],style:{color:'#111'}},
 {key:'axes_0.line_0.vertex_0',movement_group:summary,kind:'line',hit_path_px:[[17,70],[23,70]],style:{color:'#111'}},
 {key:'axes_0.line_1.points_mean_0',movement_group:summary,point_role:'mean',kind:'scatter',hit_path_px:[[20,60]],style:{marker_shape:'o'}},
 {key:'axes_0.line_1',kind:'line',movement_vertices:[[summary],['axes_0.bar_item_1']],hit_path_px:[[20,60],[120,80]],style:{color:'#111'}}]};
const summaryKeys=ctx.componentDragKeys(summaryResult,['axes_0.patch_0']);assert.deepEqual(Array.from(summaryKeys),[summary]);
assert.deepEqual(Array.from(ctx.componentSelectionBounds(summaryResult,'axes_0.patch_0')),[10,20,30,70]);
const summaryPreview=ctx.createComponentDragPreview(img,summaryResult,summaryKeys);summaryPreview.update(12,6);
const summarySvg=host.children.find(node=>node.classList.values.has('componentDragPreview'));
assert(descendants(summarySvg).some(node=>node.attrs.d==='M17 130 L23 130'&&translation(node)==='translate(12 -6)'));
assert(descendants(summarySvg).some(node=>node.attrs.d==='M32 134 L120 120'));summaryPreview.remove();
summaryResult._rawTargets.push({key:'axes_0.line_5',kind:'line',movement_vertices:[[summary],['axes_0.bar_item_1']],hit_path_px:[[20,70],[120,90]],style:{marker:'_',linestyle:'None'}});
ctx.componentSelection.clear();ctx.attachDirectManipulation(img,summaryResult);
assert(!summaryResult.targets.some(target=>target.key==='axes_0.line_5'));
console.log('PASS: bar-part movement uses the summary group, follows error stems/caps and mean points, and stretches only the moved mean-line endpoint.');
