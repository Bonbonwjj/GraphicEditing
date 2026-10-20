// Exercise the actual shared-module UI handlers without network or a browser.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('static/index.html','utf8');
const nodes=new Map([...html.matchAll(/id="([^"]+)"/g)].map(match=>[match[1],{
  value:'',checked:false,disabled:false,hidden:false,textContent:'',children:[],
  replaceChildren(...children){this.children=children;},showModal(){this.open=true;},close(){this.open=false;}
}]));
const requests=[];
const sandbox={console,Map,Set,encodeURIComponent,
  document:{getElementById:id=>{assert(nodes.has(id),id);return nodes.get(id);},createElement:tag=>({tag,append(...children){this.children=children;}})},
  state:{projects:[{id:'p',charts:['a','b']}]},reloadProjects:async()=>{},forgetProjectPreviews:()=>{},alertStatus:()=>{},
  api:async(url,options)=>{requests.push({url,options});return url.endsWith('/detail')?{code:'COLOR="blue"',module:{path:'draw.py'},history:[]}:{};}
};
sandbox.window=sandbox;
vm.runInNewContext(fs.readFileSync('static/ly_features.js','utf8')+'\nglobalThis.showTestDraft=showModuleDraft;',sandbox);
(async()=>{
  await sandbox.openSharedModule('p','module_1',{chart:'b',prompt:'Change the shared function',forceAll:true});
  assert.equal(nodes.get('sharedModulePrompt').value,'Change the shared function');
  assert.equal(nodes.get('validationChart').value,'b');
  assert.equal(nodes.get('moduleForceAll').checked,true);
  const draft={id:'draft_1',source:'COLOR="blue"',changed_locations:1,charts:['a','b'],affected_charts:['a','b'],
    requires_data_review:true,limitations:'Review required',checks:[{chart:'a',changed:1,removed:0,added:0,
      axes_changes:0,visibility_changes:0,layout_status:'pass',layout_issues:[]}]};
  sandbox.showTestDraft(draft);
  assert.equal(nodes.get('moduleDataReviewWrap').hidden,false);
  assert(nodes.get('moduleCheckReports').children[0].textContent.includes('数据/几何变化 1'));
  nodes.get('moduleReviewed').checked=true;nodes.get('moduleReviewed').onchange();
  assert.equal(nodes.get('applySharedModule').disabled,true);
  nodes.get('moduleDataReviewed').checked=true;nodes.get('moduleDataReviewed').onchange();
  assert.equal(nodes.get('applySharedModule').disabled,false);
  await nodes.get('applySharedModule').onclick();
  const body=JSON.parse(requests.find(r=>r.url.endsWith('/apply')).options.body);
  assert.equal(body.acknowledge,true);assert.equal(body.acknowledge_data_changes,true);
  await sandbox.openSharedModule('p','module_1');
  assert.equal(nodes.get('moduleForceAll').checked,false);
  assert.equal(nodes.get('moduleDataReviewed').checked,false);
  console.log('PASS: Chat handoff context, conservative full validation, per-chart reports, separate data acknowledgement, reset state.');
})().catch(error=>{console.error(error);process.exitCode=1;});
