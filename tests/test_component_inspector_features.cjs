const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/component_editor.js','utf8');
class Element{
  constructor(){this.children=[];this.dataset={};this.style={};this.value='';}
  append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}}
  setAttribute(){} addEventListener(){} closest(){return this.parent;}
  querySelector(selector){if(selector==='.componentInspectorBody')return body;if(selector==='strong')return heading;return null;}
  getBoundingClientRect(){return {height:100,width:100};}
}
const body=new Element(),panel=new Element(),heading=new Element();let basicIds;
const ctx=vm.createContext({document:{createElement:()=>new Element()},window:{innerHeight:1000,innerWidth:1000},
  openComponentInspector:(event,title,ids)=>{body.children=[];basicIds=ids;},
  $:()=>panel,pointTargetForKey:key=>ctx.stylePreviewData._rawTargets.find(t=>t.key===key&&t.point_role),
  connectionGroupForMember:()=>null,statisticalGroupForMember:()=>null,
  state:{project:'p',chart:'c'},selectedSeriesKey:'axes_0.collection_0',selectedAxisKey:'axes_0',
  componentSelectionChart:'p/c',componentSelection:new Set(),componentSelectionMode:'item',
  componentKey:()=>ctx.selectedSeriesKey,componentSelectionHint:()=>'',baseInteractiveStyle:{},
  componentColorHex:()=>null,componentRgba:()=>null,drawComponentSelection(){},addRgbColorControls(){},updateComponents(){},
  stylePreviewData:{_rawTargets:[],component_groups:[]}
});
vm.runInContext(source.slice(source.indexOf('function componentMovementKeys('),source.indexOf('function componentDragKeys(')),ctx);
vm.runInContext(source.slice(source.indexOf('function componentEditableFeatures('),source.indexOf('const attachBasicManipulation=')),ctx);
function inspect(target,group){
  ctx.selectedSeriesKey=group?.key||target.key;ctx.componentSelection=new Set();
  ctx.stylePreviewData={_rawTargets:[target],component_groups:group?[group]:[]};
  ctx.openComponentInspector({clientX:0,clientY:0},'属性',['lineColor','lineWidth','markerSize'],'line');
  return body.children.flatMap(row=>row.children).filter(node=>node.dataset.componentProp);
}
let fields=inspect({key:'axes_0.collection_0',kind:'line_collection',style:{facecolor:[],edgecolor:[[0,0,1,1]]}});
assert(!fields.some(f=>f.dataset.componentProp==='fill_color'));
assert(fields.some(f=>f.dataset.componentProp==='edge_color'));
assert(!basicIds.includes('markerSize'));
fields=inspect({key:'axes_0.line_0',kind:'line',style:{marker:'None'}});
assert(!basicIds.includes('markerSize'));assert(!fields.some(f=>f.dataset.componentProp==='fill_color'));
inspect({key:'axes_0.line_0',kind:'line',style:{marker:'o'}});assert(basicIds.includes('markerSize'));
fields=inspect({key:'axes_0.patch_0',kind:'patch',style:{facecolor:[0,0,1,1]}});
assert(fields.some(f=>f.dataset.componentProp==='fill_color'));
fields=inspect({key:'axes_0.line_0',kind:'line',style:{marker:'o'}},{key:'axes_0.mean_error_0',members:['axes_0.line_0']});
assert(!fields.some(f=>f.dataset.componentProp==='fill_color'));assert(fields.some(f=>f.dataset.componentProp==='marker_size'));
fields=inspect({key:'axes_0.collection_0.points_regular',kind:'scatter',point_role:'regular',style:{marker_shape:'+'}});
const fill=fields.find(f=>f.dataset.componentProp==='fill_color'),shape=fields.find(f=>f.dataset.componentProp==='marker_shape');
assert.equal(fill.closest('label').hidden,true);shape.value='o';shape.onchange();assert.equal(fill.closest('label').hidden,false);
shape.value='x';shape.onchange();assert.equal(fill.closest('label').hidden,true);
ctx.baseInteractiveStyle.component_styles={'axes_0.bar_item_0':{dx:18}};
fields=inspect({key:'axes_0.patch_0',kind:'patch',movement_group:'axes_0.bar_item_0',style:{facecolor:[1,0,0,1]}});
assert.equal(fields.find(field=>field.dataset.componentProp==='dx').value,18);
console.log('PASS: actual inspector hides unsupported fill and marker controls, retains patch fill, and updates point fill availability with shape.');
