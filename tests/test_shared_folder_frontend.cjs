const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map();
const node=()=>({children:[],value:'',textContent:'',dataset:{},append(...items){this.children.push(...items)},replaceChildren(){this.children=[];},querySelectorAll(){return[];}});
const element=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
const calls=[];const status={mode:'folder',path:'X:\\figure_DATA_code',available:false,target_ready:true,configured:false,projects:['research'],shared_projects:['research']};
const ctx=vm.createContext({window:{},document:{getElementById:element,createElement:node,createTextNode:text=>({textContent:text})},
  fetch:async url=>{calls.push(url);return{ok:true,json:async()=>status};}});
vm.runInContext(fs.readFileSync('static/collaboration.js','utf8'),ctx);
(async()=>{
 await vm.runInContext('window.syncTeamOnOpen()',ctx);
 assert.deepEqual(calls,['/api/collaboration']);assert(element('teamSyncStatus').textContent.includes('未连接'));
 await vm.runInContext('loadCollaboration()',ctx);
 assert.equal(element('collabEmailRow').hidden,true);assert.equal(element('publishCollaboration').disabled,true);
 assert.equal(element('pullCollaboration').disabled,true);assert.equal(element('connectCollaboration').disabled,false);
 assert.equal(element('collabProjects').children[0].children[0].checked,true);
 status.mode='direct';status.available=true;calls.length=0;
 await vm.runInContext('window.syncTeamOnOpen()',ctx);await vm.runInContext('loadCollaboration()',ctx);
 assert(calls.every(path=>path==='/api/collaboration'));assert.equal(element('teamSyncStatus').textContent,'直接共享工程');
 assert.equal(element('publishCollaboration').hidden,true);assert.equal(element('collabMessageRow').hidden,true);
 assert.equal(element('collabProjectChoices').hidden,true);assert.equal(element('pullCollaboration').textContent,'刷新共享工程');
 console.log('PASS: shared-folder startup does not upload or pull; offline status, project consent and controls stay explicit.');
 console.log('PASS: direct shared editing reads the shared workspace and hides upload/pull-copy controls.');
})().catch(error=>{console.error(error);process.exitCode=1;});
