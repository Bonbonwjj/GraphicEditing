const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../static/app.js'),'utf8');
const from=source.indexOf('async function loadCard('),to=source.indexOf('async function preview(',from);
const slot={innerHTML:'',children:[],append(node){this.children.push(node);}};
const context={state:{galleryVersion:1},projectInfo:()=>({chart_warnings:{fig4:'Traceback\nAssertionError: layout overlap'}}),
  document:{createElement:()=>({})},fetchGalleryImage:()=>{throw Error('Must not retry failed previews automatically');}};
const load=vm.runInNewContext(source.slice(from,to)+'\nloadCard',context);
(async()=>{
 await load({card:{dataset:{},querySelector:()=>slot},project:'jiahui',chart:'fig4',version:1});
 assert(slot.innerHTML.includes('导入成功'));
 assert(slot.innerHTML.includes('尚无可用预览'));
 assert(!slot.innerHTML.includes('<img'));
 assert(slot.children[0].textContent.includes('AssertionError: layout overlap'));
 let requested=0;
 context.projectInfo=()=>({chart_warnings:{fig4:'原布局检查未通过'},chart_diagnostic_previews:['fig4']});
 context.state.previews=new Map();
 context.fetchGalleryImage=async()=>{requested++;return {};};
 context.URL={createObjectURL:()=>'/actual-diagnostic.png',revokeObjectURL:()=>{}};
 context.fitChartCanvas=()=>{};
 context.chartEndpoint=()=>'/api/test/preview';
 const notes=[];
 await load({card:{dataset:{},querySelector:selector=>selector==='.chartImage'?slot:null,append:node=>notes.push(node)},project:'jiahui',chart:'fig4',version:1});
 assert.equal(requested,1);
 assert(notes[0].textContent.includes('布局警告预览'));
 assert(slot.children.at(-1).src.includes('actual-diagnostic'));
 console.log('PASS: failed chart remains imported, has an honest placeholder and does not automatically rerun');
})().catch(error=>{console.error(error);process.exitCode=1;});
