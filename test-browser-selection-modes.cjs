const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({...(process.env.CHROME_EXECUTABLE ? {executablePath:process.env.CHROME_EXECUTABLE} : {}),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
  let previewRequests=0;
  page.on('pageerror',e=>errors.push(e.message));
  await page.addLocatorHandler(page.locator('#standardizeDialog[open]'),async()=>page.locator('#standardizeDialog').evaluate(d=>d.close()));
  page.on('request',r=>{if(r.url().endsWith('/style-preview'))previewRequests++;});
  await page.goto('http://127.0.0.1:18765/');
  await page.waitForFunction(()=>state.projects.some(p=>p.id==='demo'));
  await page.evaluate(()=>{document.querySelectorAll('dialog[open]').forEach(d=>d.close());showProject('demo');});
  await page.evaluate(()=>select('demo','stats'));
  await page.waitForFunction(()=>stylePreviewData?.component_groups?.length===2&&!stylePreviewRunning);
  await page.evaluate(()=>document.querySelectorAll('dialog[open]').forEach(d=>d.close()));
  const lineKey=await page.evaluate(()=>stylePreviewData._rawTargets.find(t=>t.group_key==='axes_0.box_0'&&t.key.includes('.line_')&&t.hit_path_px?.length>=2).key);
  async function point(key,zoom=false){
   if(await page.locator('[data-inspector-close]').count())await page.locator('[data-inspector-close]').click();
   if(!zoom)await page.locator('.chartCard.active img').scrollIntoViewIfNeeded();
   return page.evaluate(({key,zoom})=>{
    const img=document.querySelector(zoom?'[data-subplot-image]':'.chartCard.active img'),r=chartImageRect(img),s=stylePreviewData.render_size_px;
    const path=stylePreviewData._rawTargets.find(t=>t.key===key).hit_path_px,p=[(path[0][0]+path[1][0])/2,(path[0][1]+path[1][1])/2];
    return{x:r.left+p[0]/s[0]*r.width,y:r.bottom-p[1]/s[1]*r.height};
   },{key,zoom});
  }
  async function drag(p){await page.mouse.move(p.x,p.y);await page.mouse.down();await page.mouse.move(p.x+24,p.y-14,{steps:5});await page.mouse.up();}
  assert.equal(await page.locator('[data-component-interaction]').inputValue(),'select');
  assert.equal(await page.locator('[data-component-selection-mode]').inputValue(),'group');
  let p=await point(lineKey);await page.mouse.click(p.x,p.y);
  assert.deepEqual(await page.evaluate(()=>[...componentSelection]),['axes_0.box_0']);
  const baseline=await page.evaluate(()=>JSON.stringify(collectInteractiveStyle())),count=previewRequests;
  p=await point(lineKey);await drag(p);
  await page.waitForTimeout(650);
  assert.equal(await page.evaluate(()=>JSON.stringify(collectInteractiveStyle())),baseline,'locked movement must not change style');
  assert.equal(previewRequests,count,'locked drag must not request a render');
  await page.locator('[data-component-selection-mode]').selectOption('part');
  p=await point(lineKey);await page.mouse.click(p.x,p.y);
  assert.deepEqual(await page.evaluate(()=>[...componentSelection]),[lineKey]);
  await page.locator('#componentInspector').waitFor({state:'visible'});
  assert(await page.locator('[data-component-prop=linewidth]').isVisible());
  await page.locator('[data-inspector-close]').click();
  await page.locator('[data-component-selection-mode]').selectOption('group');
  p=await point(lineKey);await page.mouse.click(p.x,p.y);
  assert.deepEqual(await page.evaluate(()=>[...componentSelection]),['axes_0.box_0']);
  assert.equal(previewRequests,count,'selection mode changes must not render');
  await page.locator('[data-component-interaction]').selectOption('move');
  p=await point(lineKey);await drag(p);
  await page.waitForFunction(()=>!stylePreviewRunning&&!stylePreviewData._dirty&&baseInteractiveStyle.component_styles?.['axes_0.box_0']?.dx>0);
  assert(await page.evaluate(()=>baseInteractiveStyle.component_styles['axes_0.box_0'].dy>0));
  assert.equal(await page.evaluate(key=>baseInteractiveStyle.component_styles?.[key]?.dx,lineKey),undefined);
  await page.evaluate(()=>{selectedAxisKey='axes_0';});
  await page.locator('#zoomSelectedSubplot').click();
  const zoom=page.locator('#subplotZoomDialog');await zoom.waitFor({state:'visible'});
  assert.equal(await zoom.locator('[data-component-interaction]').inputValue(),'move');
  await zoom.locator('[data-component-selection-mode]').selectOption('part');
  assert.equal(await page.locator('[data-component-selection-mode]').first().inputValue(),'part');
  p=await point(lineKey,true);await page.mouse.click(p.x,p.y);
  assert.deepEqual(await page.evaluate(()=>[...componentSelection]),[lineKey]);
  await zoom.locator('[data-component-interaction]').selectOption('select');
  const lockedStyle=await page.evaluate(()=>JSON.stringify(collectInteractiveStyle())),lockedCount=previewRequests;
  p=await point(lineKey,true);await drag(p);await page.waitForTimeout(650);
  assert.equal(await page.evaluate(()=>JSON.stringify(collectInteractiveStyle())),lockedStyle);
  assert.equal(previewRequests,lockedCount);
  await zoom.locator('[data-subplot-close]').click();
  await page.locator('[data-component-interaction]').selectOption('move');
  await page.evaluate(()=>select('demo','two'));
  assert.equal(await page.locator('[data-component-interaction]').inputValue(),'select','opening a chart resets movement lock');
  assert.deepEqual(errors,[]);
  console.log('PASS: default position lock; no render on locked drag or mode switch; whole box vs individual whisker selection; explicit drag moves entire box; zoom controls stay synchronized; opening chart locks movement; zero JS errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
