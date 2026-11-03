const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({...(process.env.CHROME_EXECUTABLE ? {executablePath:process.env.CHROME_EXECUTABLE} : {}),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addLocatorHandler(page.locator('#standardizeDialog[open]'),async()=>page.locator('#standardizeDialog').evaluate(d=>d.close()));
  await page.goto('http://127.0.0.1:18765/');await page.waitForFunction(()=>state.projects.some(p=>p.id==='demo'));
  await page.evaluate(()=>{document.querySelectorAll('dialog[open]').forEach(d=>d.close());showProject('demo');});
  await page.evaluate(()=>select('demo','points'));
  await page.waitForFunction(()=>stylePreviewData?._chart==='points'&&stylePreviewData._rawTargets?.some(t=>t.point_role==='mean'),null,{timeout:90000});
  const source=await page.evaluate(()=>state.detail.code);
  await page.locator('#subplotQuickPick').selectOption('axes_0');
  await page.locator('#subplotZoomDialog [data-component-selection-mode]').selectOption('part');
  const keys=await page.evaluate(()=>Object.fromEntries(['mean','regular','outliers'].map(role=>[role,stylePreviewData._rawTargets.find(t=>t.key.startsWith('axes_0.')&&t.point_role===role&&(role==='mean'||t.owner_key.includes('.collection_'))).key])));
  async function pick(key){
   if(await page.locator('[data-inspector-close]').count())await page.locator('[data-inspector-close]').click();
   const p=await page.evaluate(key=>{const img=document.querySelector('[data-subplot-image]'),r=chartImageRect(img),s=stylePreviewData.render_size_px,t=pointTargetForKey(key),v=t.hit_path_px[0];return{x:r.left+v[0]/s[0]*r.width,y:r.bottom-v[1]/s[1]*r.height};},key);
   await page.mouse.click(p.x,p.y);assert.deepEqual(await page.evaluate(()=>[...componentSelection]),[key]);
  }
  async function settled(key,shape){await page.waitForFunction(({key,shape})=>!stylePreviewRunning&&!stylePreviewData._dirty&&pointTargetForKey(key)?.style.marker_shape===shape,{key,shape},{timeout:90000});}
  const meanShape=await page.evaluate(key=>pointTargetForKey(key).style.marker_shape,keys.mean);
  await pick(keys.mean);await page.locator('[data-component-prop=marker_shape]').selectOption('*');await settled(keys.mean,'*');
  await page.locator('[data-component-prop=marker_shape]').selectOption('');await settled(keys.mean,meanShape);
  await page.locator('[data-component-prop=marker_shape]').selectOption('*');await settled(keys.mean,'*');
  await pick(keys.regular);assert.equal(await page.locator('[data-point-scope]').inputValue(),'group_all');
  await page.locator('[data-component-prop=marker_shape]').selectOption('s');await settled(keys.regular,'s');
  assert.equal(await page.evaluate(key=>pointTargetForKey(key).style.marker_shape,keys.outliers),'s');
  await page.locator('[data-component-prop=fill_color]').fill('#ff0000');
  await page.locator('[data-component-prop=marker_size]').fill('10');
  await page.waitForFunction(key=>!stylePreviewRunning&&!stylePreviewData._dirty&&pointTargetForKey(key)?.style.marker_size===10,keys.regular);
  await page.locator('[data-point-scope]').selectOption('group_all');await settled(keys.outliers,'s');
  assert.equal(await page.evaluate(key=>pointTargetForKey(key).style.marker_shape,keys.mean),'*');
  await pick(keys.outliers);await page.locator('[data-component-prop=marker_shape]').selectOption('^');await settled(keys.outliers,'^');
  await page.locator('[data-component-prop=fill_color]').fill('#00ff00');
  await page.waitForFunction(key=>!stylePreviewRunning&&!stylePreviewData._dirty&&pointTargetForKey(key).style.fill_color[1]===1,keys.outliers);
  assert.equal(await page.evaluate(key=>pointTargetForKey(key).style.marker_shape,keys.regular),'s');
  await page.locator('[data-subplot-picker]').selectOption('axes_1');
  const violin=await page.evaluate(()=>stylePreviewData._rawTargets.find(t=>t.key.startsWith('axes_1.')&&t.point_role==='outliers').key);
  await pick(violin);assert((await page.locator('[data-point-classification]').innerText()).includes('1.5'));
  await page.locator('[data-component-prop=marker_shape]').selectOption('X');await settled(violin,'X');
  assert.equal(await page.evaluate(key=>pointTargetForKey(key).style.marker_shape,keys.outliers),'^');
  const actual=await page.evaluate(()=>fetch(chartEndpoint('demo','points','detail')).then(r=>r.json()).then(r=>r.code));
  assert.equal(actual,source);assert.deepEqual(errors,[]);
  console.log('PASS: independent mean marker shape; ordinary samples update together; outliers remain separate or follow samples on request; box/violin point editing; neighboring axis and source unchanged; zero JS errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
