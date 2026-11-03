const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({...(process.env.CHROME_EXECUTABLE ? {executablePath:process.env.CHROME_EXECUTABLE} : {}),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addLocatorHandler(page.locator('#standardizeDialog[open]'),async()=>page.locator('#standardizeDialog').evaluate(d=>d.close()));
  await page.goto('http://127.0.0.1:18765/');await page.waitForFunction(()=>state.projects.some(p=>p.id==='demo'));
  await page.evaluate(()=>{document.querySelectorAll('dialog[open]').forEach(d=>d.close());showProject('demo');});
  await page.evaluate(()=>select('demo','connections'));
  await page.waitForFunction(()=>stylePreviewData?._chart==='connections'&&stylePreviewData._connectionGroups?.length===2,null,{timeout:90000});
  const original=await page.evaluate(()=>{const group=stylePreviewData._connectionGroups[0];return{code:state.detail.code,key:group.members[0],members:group.members,
   other:stylePreviewData._rawTargets.filter(t=>!group.members.includes(t.key)).map(t=>[t.key,t.style]),image:stylePreviewData.image};});
  assert.equal(original.members.length,4);
  await page.locator('#subplotQuickPick').selectOption('axes_0');
  if(await page.locator('[data-inspector-close]').count())await page.locator('[data-inspector-close]').click();
  const p=await page.evaluate(key=>{const t=stylePreviewData._rawTargets.find(t=>t.key===key),v=[(t.hit_path_px[0][0]+t.hit_path_px[1][0])/2,(t.hit_path_px[0][1]+t.hit_path_px[1][1])/2],img=document.querySelector('[data-subplot-image]'),r=chartImageRect(img),s=stylePreviewData.render_size_px;return{x:r.left+v[0]/s[0]*r.width,y:r.bottom-v[1]/s[1]*r.height};},original.key);
  await page.mouse.click(p.x,p.y);
  assert((await page.locator('[data-connection-group-info]').innerText()).includes('4'));
  assert.equal(await page.locator('.componentSelectionBox').last().evaluate(el=>getComputedStyle(el).borderTopWidth),'3px');
  assert.equal(await page.locator('.subplotSelectionBox').last().evaluate(el=>getComputedStyle(el).borderTopWidth),'3px');
  await page.locator('[data-component-prop=color]').fill('#ff3300');
  await page.locator('[data-component-prop=linewidth]').fill('2.5');
  await page.locator('[data-line-style]').selectOption('dashed');
  await page.waitForFunction(keys=>!stylePreviewRunning&&!stylePreviewData._dirty&&keys.every(key=>stylePreviewData._rawTargets.find(t=>t.key===key)?.style.linewidth===2.5),original.members,{timeout:90000});
  const changed=await page.evaluate(keys=>keys.map(key=>({style:stylePreviewData._rawTargets.find(t=>t.key===key).style,spec:baseInteractiveStyle.component_styles[key]})),original.members);
  for(const item of changed){assert.equal(item.style.color,'#ff3300');assert.equal(item.spec.linestyle,'dashed');}
  assert.notEqual(await page.evaluate(()=>stylePreviewData.image),original.image);
  assert.deepEqual(await page.evaluate(keys=>stylePreviewData._rawTargets.filter(t=>!keys.includes(t.key)).map(t=>[t.key,t.style]),original.members),original.other);
  // The main properties panel must use the same linked update route.
  await page.evaluate(()=>{document.querySelector('#lineWidth').value='3.5';recordInteractiveChange({target:document.querySelector('#lineWidth')});});
  await page.waitForFunction(keys=>!stylePreviewRunning&&!stylePreviewData._dirty&&keys.every(key=>stylePreviewData._rawTargets.find(t=>t.key===key)?.style.linewidth===3.5),original.members);
  assert.deepEqual(await page.evaluate(keys=>stylePreviewData._rawTargets.filter(t=>!keys.includes(t.key)).map(t=>[t.key,t.style]),original.members),original.other);
  assert.equal(await page.evaluate(()=>fetch(chartEndpoint('demo','connections','detail')).then(r=>r.json()).then(r=>r.code)),original.code);
  assert.deepEqual(errors,[]);
  console.log('PASS: paired-line color/width/dash update together; separate connection family, markers, means and box parts unchanged; both inspectors linked; selection outlines 3px; source unchanged; zero JS errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
