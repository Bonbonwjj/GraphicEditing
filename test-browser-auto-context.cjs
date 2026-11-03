const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({...(process.env.CHROME_EXECUTABLE ? {executablePath:process.env.CHROME_EXECUTABLE} : {}),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.addLocatorHandler(page.locator('#standardizeDialog[open]'),async()=>{
   await page.locator('#standardizeDialog').evaluate(d=>d.close());
  });
  await page.goto('http://127.0.0.1:18765/');await page.waitForFunction(()=>state.projects.some(p=>p.id==='demo'));
  await page.evaluate(()=>{document.querySelectorAll('dialog[open]').forEach(d=>d.close());showProject('demo');});
  await page.evaluate(()=>select('demo','one'));await page.waitForFunction(()=>stylePreviewData?._chart==='one');
  await page.evaluate(()=>{
   document.querySelectorAll('dialog[open]').forEach(d=>d.close());
   const context=chatContext(),session={id:'ses_context_test',project:'demo',status:'open',created_at:Date.now()/1000,
    charts:[{chart:'one',chart_id:'chart-one',display_name:'one'}],references:[],drafts:[],active_drafts:{},
    turns:[{id:'turn-context',user_message:'把箱型图改成小提琴图',operation:'chat_edit',target_panels:{one:'a'},
      results:[{chart:'one',chart_id:'chart-one',status:'needs_context',reason:'需要确认最终坐标与原始数据映射'}]}]};
   storeSession(context,session);state.projectChatLoaded.add('demo');renderChat();
  });
  await page.locator('[data-retry-context]').waitFor({state:'visible'});
  assert.equal(await page.locator('[data-retry-context]').innerText(),'继续自动处理这次修改');
  let submitted,submissionCount=0;
  await page.route('**/chat/sessions/ses_context_test/turns',async route=>{
   submissionCount++;
   submitted=route.request().postDataJSON();
   const session=await page.evaluate(()=>state.chatSessions.get(chatContext().key));
   session.turns.push({id:'continued',user_message:submitted.user_message,operation:'chat_edit',results:[{chart:'one',status:'answer',message:'已继续自动处理'}]});
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(session)});
  });
  await page.locator('[data-retry-context]').click();
  await page.waitForFunction(()=>document.querySelector('#messages')?.textContent.includes('已继续自动处理'));
  assert.equal(submitted.user_message,'把箱型图改成小提琴图');
  assert.deepEqual(submitted.target_panels,{one:'a'});
  await page.evaluate(()=>{
   const session=state.chatSessions.get(chatContext().key);session.turns.splice(1);
   session.turns[0].results=[{chart:'one',status:'cannot_complete',reason:'Candidate includes an unresolved operation'}];
   renderChat();
  });
  assert((await page.locator('#messages').innerText()).includes('你不需要补充技术信息'));
  assert(!(await page.locator('#messages').innerText()).includes('Candidate includes an unresolved operation'));
  await page.locator('[data-retry-context]').click();
  await page.waitForFunction(()=>document.querySelector('#messages')?.textContent.includes('已继续自动处理'));
  assert.equal(submissionCount,2);
  assert.equal(submitted.user_message,'把箱型图改成小提琴图');
  assert.deepEqual(submitted.target_panels,{one:'a'});
  await page.evaluate(()=>{
   const session=state.chatSessions.get(chatContext().key);session.turns.splice(1);
   session.turns[0].results=[{chart:'one',status:'cannot_complete',failure_code:'proposal_not_ready',reason:'平台暂时没能完成这次修改，原图已保留。你不需要补充技术信息。'}];
   renderChat();
  });
  await page.locator('[data-retry-context]').click();
  await page.waitForFunction(()=>document.querySelector('#messages')?.textContent.includes('已继续自动处理'));
  assert.equal(submissionCount,3);
  await page.evaluate(()=>{
   const session=state.chatSessions.get(chatContext().key);session.status='running';session.progress={stage:'repairing_proposal',started_at:Date.now()/1000};renderChat();
  });
  assert((await page.locator('.chatProgress').innerText()).includes('正在自动修正修改方案'));
  assert(await page.locator('[data-retry-context]').isDisabled());
  await page.evaluate(()=>{
   const session=state.chatSessions.get(chatContext().key);session.status='open';delete session.progress;renderChat();
  });
  await page.evaluate(()=>{
   const session=state.chatSessions.get(chatContext().key);
   session.drafts=[{id:'layout-test',chart:'one',chart_id:'chart-one',status:'validation_failed',
    review_blocker:'layout_changed',can_apply:false,can_continue:true,image_url:stylePreviewData.image,
    code:{'charts/one.py':'pass'},summary:'修改图型',reason:'这次修改额外改变了整图大小或子图位置，平台已拦截。'}];
   session.turns[0].results=[{chart:'one',draft_id:'layout-test',status:'validation_failed'}];renderChat();
  });
  assert(await page.locator('[data-draft-action=apply]').isDisabled());
  assert((await page.locator('.draftActionHint').innerText()).includes('额外改变了原排版，已阻止应用'));
  assert.deepEqual(errors,[]);
  console.log('PASS: context-blocked and unresolved-operation turns both have automatic continuation; legacy error translated; original request and panel scope reused without technical input; no actual model request; zero JS errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
