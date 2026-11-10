"""Small, deterministic presentation controls shared by all chart adapters."""
import ast
import json
import re

MARKER_START = '# --- PLOT_FORGE_INTERACTIVE_STYLE_START ---'
MARKER_END = '# --- PLOT_FORGE_INTERACTIVE_STYLE_END ---'
LOCATIONS = {'best','upper right','upper left','lower left','lower right','right',
             'center left','center right','lower center','upper center','center'}


def _copy_legend_handle_style(source, proxy):
    for getter, setter in (('get_color','set_color'),('get_linewidth','set_linewidth'),
                           ('get_linestyle','set_linestyle'),('get_marker','set_marker'),
                           ('get_markersize','set_markersize'),
                           ('get_markerfacecolor','set_markerfacecolor'),
                           ('get_markeredgecolor','set_markeredgecolor'),
                           ('get_facecolor','set_facecolor'),('get_edgecolor','set_edgecolor')):
        if hasattr(source,getter) and hasattr(proxy,setter):
            try: getattr(proxy,setter)(getattr(source,getter)())
            except (TypeError, ValueError): pass


def _sync_legend_handles(legend, sources, labels=None, fallback_order=True):
    """Synchronize proxies without confusing duplicate legend labels."""
    proxies=list(legend.legend_handles if hasattr(legend,'legend_handles') else getattr(legend,'legendHandles',[]))
    if labels is None:pairs=zip(sources,proxies)
    else:
        positions={}
        for index,text in enumerate(legend.get_texts()):
            original = proxies[index].get_label() if not fallback_order and index<len(proxies) else text.get_text()
            positions.setdefault(getattr(text,'_plot_forge_source_label',original),[]).append(index)
        matched=[]
        for source,label in zip(sources,labels):
            choices=positions.get(label,[])
            if choices:
                index=choices.pop(0)
                if index<len(proxies):
                    legend.get_texts()[index]._plot_forge_source_label=label
                    matched.append((source,proxies[index]))
        pairs=matched if matched or not fallback_order else zip(sources,proxies)
    for source,proxy in pairs:_copy_legend_handle_style(source,proxy)


def _sync_all_legend_handles(figure):
    """Refresh legend proxies after every artist-level styling path."""
    for axis in figure.axes:
        legend=axis.get_legend()
        if legend is not None:
            sources,labels=axis.get_legend_handles_labels()
            _sync_legend_handles(legend,sources,labels)
    sources=[];labels=[]
    for axis in figure.axes:
        handles,names=axis.get_legend_handles_labels();sources.extend(handles);labels.extend(names)
    for legend in figure.legends:_sync_legend_handles(legend,sources,labels,fallback_order=False)


def validate_style(value):
    if not isinstance(value, dict):
        raise ValueError('交互样式必须是对象')
    from plot_modes import validate_modes, validate_palettes
    plot_palettes = validate_palettes(value.get('plot_mode_palettes', {}))
    plot_modes = validate_modes(value.get('plot_modes', {}))
    auto_range = value.get('auto_range')
    if auto_range is not None:
        if not isinstance(auto_range, dict) or set(auto_range) - {'axis_labels', 'inherited_limits', 'target_kind'}:
            raise ValueError('Invalid automatic range policy')
        if auto_range.get('target_kind') not in (None, 'boxplot', 'violinplot'):
            raise ValueError('Invalid automatic range chart kind')
        labels = auto_range.get('axis_labels')
        if labels is not None and (not isinstance(labels, list) or any(not isinstance(v, str) for v in labels)):
            raise ValueError('Invalid automatic range axes')
        from component_editor import validate_components
        validate_components(auto_range.get('inherited_limits', {}))
    width = value.get('border_width', 1.0)
    border_color = value.get('border_color', '#333333')
    location = value.get('legend_location', 'best')
    names = value.get('legend_names', {})
    line_width = value.get('line_width')
    line_color = value.get('line_color')
    marker_size = value.get('marker_size')
    font_size = value.get('font_size')
    grid = value.get('grid', False)
    legend_visible = value.get('legend_visible', True)
    legend_anchor = value.get('legend_anchor')
    series_styles = value.get('series_styles', {})
    axes_styles = value.get('axes_styles', {})
    if isinstance(width, bool) or not isinstance(width, (int,float)) or not 0 <= width <= 12:
        raise ValueError('边框粗细须为 0～12')
    if not isinstance(border_color,str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',border_color):
        raise ValueError('边框颜色须为 #RRGGBB')
    if location not in LOCATIONS:
        raise ValueError('不支持的图例位置')
    if not isinstance(names,dict) or len(names)>100 or any(
            not isinstance(k,str) or not isinstance(v,str) or len(k)>200 or len(v)>200
            for k,v in names.items()):
        raise ValueError('图例名称映射无效')
    for number,label,low,high in ((line_width,'线条粗细',0,12),(marker_size,'标记大小',0,40),(font_size,'字号',6,48)):
        if number is not None and (isinstance(number,bool) or not isinstance(number,(int,float)) or not low<=number<=high):
            raise ValueError(f'{label}须为 {low}～{high}')
    if line_color not in (None,'') and (not isinstance(line_color,str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',line_color)):
        raise ValueError('线条颜色须为 #RRGGBB')
    if not isinstance(grid,bool) or not isinstance(legend_visible,bool):
        raise ValueError('网格和图例显示设置无效')
    if legend_anchor is not None and (not isinstance(legend_anchor,(list,tuple)) or len(legend_anchor)!=2
            or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not -0.5<=v<=1.5 for v in legend_anchor)):
        raise ValueError('图例拖动位置无效')
    if not isinstance(series_styles,dict) or len(series_styles)>200:
        raise ValueError('线条样式映射无效')
    clean_series={}
    for key,spec in series_styles.items():
        if not isinstance(key,str) or not re.fullmatch(r'axes_\d+\.(?:line|collection|patch)_\d+',key) or not isinstance(spec,dict):
            raise ValueError('线条标识无效')
        series_color=spec.get('color'); series_width=spec.get('linewidth'); series_marker=spec.get('markersize')
        if series_color is not None and (not isinstance(series_color,str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',series_color)):
            raise ValueError('线条颜色无效')
        if series_width is not None and (isinstance(series_width,bool) or not isinstance(series_width,(int,float)) or not 0<=series_width<=12):
            raise ValueError('线条粗细无效')
        if series_marker is not None and (isinstance(series_marker,bool) or not isinstance(series_marker,(int,float)) or not 0<=series_marker<=40):
            raise ValueError('线条标记大小无效')
        clean_series[key]={'color':series_color,'linewidth':None if series_width is None else float(series_width),
                           'markersize':None if series_marker is None else float(series_marker)}
    if not isinstance(axes_styles,dict) or len(axes_styles)>50:
        raise ValueError('子图样式映射无效')
    clean_axes={}
    for key,spec in axes_styles.items():
        if not isinstance(key,str) or not re.fullmatch(r'axes_\d+',key) or not isinstance(spec,dict):
            raise ValueError('子图标识无效')
        allowed={'border_width','border_color','font_size','grid','title','xlabel','ylabel','legend_location','legend_visible','legend_names','legend_anchor'}
        if any(name not in allowed for name in spec): raise ValueError('子图样式字段无效')
        axis_spec={}
        for name in allowed:
            if name not in spec: continue
            item=spec[name]
            if name=='border_width' and (isinstance(item,bool) or not isinstance(item,(int,float)) or not 0<=item<=12): raise ValueError('子图边框粗细无效')
            if name=='border_color' and (not isinstance(item,str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',item)): raise ValueError('子图边框颜色无效')
            if name=='font_size' and (item is not None and (isinstance(item,bool) or not isinstance(item,(int,float)) or not 6<=item<=48)): raise ValueError('子图字号无效')
            if name=='grid' and not isinstance(item,bool): raise ValueError('子图网格设置无效')
            if name=='legend_visible' and not isinstance(item,bool): raise ValueError('子图图例设置无效')
            if name=='legend_location' and item not in LOCATIONS: raise ValueError('子图图例位置无效')
            if name in ('title','xlabel','ylabel') and item is not None and (not isinstance(item,str) or len(item)>300): raise ValueError('子图文字无效')
            if name in ('legend_names','legend_anchor'): validate_style({name:item})
            axis_spec[name]=float(item) if name in ('border_width','font_size') and item is not None else item
        clean_axes[key]=axis_spec
    spine_styles = value.get('spine_styles', {})
    if not isinstance(spine_styles,dict) or len(spine_styles)>200: raise ValueError('边框样式映射无效')
    for key,spec in spine_styles.items():
        if not isinstance(key,str) or not re.fullmatch(r'axes_\d+\.spine_(?:left|right|top|bottom)',key) or not isinstance(spec,dict) or set(spec)-{'border_width','border_color'}: raise ValueError('边框标识无效')
        if 'border_width' in spec and (isinstance(spec['border_width'],bool) or not isinstance(spec['border_width'],(int,float)) or not 0<=spec['border_width']<=12): raise ValueError('边框粗细无效')
        if 'border_color' in spec and (not isinstance(spec['border_color'],str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',spec['border_color'])): raise ValueError('边框颜色无效')
    text_styles = value.get('text_styles', {})
    if not isinstance(text_styles,dict) or len(text_styles)>500: raise ValueError('文字样式映射无效')
    clean_text = {}
    for key,spec in text_styles.items():
        if not isinstance(key,str) or not re.fullmatch(r'axes_\d+\.(?:xlabel|ylabel|title_\d+|annotation_\d+|legend_text_\d+|[xy]tick_(?:major|minor)_\d+_[12]|[xy]offset)',key) or not isinstance(spec,dict) or set(spec)-{'font_size'}:
            raise ValueError('文字标识无效')
        size=spec.get('font_size')
        if size is not None and (isinstance(size,bool) or not isinstance(size,(int,float)) or not 6<=size<=48): raise ValueError('文字字号无效')
        clean_text[key]={'font_size':size}
    labels={key:value.get(key) for key in ('title','xlabel','ylabel')}
    if any(text is not None and (not isinstance(text,str) or len(text)>300) for text in labels.values()):
        raise ValueError('标题或坐标轴名称过长')
    from component_editor import validate_components
    components=validate_components(value.get('component_styles',{}))
    from drawing_items import validate_items
    added_items=validate_items(value.get('added_items',{}))
    normalized = {'plot_mode_palettes':plot_palettes,'plot_modes':plot_modes,'auto_range':auto_range,'added_items':added_items,'component_styles':components,'border_width':float(width),'border_color':border_color,
            'legend_location':location,'legend_names':names,
            'line_width':None if line_width is None else float(line_width),
            'line_color':line_color or None,
            'marker_size':None if marker_size is None else float(marker_size),
            'font_size':None if font_size is None else float(font_size),
            'grid':grid,'legend_visible':legend_visible,
            'legend_anchor':list(legend_anchor) if legend_anchor is not None else None,
            'series_styles':clean_series,'axes_styles':clean_axes,'text_styles':clean_text,'spine_styles':spine_styles,**labels}
    return {key:item for key,item in normalized.items() if key in value}


def apply_interactive_style(figure, style):
    style = validate_style(style)
    if style.get('plot_modes'):
        from plot_modes import apply_modes
        apply_modes(figure, style['plot_modes'], style.get('plot_mode_palettes'))
    if style.get('auto_range') is not None:
        figure._conversion_range_style = style
        style = apply_conversion_ranges(figure, style)
    if style.get('added_items'):
        from drawing_items import apply_items
        apply_items(figure,style['added_items'])
    for axis_index, axis in enumerate(figure.axes):
        local = {**style, **style.get('axes_styles', {}).get(f'axes_{axis_index}', {})}
        for spine in axis.spines.values():
            if 'border_width' in local: spine.set_linewidth(local['border_width'])
            if 'border_color' in local: spine.set_edgecolor(local['border_color'])
        for name,spine in axis.spines.items():
            spec=style.get('spine_styles',{}).get(f'axes_{axis_index}.spine_{name}',{})
            if 'border_width' in spec: spine.set_linewidth(spec['border_width'])
            if 'border_color' in spec: spine.set_edgecolor(spec['border_color'])
        for index,patch in enumerate(axis.patches):
            spec=style.get('series_styles',{}).get(f'axes_{axis_index}.patch_{index}',{})
            if spec.get('color') is not None: patch.set_facecolor(spec['color'])
            if spec.get('linewidth') is not None: patch.set_linewidth(spec['linewidth'])
        for line_index, line in enumerate(axis.lines):
            values = {name: style.get(key) for name,key in
                      (('linewidth','line_width'),('color','line_color'),('markersize','marker_size'))}
            values.update(style.get('series_styles', {}).get(f'axes_{axis_index}.line_{line_index}', {}))
            for name,value in values.items():
                if value is not None: getattr(line, 'set_'+name)(value)
        from matplotlib.collections import PathCollection
        for index,collection in enumerate(axis.collections):
            spec = style.get('series_styles',{}).get(f'axes_{axis_index}.collection_{index}',{})
            if not isinstance(collection,PathCollection): continue
            if spec.get('color') is not None: collection.set_color(spec['color'])
            if spec.get('linewidth') is not None: collection.set_linewidth(spec['linewidth'])
            if spec.get('markersize') is not None: collection.set_sizes([spec['markersize']**2])
        # Matplotlib legends contain proxy artists copied when legend() is
        # called.  Updating the plotted artist afterwards does not update that
        # copy, so keep each visible proxy in sync with its source series.
        # Match by the stable legend order/label instead of artist indices;
        # this also works when private (``_label``) artists are interleaved.
        legend = axis.get_legend()
        if legend is not None:
            sources, labels = axis.get_legend_handles_labels()
            _sync_legend_handles(legend,sources,labels)
        if local.get('font_size') is not None:
            axis.tick_params(labelsize=local['font_size'])
            for text in (axis.title,axis.xaxis.label,axis.yaxis.label,*axis.texts):
                text.set_fontsize(local['font_size'])
        if 'grid' in local: axis.grid(local['grid'])
        for name in ('title','xlabel','ylabel'):
            if local.get(name) is not None: getattr(axis,'set_'+name)(local[name])
        legend = axis.get_legend()
        if local.get('legend_visible') is False:
            if legend is not None: legend.remove()
            continue
        legend_keys = {'legend_visible','legend_names','legend_location','legend_anchor'}
        if not legend_keys.intersection(local): continue
        if legend is None and local.get('legend_visible') is True:
            handles, labels = axis.get_legend_handles_labels()
            if handles: legend = axis.legend()
        if legend is not None:
            if 'legend_names' in local:
                for text in legend.get_texts():
                    text.set_text(local['legend_names'].get(text.get_text(), text.get_text()))
            if 'legend_location' in local:
                if hasattr(legend,'set_loc'): legend.set_loc(local['legend_location'])
                else:
                    from matplotlib.legend import Legend
                    legend._set_loc(Legend.codes[local['legend_location']])
            if local.get('legend_anchor') is not None:
                legend.set_bbox_to_anchor(local['legend_anchor'],transform=figure.transFigure)

    # Shared paper-figure legends created by fig.legend() are not Axes-owned.
    for legend in list(figure.legends):
        sources=[];labels=[]
        for axis in figure.axes:
            handles,names=axis.get_legend_handles_labels();sources.extend(handles);labels.extend(names)
        _sync_legend_handles(legend,sources,labels,fallback_order=False)
        if style.get('legend_visible') is False:legend.remove();continue
        if 'legend_names' in style:
            for text in legend.get_texts():text.set_text(style['legend_names'].get(text.get_text(),text.get_text()))
        if 'legend_location' in style:
            # Matplotlib rejects loc='best' for figure-level legends.  The
            # sparse default means "keep the renderer's original placement"
            # here; explicit fixed locations remain editable.
            if style['legend_location']=='best':pass
            elif hasattr(legend,'set_loc'):legend.set_loc(style['legend_location'])
            else:
                from matplotlib.legend import Legend
                legend._set_loc(Legend.codes[style['legend_location']])
        if style.get('legend_anchor') is not None:
            legend.set_bbox_to_anchor(style['legend_anchor'],transform=figure.transFigure)

    # Apply text-level overrides last, after any axis-wide settings or legend changes.
    for key,spec in style.get('text_styles',{}).items():
        axis_key,name=key.split('.',1)
        index=int(axis_key[5:])
        if index>=len(figure.axes): continue
        axis=figure.axes[index];text=None
        if name=='xlabel': text=axis.xaxis.label
        elif name=='ylabel': text=axis.yaxis.label
        elif name.startswith('title_'):
            items=[axis.title,axis._left_title,axis._right_title];index=int(name.split('_')[-1])
            if index<len(items): text=items[index]
        elif name.startswith('annotation_'):
            index=int(name.split('_')[-1])
            if index<len(axis.texts): text=axis.texts[index]
        elif name.startswith('legend_text_') and axis.get_legend() is not None:
            items=[axis.get_legend().get_title(),*axis.get_legend().get_texts()];index=int(name.split('_')[-1])
            if index<len(items): text=items[index]
        elif name.endswith('offset'): text=(axis.xaxis if name[0]=='x' else axis.yaxis).get_offset_text()
        elif 'tick_' in name:
            axis_obj=axis.xaxis if name[0]=='x' else axis.yaxis
            _,level,index,side=name.split('_');ticks=axis_obj.get_major_ticks() if level=='major' else axis_obj.get_minor_ticks()
            if int(index)<len(ticks): text=getattr(ticks[int(index)],'label'+side)
        if text is not None and spec.get('font_size') is not None: text.set_fontsize(spec['font_size'])

    if style.get('component_styles'):
        from component_editor import apply_components
        apply_components(figure,style['component_styles'])
    from component_editor import sync_axis_ticks
    sync_axis_ticks(figure,style.get('component_styles',{}))
    # component_styles is applied after the legacy series path.  Legends own
    # copies of their handles, so a final synchronization is required for
    # direct component edits (including linked center-line/uncertainty bands).
    _sync_all_legend_handles(figure)


def apply_conversion_ranges(figure, style):
    """Autoscale converted panels while letting later manual ranges take priority."""
    from component_editor import lock_range_layout
    from matplotlib.ticker import FixedLocator, MaxNLocator, LogLocator, AutoMinorLocator, NullLocator
    policy = style['auto_range']
    labels = policy.get('axis_labels')
    inherited = policy.get('inherited_limits', {})
    components = {key: dict(spec) for key, spec in style.get('component_styles', {}).items()}
    kind = policy.get('target_kind')
    target_type = {'violinplot': 'violin_statistics', 'boxplot': 'box_statistics'}.get(kind)
    targets = [axis for axis in figure.axes if axis.name == 'rectilinear'
               and (labels is None or axis.get_label() in labels)
               and (target_type is None or any(
                   getattr(artist, '_chat_semantic_data', {}).get('type') == target_type
                   for artist in [*axis.lines, *axis.patches, *axis.collections]))]
    if not targets:
        return style
    lock_range_layout(figure)
    for axis in targets:
        key = f'axes_{figure.axes.index(axis)}'
        spec = components.get(key, {})
        position = axis.get_position().frozen()
        axis.set_box_aspect(None)
        axis.set_aspect('auto')
        axis.set_position(position)
        # dataLim already includes collections, error bars and distribution
        # bodies. relim() would discard scatter/collection bounds.
        axis.autoscale(enable=True, axis='both')
        for dimension, sides in (('x', ('bottom', 'top')), ('y', ('left', 'right'))):
            field = dimension + 'lim'
            if field in spec and spec[field] == inherited.get(key, {}).get(field):
                spec.pop(field)
            obj = axis.xaxis if dimension == 'x' else axis.yaxis
            log = getattr(axis, 'get_' + dimension + 'scale')() == 'log'
            labels = [text.get_text().strip() for text in obj.get_ticklabels()]
            try:
                for label in labels:
                    if label: float(label.replace('−', '-'))
                numeric = True
            except ValueError:
                numeric = False
            if isinstance(obj.get_major_locator(), FixedLocator) and (obj.get_converter() if hasattr(obj, 'get_converter') else obj.converter) is None and numeric:
                obj.set_major_locator(LogLocator() if log else MaxNLocator(nbins=5))
            if isinstance(obj.get_minor_locator(), FixedLocator):
                obj.set_minor_locator(NullLocator() if log else AutoMinorLocator())
            if field in spec:
                getattr(axis, 'set_' + field)(spec[field])
            bounds = getattr(axis, 'get_' + field)()
            for side in sides:
                axis.spines[side].set_bounds(*sorted(bounds))
    return {**style, 'component_styles': components}


def finalize_conversion_ranges(figure):
    style = getattr(figure, '_conversion_range_style', None)
    if style is not None:
        apply_conversion_ranges(figure, style)


def prepare_conversion_source(source, baseline, axis_labels=None, target_kind=None):
    """Persist conversion range behavior in candidate and applied chart code."""
    old_style = read_style(baseline)
    style = read_style(source)
    inherited = {key: {field: spec[field] for field in ('xlim', 'ylim') if field in spec}
                 for key, spec in old_style.get('component_styles', {}).items()
                 if re.fullmatch(r'axes_\d+', key)}
    style['auto_range'] = {'axis_labels': axis_labels, 'inherited_limits': inherited, 'target_kind': target_kind}
    return upsert_style(source, style)


def style_block(style):
    return (MARKER_START+'\nINTERACTIVE_STYLE = '+repr(validate_style(style))+'\n'+MARKER_END)


def read_style(source):
    match=re.search(re.escape(MARKER_START)+r'\nINTERACTIVE_STYLE = (.*?)\n'+re.escape(MARKER_END),source,re.S)
    if not match:
        return validate_style({})
    try:
        return validate_style(ast.literal_eval(match.group(1)))
    except (ValueError,SyntaxError):
        raise ValueError('当前交互样式配置无效') from None


def upsert_style(source, style):
    """Add/update controls without rewriting the rest of the chart source."""
    style = validate_style(style)
    block = style_block(style)
    pattern=re.escape(MARKER_START)+r'.*?'+re.escape(MARKER_END)
    has_block=bool(re.search(pattern,source,re.S))
    if has_block:
        source=re.sub(pattern,lambda _:block,source,count=1,flags=re.S)
    import_line='from interactive_style import apply_interactive_style\n'
    lines=source.splitlines(keepends=True)
    parsed=ast.parse(source)
    insert=(parsed.body[0].end_lineno if parsed.body and isinstance(parsed.body[0],ast.Expr)
            and isinstance(parsed.body[0].value,ast.Constant)
            and isinstance(parsed.body[0].value.value,str) else 0)
    # Adapter entries have a stable customization hook.
    if 'def customize(figure):' in source:
        if not has_block:
            source=''.join(lines[:insert])+import_line+block+'\n'+''.join(lines[insert:])
        source=source.replace('def customize(figure):\n    pass',
            'def customize(figure):\n    apply_interactive_style(figure, INTERACTIVE_STYLE)',1)
        if 'apply_interactive_style(figure, INTERACTIVE_STYLE)' not in source.split('def customize(figure):',1)[1]:
            source=source.replace('def customize(figure):',
                'def customize(figure):\n    apply_interactive_style(figure, INTERACTIVE_STYLE)',1)
        return source
    # Ordinary Matplotlib entries: apply immediately before their final output.
    # Migrate old hooks that were placed after save/export. Applying after the
    # image has been written changes the live figure but cannot change preview.
    source=''.join(line for line in source.splitlines(keepends=True)
                   if line.strip()!='apply_interactive_style(plt.gcf(), INTERACTIVE_STYLE)')
    tree=ast.parse(source)
    candidates=[]
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call):
            continue
        name=(node.func.attr if isinstance(node.func,ast.Attribute) else
              node.func.id if isinstance(node.func,ast.Name) else '')
        if name in ('savefig','show','finish_figure','finish_normalized_figure'):
            candidates.append(node.lineno)
    if not candidates:
        raise ValueError('未找到可应用交互样式的绘图输出')
    if not has_block:
        source=''.join(lines[:insert])+import_line+block+'\n'+''.join(lines[insert:])
    lines=source.splitlines(keepends=True)
    tree=ast.parse(source); output_lines=[]
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call):
            continue
        name=(node.func.attr if isinstance(node.func,ast.Attribute) else
              node.func.id if isinstance(node.func,ast.Name) else '')
        if name in ('savefig','show','finish_figure','finish_normalized_figure'):
            output_lines.append(node.lineno)
    line=min(output_lines)-1
    indent=re.match(r'\s*',lines[line]).group(0)
    lines.insert(line,indent+'apply_interactive_style(plt.gcf(), INTERACTIVE_STYLE)\n')
    return ''.join(lines)
