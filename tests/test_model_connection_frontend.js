const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('static/index.html','utf8');
const elements=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],{dataset:{},value:'',textContent:'',classList:{toggle(){}},querySelectorAll(){return[];}}]));
const sandbox={IntersectionObserver:class{observe(){}unobserve(){}},console,Set,Map,Date,JSON,URL,Promise,encodeURIComponent,
 localStorage:{getItem(){return'dark';}},document:{hidden:false,getElementById:id=>elements.get(id),documentElement:{dataset:{}},querySelectorAll:()=>[],addEventListener(){}},setInterval(){},
 fetch:async()=>({ok:true,json:async()=>({status:'connected',message:'模型请求成功',checked_at:1000})})};
let source=fs.readFileSync('static/app.js','utf8');source=source.slice(0,source.indexOf('(async()=>{try{loadModelConfig()'));
vm.runInNewContext(source+'\nglobalThis.app={state,renderModelConnection,refreshModelConnection};',sandbox);
(async()=>{
 const {state,renderModelConnection,refreshModelConnection}=sandbox.app;state.modelConfigured=true;
 await refreshModelConnection();assert.equal(elements.get('modelConfigBadge').textContent,'已连接');
 renderModelConnection({status:'error',message:'HTTP 401'});assert.equal(elements.get('modelConfigBadge').dataset.status,'error');assert.match(elements.get('modelConnectionState').textContent,/401/);
 let release;sandbox.fetch=()=>new Promise(r=>release=r);const pending=refreshModelConnection();state.modelConfigured=false;state.modelConnectionRevision=1;
 renderModelConnection({status:'unconfigured',message:'未配置'});release({ok:true,json:async()=>({status:'connected'})});await pending;
 assert.equal(elements.get('modelConfigBadge').textContent,'未配置');
 state.modelConfigured=true;sandbox.navigator={onLine:false};await refreshModelConnection();assert.equal(elements.get('modelConfigBadge').textContent,'网络离线');
 console.log('PASS: verified/reachable/error states, stale response isolation, immediate offline state.');
})().catch(e=>{console.error(e);process.exitCode=1;});
