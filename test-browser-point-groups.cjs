const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({...(process.env.CHROME_EXECUTABLE ? {executablePath:process.env.CHROME_EXECUTABLE} : {}),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addLocatorHandler(page.locator('#standardizeDialog[open]'),async()=>page.locator('#standardizeDialog').evaluate(d=>d.close()));
  await page.goto('http://127.0.0.1:18765/');await page.waitForFunction(()=>state.projects.some(p=>p.id==='demo'));
  await page.evaluate(()=>{document.querySelectorAll('dialog[open]').forEach(d=>d.close());showProject('demo');});
  await page.evaluate(()=>select('demo','point_groups'));
  await page.waitForFunction(()=>stylePreviewData?._chart==='point_groups'&&stylePreviewData._rawTargets?.some(t=>t.point_group),null,{timeout:90000});
  const source=await page.evaluate(()=>state.detail.code);
  await page.locator('#subplotQuickPick').selectOption('axes_0');
  await page.locator('#subplotZoomDialog [data-component-selection-mode]').selectOption('part');
  const keys=await page.evaluate(()=>{
   const dots=stylePreviewData._rawTargets.filter(t=>t.owner_key?.startsWith('axes_0.collection_')&&t.point_role);
   const regular=dots.find(t=>t.point_role==='regular'),outlier=dots.find(t=>t.point_role==='outliers'&&t.point_group===regular.point_group);
   return{regular:regular.key,outlier:outlier.key,group:regular.point_group,
    other:stylePreviewData._rawTargets.filter(t=>t.point_role&&t.key.startsWith('axes_0.')&&t.point_group!==regular.point_group).map(t=>[t.key,t.style])};
  });
  async function pick(key){
   if(await page.locator('[data-inspector-close]').count())await page.locator('[data-inspector-close]').click();
   const p=await page.evaluate(key=>{const t=pointTargetForKey(key),v=t.hit_path_px[0],img=document.querySelector('[data-subplot-image]'),r=chartImageRect(img),s=stylePreviewData.render_size_px;return{x:r.left+v[0]/s[0]*r.width,y:r.bottom-v[1]/s[1]*r.height};},key);
   await page.mouse.click(p.x,p.y);assert.deepEqual(await page.evaluate(()=>[...componentSelection]),[key]);
  }
  async function settled(key,shape){await page.waitForFunction(({key,shape})=>!stylePreviewRunning&&!stylePreviewData._dirty&&pointTargetForKey(key)?.style.marker_shape===shape,{key,shape},{timeout:90000});}
  async function unchanged(){assert.deepEqual(await page.evaluate(group=>stylePreviewData._rawTargets.filter(t=>t.point_role&&t.key.startsWith('axes_0.')&&t.point_group!==group).map(t=>[t.key,t.style]),keys.group),keys.other);}
  await pick(keys.regular);
  assert.deepEqual(await page.locator('[data-point-scope] option').evaluateAll(options=>options.map(o=>o.textContent)),['该组所有散点','仅该组离群散点']);
  assert.equal(await page.locator('[data-point-scope]').inputValue(),'group_all');
  assert((await page.locator('[data-point-classification]').innerText()).includes('DIS'));
  await page.locator('[data-component-prop=marker_shape]').selectOption('s');await settled(keys.outlier,'s');await unchanged();
  await page.locator('[data-component-prop=fill_color]').fill('#ff0000');
  await page.waitForFunction(key=>!stylePreviewRunning&&!stylePreviewData._dirty&&pointTargetForKey(key).style.fill_color[0]===1,keys.outlier);await unchanged();
  const before=await page.evaluate(()=>JSON.stringify(collectInteractiveStyle()));
  await page.locator('[data-point-scope]').selectOption('group_outliers');
  assert.equal(await page.evaluate(()=>JSON.stringify(collectInteractiveStyle())),before,'Changing scope must not restyle points');
  await page.locator('[data-component-prop=marker_shape]').selectOption('^');await settled(keys.outlier,'^');
  assert.equal(await page.evaluate(key=>pointTargetForKey(key).style.marker_shape,keys.regular),'s');await unchanged();
  await pick(keys.outlier);assert.equal(await page.locator('[data-point-scope]').inputValue(),'group_outliers');
  await page.locator('[data-component-prop=fill_color]').fill('#00ff00');
  await page.waitForFunction(key=>!stylePreviewRunning&&!stylePreviewData._dirty&&pointTargetForKey(key).style.fill_color[1]===1,keys.outlier);await unchanged();
  const boxState=await page.evaluate(()=>stylePreviewData._rawTargets.filter(t=>t.point_role&&t.key.startsWith('axes_0.')).map(t=>[t.key,t.style]));
  await page.locator('[data-subplot-picker]').selectOption('axes_1');
  const violin=await page.evaluate(()=>{const all=stylePreviewData._rawTargets.filter(t=>t.point_role&&t.owner_key?.startsWith('axes_1.collection_'));const target=all.find(t=>t.point_role==='regular');return{key:target.key,group:target.point_group,other:all.filter(t=>t.point_group!==target.point_group).map(t=>[t.key,t.style])};});
  await pick(violin.key);await page.locator('[data-component-prop=marker_shape]').selectOption('X');await settled(violin.key,'X');
  assert.deepEqual(await page.evaluate(group=>stylePreviewData._rawTargets.filter(t=>t.point_role&&t.owner_key?.startsWith('axes_1.collection_')&&t.point_group!==group).map(t=>[t.key,t.style]),violin.group),violin.other);
  assert.deepEqual(await page.evaluate(()=>stylePreviewData._rawTargets.filter(t=>t.point_role&&t.key.startsWith('axes_0.')).map(t=>[t.key,t.style])),boxState);
  assert.equal(await page.evaluate(()=>fetch(chartEndpoint('demo','point_groups','detail')).then(r=>r.json()).then(r=>r.code)),source);
  assert.deepEqual(errors,[]);
  console.log('PASS: only current category changes in a shared scatter collection; two exact scope choices; outliers can change separately; box/violin and neighboring categories stay isolated; source unchanged; zero JS errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
