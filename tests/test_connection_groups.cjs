const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/component_editor.js','utf8');
const implementation=source.slice(source.indexOf('function buildConnectionGroups('),source.indexOf('function connectionGroupForMember('));
const color=value=>Array.isArray(value)?'#'+value.slice(0,3).map(n=>Math.round(n*255).toString(16).padStart(2,'0')).join(''):value;
const ctx=vm.createContext({componentColorHex:color});vm.runInContext(implementation,ctx);
const dot=(key,group,points,axis='axes_0',role='regular')=>({key:axis+'.'+key+'.points_'+role,owner_key:axis+'.'+key,kind:'scatter',point_role:role,point_group:axis+'.'+group,hit_path_px:points,style:{fill_color:[0,0,0,1]}});
const line=(n,points,extra={},axis='axes_0')=>({key:axis+'.line_'+n,kind:'line',hit_path_px:points,style:{color:'#777777'},...extra});
function groups(targets,component_groups=[]){ctx.result={dpi:72,targets,component_groups};return JSON.parse(JSON.stringify(vm.runInContext('buildConnectionGroups(result)',ctx))).map(g=>g.members.sort());}
const clouds=[dot('collection_0','category_0',[[0,10],[0,20],[0,30]]),dot('collection_1','category_1',[[100,15],[100,25],[100,35]])];
let found=groups([...clouds,line(0,[[0,10],[100,15]]),line(1,[[0,20],[100,25]])]);
assert.deepEqual(found,[['axes_0.line_0','axes_0.line_1']]);
found=groups([...clouds,line(0,[[0,10],[100,15]]),line(1,[[0,20],[100,25]]),
 line(2,[[0,12],[100,18]]),line(3,[[0,10],[100,15]],{group_key:'axes_0.box_0'}),
 line(4,[[0,10],[100,15]],{added_id:'manual'}),line(5,[[0,10],[0,20],[100,20],[100,15]]),
 line(6,[[0,20],[100,25]],{style:{color:'#000000'}}),dot('line_6','summary',[[0,20],[100,25]],'axes_0','mean')]);
assert.deepEqual(found,[['axes_0.line_0','axes_0.line_1']]);
found=groups([...clouds,line(0,[[0,10],[100,15]]),line(1,[[0,20],[100,25]]),
 dot('collection_2','category_2',[[200,10],[200,20]]),dot('collection_3','category_3',[[300,15],[300,25]]),
 line(7,[[200,10],[300,15]]),line(8,[[200,20],[300,25]])]);
assert.equal(found.length,2);assert(found.every(group=>group.length===2));
found=groups([...clouds,
 line(0,[[0,10],[100,15]],{label:'A',style:{color:'#ff0000'}}),line(1,[[0,20],[100,25]],{style:{color:'#ff0000'}}),
 line(2,[[0,10],[100,15]],{label:'B',style:{color:'#0000ff'}}),line(3,[[0,30],[100,35]],{style:{color:'#0000ff'}})]);
assert.deepEqual(found,[['axes_0.line_0','axes_0.line_1'],['axes_0.line_2','axes_0.line_3']]);
found=groups([...clouds,line(0,[[0,10],[100,15]]),line(1,[[0,20],[100,25]]),
 dot('collection_0','category_0',[[0,10],[0,20]],'axes_1'),dot('collection_1','category_1',[[100,15],[100,25]],'axes_1'),
 line(0,[[0,10],[100,15]],{},'axes_1'),line(1,[[0,20],[100,25]],{},'axes_1')]);
assert.equal(found.length,2);assert(found.every(group=>new Set(group.map(k=>k.split('.')[0])).size===1));
found=groups([dot('collection_0','a',[[10,0],[20,0]]),dot('collection_1','b',[[15,100],[25,100]]),line(0,[[10,0],[15,100]]),line(1,[[20,0],[25,100]])]);
assert.deepEqual(found,[['axes_0.line_0','axes_0.line_1']]);
console.log('PASS: linked observation strokes recognized; means, box parts, manual lines and brackets excluded; categories, labels and axes remain separate; horizontal plots supported.');

found=groups([line(0,[[0,10],[100,15]],{connection_members:['axes_0.line_0','axes_0.line_1']}),line(1,[[0,20],[100,25]],{connection_members:['axes_0.line_0','axes_0.line_1']})]);
assert.deepEqual(found,[['axes_0.line_0','axes_0.line_1']]);
const updateSource=source.slice(source.indexOf('function updateComponents('),source.indexOf('const openBasicInspector='));
const point={key:'axes_0.line_0.points_regular',owner_key:'axes_0.line_0',point_role:'regular',style:{fill_color:[1,0,0,.4],edge_color:[0,0,0,.8],linewidth:2}};
const editContext=vm.createContext({
  baseInteractiveStyle:{component_styles:{}},componentSelection:new Set(),
  stylePreviewData:{_rawTargets:[point]},styleSeriesStyles:{'axes_0.line_1':{color:'#aaaaaa',linewidth:1}},
  connectionGroupForMember:key=>['axes_0.line_0','axes_0.line_1'].includes(key)?{members:['axes_0.line_0','axes_0.line_1']}:null,
  componentColorHex:color,pointTargetForKey:()=>null,statisticalGroupForMember:()=>null,
  $:()=>null,selectedTextKey:null,offlineComponentPreview:()=>{},scheduleInteractiveStylePreview:()=>{}
});
vm.runInContext(updateSource,editContext);
for(const [property,value]of [['color','#123456'],['linewidth',3],['linestyle','--'],['alpha',.5]]){
  editContext.property=property;editContext.value=value;
  vm.runInContext("updateComponents(property,value,['axes_0.line_0'])",editContext);
  const styles=editContext.baseInteractiveStyle.component_styles;
  assert.equal(styles['axes_0.line_0'][property],value);assert.equal(styles['axes_0.line_1'][property],value);
  assert.equal(styles['axes_0.line_2'],undefined);
}
const marker=editContext.baseInteractiveStyle.component_styles[point.key];
assert.equal(marker.fill_color,'#ff0000');assert.equal(marker.edge_color,'#000000');assert.equal(marker.fill_alpha,.4);assert.equal(marker.edge_alpha,.8);assert.equal(marker.linewidth,2);
console.log('PASS: reported paired strokes link; editing one updates all family strokes while preserving marker colors, opacity and width.');
