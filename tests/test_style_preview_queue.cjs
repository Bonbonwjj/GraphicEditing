const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/app.js','utf8');
const implementation=source.slice(source.indexOf('async function previewInteractiveStyle('),source.indexOf('async function cancelInteractiveStylePreview('));
function fixture(){
  const image={src:'baseline',getAttribute(){return this.src}},requests=[],status={};
  const slot={querySelector:()=>image},card={dataset:{chart:'fig'},querySelector:selector=>selector==='.chartImage img'?image:slot};
  const ctx=vm.createContext({state:{project:'p',chart:'fig',detail:{revision:'r'}},stylePreviewData:{_dirty:true,image:'baseline',render_size_px:[100,100]},
    stylePreviewRunning:false,stylePreviewQueued:false,stylePreviewNeedsFull:false,stylePreviewHighQuality:false,stylePreviewGeneration:0,
    styleBaselineKey:null,styleBaselineImage:null,stylePreviewTimer:null,style:{color:'red'},
    document:{querySelectorAll:()=>[card],querySelector:()=>null},$:id=>id==='subplotZoomDialog'?{}:status,
    collectInteractiveStyle:()=>ctx.style,chartEndpoint:()=>'/preview',
    fetch:(_url,options)=>new Promise(resolve=>requests.push({body:JSON.parse(options.body),resolve:incoming=>resolve({ok:true,json:async()=>incoming})})),
    attachDirectManipulation:(_img,result)=>ctx.stylePreviewData=result,clearTimeout:()=>{},setTimeout:(_fn,delay)=>{ctx.delay=delay;return 1}
  });
  vm.runInContext(implementation,ctx);return{ctx,requests,image,status};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  for(const lightweight of [true,false]){
    const{ctx,requests,image}=fixture();ctx.stylePreviewNeedsFull=!lightweight;
    const first=ctx.previewInteractiveStyle();ctx.style={color:'blue'};ctx.scheduleInteractiveStylePreview(true);
    requests[0].resolve({image:'outdated',lightweight,preview_dpi:160});await first;await flush();
    assert.equal(image.src,'baseline');assert.equal(requests.length,2);
    assert.equal(requests[1].body.style.color,'blue');assert.equal(requests[1].body.lightweight,lightweight);
    requests[1].resolve({image:'latest',lightweight,preview_dpi:160});await flush();
    assert.equal(image.src,'latest');assert.equal(ctx.stylePreviewData._dirty,false);
  }
  const{ctx,requests}=fixture();
  const hd=ctx.previewInteractiveStyle({highQuality:true});assert.equal(requests[0].body.high_quality,true);
  requests[0].resolve({image:'hd',lightweight:true,preview_dpi:360});await hd;
  ctx.scheduleInteractiveStylePreview(true);assert.equal(ctx.delay,180);
  const edit=ctx.previewInteractiveStyle();assert.equal(requests[1].body.high_quality,false);
  requests[1].resolve({image:'edit',lightweight:true,preview_dpi:160});await edit;
  assert.equal(ctx.stylePreviewData._previewDpi,160);
  const active=fixture();active.image._componentDragging=true;
  const pending=active.ctx.previewInteractiveStyle();active.requests[0].resolve({image:'arrived-during-drag',lightweight:false,preview_dpi:160});await pending;
  assert.equal(active.image.src,'baseline');assert.equal(active.image._deferredStylePreview,true);
  assert.equal(active.ctx.stylePreviewData._dirty,true);assert.equal(active.ctx.stylePreviewNeedsFull,true);
  active.image._componentDragging=false;
  const released=active.ctx.previewInteractiveStyle();active.requests[1].resolve({image:'after-drag',lightweight:false,preview_dpi:160});await released;
  assert.equal(active.image.src,'after-drag');
  console.log('PASS: zoom debounce reduced; stale renders skipped; full hit reports preserved; explicit HD does not slow subsequent edits.');
})().catch(error=>{console.error(error);process.exitCode=1});
