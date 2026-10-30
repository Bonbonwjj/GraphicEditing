"""Small, deterministic presentation controls shared by all chart adapters."""
import ast
import json
import re

MARKER_START = '# --- PLOT_FORGE_INTERACTIVE_STYLE_START ---'
MARKER_END = '# --- PLOT_FORGE_INTERACTIVE_STYLE_END ---'
LOCATIONS = {'best','upper right','upper left','lower left','lower right','right',
             'center left','center right','lower center','upper center','center'}


def validate_style(value):
    if not isinstance(value, dict):
        raise ValueError('交互样式必须是对象')
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
        if not isinstance(key,str) or not re.fullmatch(r'axes_\d+\.line_\d+',key) or not isinstance(spec,dict):
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
        allowed={'border_width','border_color','font_size','grid','title','xlabel','ylabel','legend_location','legend_visible'}
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
            if name in ('title','xlabel','ylabel') and (not isinstance(item,str) or len(item)>300): raise ValueError('子图文字无效')
            axis_spec[name]=float(item) if name in ('border_width','font_size') and item is not None else item
        clean_axes[key]=axis_spec
    labels={key:value.get(key) for key in ('title','xlabel','ylabel')}
    if any(text is not None and (not isinstance(text,str) or len(text)>300) for text in labels.values()):
        raise ValueError('标题或坐标轴名称过长')
    return {'border_width':float(width),'border_color':border_color,
            'legend_location':location,'legend_names':names,
            'line_width':None if line_width is None else float(line_width),
            'line_color':line_color or None,
            'marker_size':None if marker_size is None else float(marker_size),
            'font_size':None if font_size is None else float(font_size),
            'grid':grid,'legend_visible':legend_visible,
            'legend_anchor':list(legend_anchor) if legend_anchor is not None else None,
            'series_styles':clean_series,'axes_styles':clean_axes,**labels}


def apply_interactive_style(figure, style):
    style = validate_style(style)
    for axis_index,axis in enumerate(figure.axes):
        axis_style=style['axes_styles'].get(f'axes_{axis_index}',{})
        for spine in axis.spines.values():
            spine.set_linewidth(axis_style.get('border_width',style['border_width']))
            spine.set_edgecolor(axis_style.get('border_color',style['border_color']))
        for line_index,line in enumerate(axis.lines):
            if style['line_width'] is not None: line.set_linewidth(style['line_width'])
            if style['line_color'] is not None: line.set_color(style['line_color'])
            if style['marker_size'] is not None: line.set_markersize(style['marker_size'])
            selected=style['series_styles'].get(f'axes_{axis_index}.line_{line_index}',{})
            if selected.get('linewidth') is not None: line.set_linewidth(selected['linewidth'])
            if selected.get('color') is not None: line.set_color(selected['color'])
            if selected.get('markersize') is not None: line.set_markersize(selected['markersize'])
        font_size=axis_style.get('font_size',style['font_size'])
        if font_size is not None:
            axis.tick_params(labelsize=font_size)
            for text in (axis.title,axis.xaxis.label,axis.yaxis.label): text.set_fontsize(font_size)
            for text in axis.texts: text.set_fontsize(font_size)
        axis.grid(axis_style.get('grid',style['grid']))
        title=axis_style.get('title',style['title']); xlabel=axis_style.get('xlabel',style['xlabel']); ylabel=axis_style.get('ylabel',style['ylabel'])
        if title is not None: axis.set_title(title)
        if xlabel is not None: axis.set_xlabel(xlabel)
        if ylabel is not None: axis.set_ylabel(ylabel)
        handles, labels = axis.get_legend_handles_labels()
        legend = axis.get_legend()
        legend_visible=axis_style.get('legend_visible',style['legend_visible'])
        legend_location=axis_style.get('legend_location',style['legend_location'])
        if not legend_visible:
            if legend is not None: legend.remove()
        elif handles or legend is not None:
            mapped = [style['legend_names'].get(label,label) for label in labels]
            if handles:
                legend=axis.legend(handles,mapped,loc=legend_location)
            elif legend is not None:
                legend.set_loc(legend_location)
            if legend is not None and style['legend_anchor'] is not None:
                legend.set_bbox_to_anchor(style['legend_anchor'],transform=figure.transFigure)


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
