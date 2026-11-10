// Multi-select chart layers follow the currently selected single subplot.
const plotModeNames={boxplot:'箱线图',violinplot:'小提琴图',scatter:'散点图',mean_error:'均值点 ± SEM',mean_line:'分组均值折线',mean_bar:'均值柱形 ± SEM',line:'折线图',histogram_count:'直方图（样本数）',histogram:'直方图（概率密度）',density_count:'密度曲线（估计样本数）',density:'密度曲线（概率密度 KDE）'};
const plotModeOriginalStyles=new Map();
let plotModeChartKey=null;
function plotModeAxisKey(){
  if(!state.chart||!state.detail||!stylePreviewData)return null;
  if(stylePreviewData._project&&stylePreviewData._project!==state.project)return null;
  if(stylePreviewData._chart&&stylePreviewData._chart!==state.chart)return null;
  const selected=[...new Set([...componentSelection].map(key=>key.match(/^axes_\d+/)?.[0]).filter(Boolean))];
  if(selected.length>1)return null;
  return selectedAxisKey||selected[0]||selectedSeriesKey?.match(/^axes_\d+/)?.[0]||null;
}
function installPlotModePicker(bar){
  const picker=document.createElement('details');picker.className='plotModePicker';picker.hidden=true;
  picker.innerHTML='<summary>绘图类型 ▾</summary><div class="plotModeBody"><strong data-plot-mode-target></strong><fieldset data-plot-mode-options><legend>可多选，组合显示</legend></fieldset><p data-plot-mode-note class="dim" role="status"></p><div class="plotModeActions"><button type="button" data-plot-mode-preview class="primary">预览组合</button><button type="button" data-plot-mode-reset>恢复原图型</button><button type="button" data-plot-mode-save>对比并保存</button></div><small>折线/散点保留完整坐标；分布图使用原始观测。箱线、小提琴、分组散点可叠加；直方图：X 轴为原指标，Y 轴为各区间样本数；每条观测对应一人时即为人数。样本数密度曲线用 KDE × 组内样本数 × 区间宽度，表示每区间估计样本数（可为小数），可单独显示或叠加样本数直方图。概率密度不是人数，仅与密度直方图叠加。均值图显示均值，误差线为 SEM。</small></div>';
  bar.querySelector('[data-component-selection-mode]').closest('label').after(picker);
  picker.addEventListener('toggle',()=>{if(picker.open){refreshPlotModePickers();positionPlotModePicker(picker);}});
  picker.querySelector('[data-plot-mode-preview]').onclick=()=>previewPlotModes(picker,false);
  picker.querySelector('[data-plot-mode-reset]').onclick=()=>previewPlotModes(picker,true);
  picker.querySelector('[data-plot-mode-save]').onclick=()=>{picker.open=false;showStyleComparison();};
  return picker;
}
function positionPlotModePicker(picker){
  if(!picker.open)return;
  const body=picker.querySelector('.plotModeBody'),anchor=picker.querySelector('summary').getBoundingClientRect();
  const width=Math.min(380,window.innerWidth-24);
  body.style.width=width+'px';body.style.left=Math.max(12,Math.min(anchor.left,window.innerWidth-width-12))+'px';
  const below=window.innerHeight-anchor.bottom-16;
  const top=below<180?Math.max(12,anchor.top-Math.min(body.scrollHeight,window.innerHeight-24)-6):anchor.bottom+6;
  body.style.top=top+'px';body.style.maxHeight=Math.max(100,window.innerHeight-top-12)+'px';
}
window.addEventListener('resize',()=>document.querySelectorAll('.plotModePicker[open]').forEach(positionPlotModePicker));
document.addEventListener('pointerdown',event=>{for(const picker of document.querySelectorAll('.plotModePicker[open]'))if(!picker.contains(event.target))picker.open=false;});
function restrictPlotModeCombinations(picker,changed=null){
  const inputs=[...picker.querySelectorAll('[data-plot-mode]')];
  const family=input=>['histogram_count','density_count'].includes(input.value)?'count'
    :['histogram','density'].includes(input.value)?'density':'category';
  if(changed?.checked){
    for(const input of inputs)if(family(input)!==family(changed))input.checked=false;
  }
}
function refreshPlotModePickers(){
  const identity=state.project+'/'+state.chart+'/'+(state.detail?.revision||'');
  if(identity!==plotModeChartKey){plotModeOriginalStyles.clear();plotModeChartKey=identity;}
  const key=plotModeAxisKey(),axis=stylePreviewData?.plot_mode_axes?.find(axis=>axis.key===key);
  for(const picker of document.querySelectorAll('.plotModePicker')){
    const supported=[...new Set(axis?.supported||[])].filter(mode=>!axis?.unavailable?.[mode]);
    picker.hidden=!key||!supported.length;picker.dataset.axisKey=key||'';
    if(picker.hidden){picker.open=false;continue;}
    const panel=state.detail?.panel_index?.panels?.find(panel=>panel.axis_labels?.includes(axis?.axis_label));
    const label=(panel?'图 '+panel.id+' · ':'')+(axis?.label||'当前子图');
    picker.querySelector('[data-plot-mode-target]').textContent='当前子图：'+label;
    const field=picker.querySelector('[data-plot-mode-options]');field.replaceChildren();
    const legend=document.createElement('legend');legend.textContent='可多选，组合显示';field.append(legend);
    const selected=baseInteractiveStyle.plot_modes?.[key]??axis?.selected??[];
    for(const mode of supported){
      const row=document.createElement('label'),input=document.createElement('input');
      input.type='checkbox';input.value=mode;input.setAttribute('aria-label',plotModeNames[mode]||mode);input.dataset.plotMode='';input.checked=selected.includes(mode);
      input.onchange=()=>restrictPlotModeCombinations(picker,input);
      row.append(input,document.createTextNode(plotModeNames[mode]||mode));field.append(row);
    }
    restrictPlotModeCombinations(picker);
    picker.querySelector('[data-plot-mode-preview]').disabled=!axis?.supported?.length;
    picker.querySelector('[data-plot-mode-reset]').disabled=!baseInteractiveStyle.plot_modes?.[key];
    picker.querySelector('[data-plot-mode-save]').disabled=!baseInteractiveStyle.plot_modes?.[key];
    picker.querySelector('[data-plot-mode-note]').textContent=
      (axis.group_counts?.length?'各组原始样本数：'+axis.group_counts.join('、'):'使用完整 X/Y 坐标，保持原顺序。')
      +' 仅显示可用图型；选择不兼容的图型会自动取消冲突项。';
  }
}
async function previewPlotModes(plotModePicker,reset=false){
  const key=plotModePicker.dataset.axisKey;
  if(key!==plotModeAxisKey())return;
  if(!key||!state.detail)return;
  const modes=[...plotModePicker.querySelectorAll('[data-plot-mode]:checked')].map(input=>input.value);
  if(!reset&&!modes.length){plotModePicker.querySelector('[data-plot-mode-note]').textContent='请至少勾选一种图型。';return;}
  const identity=state.project+'/'+state.chart+'/'+state.detail.revision;
  if(!reset&&(stylePreviewRunning||stylePreviewQueued||stylePreviewData?._dirty)){
    plotModePicker.querySelector('[data-plot-mode-note]').textContent='正在同步当前组别配色…';
    clearTimeout(stylePreviewTimer);
    await previewInteractiveStyle();
    const deadline=Date.now()+165000;
    while(stylePreviewRunning||stylePreviewQueued){
      if(Date.now()>deadline){plotModePicker.querySelector('[data-plot-mode-note]').textContent='当前配色预览尚未完成，请完成后重试。';return;}
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    if(stylePreviewData?._dirty){plotModePicker.querySelector('[data-plot-mode-note]').textContent='当前修改尚未成功预览，请先处理预览错误。';return;}
  }
  if(identity!==state.project+'/'+state.chart+'/'+state.detail?.revision||key!==plotModeAxisKey())return;
  baseInteractiveStyle.plot_mode_palettes={...(baseInteractiveStyle.plot_mode_palettes||{})};
  if(!reset){
    const palette=stylePreviewData?.plot_mode_axes?.find(axis=>axis.key===key)?.palette;
    if(palette?.length)baseInteractiveStyle.plot_mode_palettes[key]=JSON.parse(JSON.stringify(palette));
  }
  baseInteractiveStyle.plot_modes={...(baseInteractiveStyle.plot_modes||{})};
  const perArtist=new RegExp('^'+key+'\\.(?:line_|collection_|patch_|box_|violin_|points_|mean_error_|bars_|group_|stem_)');
  const components=baseInteractiveStyle.component_styles||{};
  if(!reset&&!plotModeOriginalStyles.has(key)){
    plotModeOriginalStyles.set(key,JSON.parse(JSON.stringify({
      components:Object.fromEntries(Object.entries(components).filter(([name])=>perArtist.test(name)||name===key)),
      series:Object.fromEntries(Object.entries(styleSeriesStyles).filter(([name])=>name.startsWith(key+'.'))),
      axes:styleAxesStyles[key]||{}
    })));
  }
  for(const name of Object.keys(components))if(perArtist.test(name))delete components[name];
  for(const name of Object.keys(styleSeriesStyles))if(name.startsWith(key+'.'))delete styleSeriesStyles[name];
  if(reset){
    delete baseInteractiveStyle.plot_modes[key];
    delete baseInteractiveStyle.plot_mode_palettes[key];
    const original=plotModeOriginalStyles.get(key);
    if(original){Object.assign(components,original.components);Object.assign(styleSeriesStyles,original.series);styleAxesStyles[key]=original.axes;plotModeOriginalStyles.delete(key);}
  }else{
    baseInteractiveStyle.plot_modes[key]=modes;
    if(modes.some(mode=>['histogram_count','density_count','histogram','density'].includes(mode))){
      styleAxesStyles[key]={...(styleAxesStyles[key]||{}),xlabel:null,ylabel:null};
    }
    // Old numerical windows can clip a different mark type. Keep other axis settings.
    if(components[key]){delete components[key].xlim;delete components[key].ylim;}
  }
  baseInteractiveStyle.component_styles=components;
  componentSelection.clear();$('componentInspector')?.remove();
  document.querySelectorAll('.offlineComponentPreview').forEach(node=>node.remove());
  scheduleInteractiveStylePreview(false);
  plotModePicker.querySelector('[data-plot-mode-note]').textContent=reset?'正在恢复原图型…':'正在预览：'+modes.map(mode=>plotModeNames[mode]).join(' + ');
  plotModePicker.querySelector('[data-plot-mode-reset]').disabled=reset;
}

const toolbarBeforePlotModes=componentInteractionToolbar;
componentInteractionToolbar=function(){const bar=toolbarBeforePlotModes();installPlotModePicker(bar);return bar;};
for(const bar of document.querySelectorAll('.componentInteractionToolbar'))installPlotModePicker(bar);
const selectBeforePlotModes=selectSubplot;
selectSubplot=function(...args){const result=selectBeforePlotModes(...args);refreshPlotModePickers();return result;};
const drawSelectionBeforePlotModes=drawComponentSelection;
drawComponentSelection=function(...args){const result=drawSelectionBeforePlotModes(...args);refreshPlotModePickers();return result;};
const attachBeforePlotModes=attachDirectManipulation;
attachDirectManipulation=function(...args){const result=attachBeforePlotModes(...args);refreshPlotModePickers();return result;};
refreshPlotModePickers();

const showProjectBeforePlotModes=showProject;
showProject=function(...args){const result=showProjectBeforePlotModes(...args);refreshPlotModePickers();return result;};
const selectChartBeforePlotModes=select;
select=async function(...args){for(const picker of document.querySelectorAll('.plotModePicker')){picker.hidden=true;picker.open=false;}return selectChartBeforePlotModes(...args);};
