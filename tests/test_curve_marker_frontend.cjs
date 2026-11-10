const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/component_editor.js','utf8');
const snippet=source.slice(source.indexOf('function componentMarkerPath('),source.indexOf('const openBasicInspector='));
const paths=[];
const svg={style:{},setAttribute(){},append(node){paths.push(node)},querySelector(selector){return paths.find(p=>'#'+p.id===selector)}};
const host={getBoundingClientRect:()=>({left:0,top:0}),querySelector:()=>svg};
const image={parentElement:host};
const point={key:'axes_0.line_0.points_regular',owner_key:'axes_0.line_0',point_role:'regular',hit_path_px:[[10,20],[20,30]],
  style:{marker_shape:'o',marker_size:6,linewidth:.65,fill_color:[1,1,1,1],edge_color:[.1,.2,.7,1]}};
const ctx=vm.createContext({
  stylePreviewData:{dpi:72,render_size_px:[100,100],component_groups:[{key:'axes_0.group_0',members:['axes_0.line_0'],locked_selection:true,linked_properties:['color']}],
    _rawTargets:[{key:'axes_0.line_0',kind:'line',hit_path_px:[[10,20],[20,30]],style:{color:'#2465b9'}},point]},
  baseInteractiveStyle:{component_styles:{[point.key]:{edge_color:'#2465b9',marker_shape:'s'},'axes_0.line_1.points_regular':{edge_color:'#d37520'}}},
  componentSelection:new Set(['axes_0.group_0']),styleSeriesStyles:{},selectedTextKey:null,
  componentColorHex:value=>Array.isArray(value)?'#'+value.slice(0,3).map(v=>Math.round(v*255).toString(16).padStart(2,'0')).join(''):value,
  componentRgba:value=>Array.isArray(value)?value:null,
  chartImageRect:()=>({left:0,top:0,width:100,height:100}),
  connectionGroupForMember:()=>null,pointTargetForKey:()=>null,statisticalGroupForMember:()=>null,
  $:id=>id==='componentInspector'?null:{},scheduleInteractiveStylePreview:()=>{},
  document:{querySelector:()=>image,createElementNS:()=>({attrs:{},setAttribute(key,value){this.attrs[key]=value},remove(){const i=paths.indexOf(this);if(i>=0)paths.splice(i,1)}})}
});
vm.runInContext(snippet,ctx);
vm.runInContext("updateComponents('color','#33ee11')",ctx);
assert.equal(ctx.baseInteractiveStyle.component_styles[point.key].edge_color,undefined);
let marker=paths.find(path=>path.id==='offline-'+point.key.replace(/[^a-zA-Z0-9_-]/g,'-'));
assert.equal(marker.attrs.stroke,'#33ee11');assert.equal(marker.attrs.fill,'#ffffff');
const previousShape=marker.attrs.d;
vm.runInContext("updateComponents('marker_shape','^')",ctx);
assert.equal(ctx.baseInteractiveStyle.component_styles[point.key].marker_shape,undefined);
marker=paths.find(path=>path.id==='offline-'+point.key.replace(/[^a-zA-Z0-9_-]/g,'-'));
assert(marker.attrs.d.includes('L'));assert.equal((marker.attrs.d.match(/Z/g)||[]).length,2);
assert.notEqual(marker.attrs.d,previousShape);
assert.equal(marker.attrs.stroke,'#33ee11');assert.equal(marker.attrs.fill,'#ffffff');
assert.equal(ctx.baseInteractiveStyle.component_styles['axes_0.line_1.points_regular'].edge_color,'#d37520');
console.log('PASS: group edits clear old marker overrides; immediate preview updates all mean edges/shapes and preserves white fill and the other series.');
