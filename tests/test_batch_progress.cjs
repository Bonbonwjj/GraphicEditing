const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../static/workspace.js'),'utf8');
const start=source.indexOf('  function batchProgress(');
const end=source.indexOf('  // End batch progress calculation.');
assert.ok(start>=0&&end>start,'progress calculation must be bundled with workspace');
const progress=vm.runInNewContext(source.slice(start,end)+'\nbatchProgress');
const html=fs.readFileSync(require.resolve('../static/index.html'),'utf8');
assert.ok(!html.includes('/static/batch_progress.js'),'must not depend on an unserved asset');
const jobs=['needs_context','failed','working','pending'].map((status,i)=>({id:String(i),status}));
let p=progress({jobs,current:'2'});
assert.equal(p.done,2);assert.equal(p.ready,0);assert.equal(p.current,2);assert.equal(p.issues,2);
assert.match(p.text,/批次 3 \/ 4/);
assert.match(p.text,/含上次结果/);
assert.match(p.text,/重复提交相同源码无法解决/);
p=progress({jobs:[{status:'blocked'},{status:'interrupted'}]});
assert.equal(p.done,0);assert.equal(p.issues,2);
p=progress({phase:'validation',jobs:[{status:'ready'},{status:'validation_failed'}]});
assert.equal(p.done,1);assert.equal(p.total,2);
assert.match(progress({phase:'merge',jobs:[{status:'ready'}]}).stage,/汇总/);
assert.match(progress({installed:true,jobs:[{status:'ready'}]}).stage,/可进入改图/);
assert.equal(progress({jobs:[]}).done,0);
const retry=progress({jobs,current:'2',attempt:{jobs:['2'],returned:[]}});
assert.equal(retry.done,0);assert.equal(retry.progressTotal,1);
assert.match(retry.text,/本轮已返回 0\/1/);
assert.match(progress({jobs:[{id:'a',status:'working',started_at:100}],current:'a'},165).text,/已等待 1 分 5 秒/);
console.log('batch progress tests passed');
const ly1=progress({phase:'analysis',jobs:[
  {id:'a',status:'failed',target_files:['plot_functions_group.py'],reason:'模型请求超时'},
  {id:'b',status:'blocked',target_files:['border_encounters_analyzer.py'],reason:'超过 18 万字符'},
  {id:'c',status:'blocked',target_files:['group_compare_26819.py'],reason:'依赖超限'}]});
assert.match(ly1.stage,/失败／被阻止/);
assert.match(ly1.text,/失败 1 批 · 被阻止 2 批/);
assert.match(ly1.text,/plot_functions_group.py：模型请求超时/);
assert.match(progress({jobs:[{status:'pending_local_run'}]}).stage,/成功.*待本机导出/);
assert.match(progress({jobs:[{status:'failed'}]}).stage,/失败/);
assert.match(progress({jobs:[{status:'blocked'}]}).stage,/被阻止/);
assert.match(progress({phase:'merge',jobs:[],outcome:{status:'failed',label:'失败：汇总失败',reasons:[]}}).stage,/失败：汇总失败/);

// Reopening an existing result must not replace it with a fresh planning view.
(async()=>{
  const from=source.indexOf("  $('workspaceResume').onclick=async()=>{");
  const to=source.indexOf("  $('workspaceAnalyze').onclick=async()=>{",from);
  let planning=0,shown=null;
  let saved={project:'ly1',status:'needs_context',can_open:false,batch:{outcome:{status:'failed_blocked'}}};
  const elements={workspaceRecent:{value:'ly1'},workspaceResume:{},workspaceBatchPlan:{onclick:async()=>planning++}};
  const context={$:id=>elements[id],api:async()=>saved,displayStatus:v=>shown=v,enter:async()=>{},message:()=>{}};
  vm.runInNewContext(source.slice(from,to),context);
  await elements.workspaceResume.onclick();
  assert.equal(planning,0);
  assert.equal(shown.batch.outcome.status,'failed_blocked');
  saved={project:'new',status:'needs_analysis',can_open:false};
  await elements.workspaceResume.onclick();
  assert.equal(planning,1);
  console.log('PASS: saved failure survives reopening; fresh projects still auto-plan');
})().catch(error=>{console.error(error);process.exitCode=1;});
