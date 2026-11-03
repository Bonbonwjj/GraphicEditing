const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({...(process.env.CHROME_EXECUTABLE ? {executablePath:process.env.CHROME_EXECUTABLE} : {}),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:18765/');await page.waitForFunction(()=>state.projects.some(p=>p.id==='demo'));
  await page.evaluate(()=>{document.querySelectorAll('dialog[open]').forEach(d=>d.close());showProject('demo');});
  await page.evaluate(()=>select('demo','violin'));
  await page.waitForFunction(()=>stylePreviewData?._chart==='violin'&&stylePreviewData.component_groups?.length===4&&!stylePreviewRunning);
  await page.evaluate(()=>document.querySelectorAll('dialog[open]').forEach(d=>d.close()));
  const keys=await page.evaluate(()=>{
   const g=stylePreviewData.component_groups.find(g=>g.key==='axes_0.violin_0');
   const cap=g.part_targets.filter(t=>t.key.includes('.segment_')&&t.hit_path_px.length===2&&t.hit_path_px[0][1]===t.hit_path_px[1][1]).sort((a,b)=>b.hit_path_px[0][1]-a.hit_path_px[0][1])[0];
   return{body:g.members.find(k=>!k.includes('.segment_')),cap:cap.key};
  });
  const untouched=await page.evaluate(()=>JSON.stringify(stylePreviewData._rawTargets.filter(t=>t.group_key!=='axes_0.violin_0').map(t=>[t.key,t.style])));
  async function pick(key,zoom=false){
   if(await page.locator('[data-inspector-close]').count())await page.locator('[data-inspector-close]').click();
   if(!zoom)await page.locator('.chartCard.active img').scrollIntoViewIfNeeded();
   const p=await page.evaluate(({key,zoom})=>{const img=document.querySelector(zoom?'[data-subplot-image]':'.chartCard.active img'),r=chartImageRect(img),s=stylePreviewData.render_size_px,t=stylePreviewData._rawTargets.find(t=>t.key===key),path=t.hit_path_px,p=path[key.includes('.segment_')?0:Math.floor(path.length*.2)];return{x:r.left+p[0]/s[0]*r.width,y:r.bottom-p[1]/s[1]*r.height};},{key,zoom});
   await page.mouse.click(p.x,p.y);await page.locator('#componentInspector').waitFor({state:'visible'});
  }
  async function assertWhole(hex){
   const colors=await page.evaluate(()=>{const g=stylePreviewData.component_groups.find(g=>g.key==='axes_0.violin_0');return g.members.map(key=>{const t=stylePreviewData._rawTargets.find(t=>t.key===key);return{key,color:t.style.edgecolor||t.style.color};});});
   for(const item of colors){let c=item.color;if(Array.isArray(c[0]))c=c[0];assert.equal('#'+c.slice(0,3).map(v=>Math.round(v*255).toString(16).padStart(2,'0')).join(''),hex,item.key);}
   assert.equal(await page.evaluate(()=>JSON.stringify(stylePreviewData._rawTargets.filter(t=>t.group_key!=='axes_0.violin_0').map(t=>[t.key,t.style]))),untouched);
  }
  await pick(keys.body);assert.deepEqual(await page.evaluate(()=>[...componentSelection]),['axes_0.violin_0']);
  assert((await page.locator('#componentInspector strong').innerText()).includes('小提琴'));
  await page.locator('[data-component-prop=edge_color]').fill('#ff0000');
  await page.waitForFunction(()=>!stylePreviewRunning&&!stylePreviewData._dirty&&baseInteractiveStyle.component_styles?.['axes_0.violin_0']?.edge_color==='#ff0000');await assertWhole('#ff0000');
  await page.locator('[data-component-selection-mode]').selectOption('part');
  await pick(keys.cap);assert.deepEqual(await page.evaluate(()=>[...componentSelection]),[keys.cap]);
  await page.locator('[data-component-prop=color]').fill('#0066ff');
  await page.waitForFunction(key=>!stylePreviewRunning&&!stylePreviewData._dirty&&baseInteractiveStyle.component_styles?.[key]?.color==='#0066ff',keys.cap);
  assert(await page.evaluate(key=>{const t=stylePreviewData._rawTargets.find(t=>t.key===key);return t.style.color[0]===0&&t.style.color[2]===1;},keys.cap));
  await page.evaluate(()=>{selectedAxisKey='axes_0';});await page.locator('#zoomSelectedSubplot').click();
  await page.locator('#subplotZoomDialog [data-component-selection-mode]').selectOption('group');
  await pick(keys.body,true);assert.deepEqual(await page.evaluate(()=>[...componentSelection]),['axes_0.violin_0']);
  await page.locator('[data-component-prop=edge_color]').fill('#00aa55');
  await page.waitForFunction(()=>!stylePreviewRunning&&!stylePreviewData._dirty&&baseInteractiveStyle.component_styles['axes_0.violin_0'].edge_color==='#00aa55');await assertWhole('#00aa55');
  assert.deepEqual(errors,[]);
  console.log('PASS: violin body and shared summary segments support whole/part selection; whole color reaches every own part; later cap edit affects one segment; focused whole edit wins again; neighboring violin, bars and stems unchanged; zero JS errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
