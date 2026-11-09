"""Presentation-only component properties and transforms (offsets in points)."""
import math
import re


def validate_components(value):
    if not isinstance(value, dict) or len(value) > 500:
        raise ValueError('组件配置无效')
    allowed = {'dx', 'dy', 'scale', 'color', 'fill_color', 'edge_color', 'linewidth',
               'font_size', 'font_family', 'text', 'hidden', 'linestyle', 'alpha', 'fill_alpha', 'edge_alpha', 'xlim', 'ylim', 'width_scale', 'x_scale', 'y_scale', 'marker_size', 'marker_shape', 'x_tick_length', 'y_tick_length', 'x_tick_width', 'y_tick_width'}
    for key, spec in value.items():
        if not isinstance(key, str) or not re.fullmatch(r'axes_\d+(?:\.(?:(?:box|violin|mean_error|bars|stem|group)_\d+|[xy]axis_text|(?:line_\d+|collection_\d+)(?:\.points_(?:(?:regular|outliers)(?:_g\d+)?|mean_\d+))?|collection_\d+\.segment_\d+|patch_\d+|image_\d+|xlabel|ylabel|title_[012]|annotation_\d+|legend|legend_text_\d+|spine_(?:left|right|top|bottom)|[xy]tick_(?:major|minor)_\d+_[12]|[xy]offset))?', key):
            raise ValueError('组件标识无效')
        if not isinstance(spec, dict) or set(spec) - allowed:
            raise ValueError('组件属性无效')
        for name, item in spec.items():
            if name=='hidden':
                if not isinstance(item,bool): raise ValueError('隐藏设置无效')
            elif name=='linestyle':
                if item not in ('solid','dashed','dotted','dashdot'): raise ValueError('线型无效')
            elif name=='marker_shape':
                from point_components import MARKERS
                if item not in MARKERS:raise ValueError('点形状无效')
            elif name in ('color', 'fill_color', 'edge_color'):
                if not isinstance(item, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', item):
                    raise ValueError('颜色必须为 #RRGGBB')
            elif name in ('font_family', 'text'):
                if not isinstance(item, str) or len(item) > 500:
                    raise ValueError('文字属性无效')
                if name=='font_family':
                    from matplotlib import font_manager
                    try: font_manager.findfont(font_manager.FontProperties(family=[item]),fallback_to_default=False)
                    except ValueError:
                        raise ValueError('字体不可用：'+item+'。请选择本机已安装字体后重试') from None
            elif name in ('xlim', 'ylim'):
                if not isinstance(item, (list, tuple)) or len(item) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in item) or item[0] == item[1]:
                    raise ValueError('坐标范围需要两个不同的有限数值')
            elif isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
                raise ValueError('组件数值无效')
            elif name in ('alpha','fill_alpha','edge_alpha') and not 0<=item<=1:
                raise ValueError('不透明度须为 0～1')
            elif name in ('scale','width_scale','x_scale','y_scale') and not .05 <= item <= 20:
                raise ValueError('缩放倍数须为 0.05～20')
            elif name in ('marker_size','x_tick_length','y_tick_length','x_tick_width','y_tick_width') and not 0<=item<=100:
                raise ValueError('点大小或刻度线尺寸须为 0～100 pt')
            elif name == 'font_size' and not 1 <= item <= 200:
                raise ValueError('字号须为 1～200')
            elif name == 'linewidth' and not 0 <= item <= 50:
                raise ValueError('边框粗细须为 0～50')
            elif name in ('dx', 'dy') and abs(item) > 5000:
                raise ValueError('位移过大')
    return value


def resolve_component(figure, key):
    axis_key, _, name = key.partition('.')
    index = int(axis_key[5:])
    if index >= len(figure.axes):
        return None
    axis = figure.axes[index]
    segment = re.fullmatch(r'collection_(\d+)\.segment_(\d+)', name)
    if segment:
        from matplotlib.collections import LineCollection
        from component_groups import CollectionSegment
        ci, si = map(int, segment.groups())
        if ci < len(axis.collections) and isinstance(axis.collections[ci], LineCollection) and si < len(axis.collections[ci].get_segments()):
            return CollectionSegment(axis.collections[ci], si)
        return None
    if not name: return axis
    if name == 'xlabel': return axis.xaxis.label
    if name == 'ylabel': return axis.yaxis.label
    if name == 'legend': return axis.get_legend()
    if name.startswith('spine_'): return axis.spines.get(name[6:])
    for prefix, items in (('line_', axis.lines), ('collection_', axis.collections),
                          ('patch_', axis.patches), ('image_', axis.images), ('annotation_', axis.texts),
                          ('title_', [axis.title, axis._left_title, axis._right_title])):
        if name.startswith(prefix):
            index = int(name[len(prefix):])
            return items[index] if index < len(items) else None
    if name.startswith('legend_text_') and axis.get_legend() is not None:
        items = [axis.get_legend().get_title(), *axis.get_legend().get_texts()]
        index = int(name[12:])
        return items[index] if index < len(items) else None
    if name.endswith('offset'): return (axis.xaxis if name[0] == 'x' else axis.yaxis).get_offset_text()
    if 'tick_' in name:
        _, level, index, side = name.split('_')
        obj = axis.xaxis if name[0] == 'x' else axis.yaxis
        ticks = obj.get_major_ticks() if level == 'major' else obj.get_minor_ticks()
        return getattr(ticks[int(index)], 'label' + side) if int(index) < len(ticks) else None


def apply_components(figure, value):
    from matplotlib.axes import Axes
    from matplotlib.text import Text
    from matplotlib.legend import Legend
    from matplotlib.collections import PathCollection
    from matplotlib.transforms import Affine2D
    from matplotlib.patches import Patch
    value = validate_components(value)
    point_specs={key:dict(spec) for key,spec in value.items() if '.points_' in key}
    value={key:spec for key,spec in value.items() if '.points_' not in key}
    install_layout_tracking()
    # Change limits before constructing tick overrides, because the locator may
    # create a different set of ticks for the new interval.
    from matplotlib.ticker import FixedLocator, MaxNLocator, LogLocator, AutoMinorLocator, NullLocator
    for key,spec in value.items():
        if not re.fullmatch(r'axes_\d+',key): continue
        axis=resolve_component(figure,key)
        if axis is None: continue
        for field in ('xlim','ylim'):
            if field not in spec: continue
            dimension=field[0];axis_obj=axis.xaxis if dimension=='x' else axis.yaxis
            log=getattr(axis,'get_'+dimension+'scale')()=='log'
            if log and min(spec[field])<=0: raise ValueError('对数坐标范围必须大于零')
            old_locator=axis_obj.get_major_locator()
            count=max(2,min(10,len(axis_obj.get_majorticklocs())-1))
            getattr(axis,'set_'+field)(spec[field])
            if isinstance(old_locator,FixedLocator):
                axis_obj.set_major_locator(LogLocator() if log else MaxNLocator(nbins=count,steps=[1,2,2.5,5,10]))
            if isinstance(axis_obj.get_minor_locator(),FixedLocator):
                axis_obj.set_minor_locator(NullLocator() if log else AutoMinorLocator())
            for name in (('bottom','top') if dimension=='x' else ('left','right')):
                axis.spines[name].set_bounds(*sorted(spec[field]))
    value={key:dict(spec) for key,spec in value.items()}
    for key,spec in list(value.items()):
        if '.spine_' in key and 'scale' in spec:
            axis_key,side=key.split('.spine_');field='x_scale' if side in ('bottom','top') else 'y_scale'
            value.setdefault(axis_key,{})[field]=spec.pop('scale')
    from component_groups import component_groups, artist_key, artist_points
    groups=component_groups(figure)
    expanded={}
    figure.canvas.draw()
    for key,spec in value.items():
        if key.endswith(('xaxis_text','yaxis_text')):
            axis=figure.axes[int(key.split('.')[0][5:])];dimension=key.split('.')[1][0]
            axis_obj=axis.xaxis if dimension=='x' else axis.yaxis
            if 'color' in spec: axis.tick_params(axis=dimension,which='both',colors=spec['color'])
            for level,ticks in (('major',axis_obj.get_major_ticks()),('minor',axis_obj.get_minor_ticks())):
                for i,tick in enumerate(ticks):
                    for side in ('1','2'): expanded[f'{key.split(".")[0]}.{dimension}tick_{level}_{i}_{side}']=dict(spec)
        elif key in groups:
            import numpy as np
            members=groups[key];points=[artist_points(obj,figure.canvas.get_renderer()) for obj in members]
            valid=[p[np.isfinite(p).all(axis=1)] for p in points if len(p)]
            all_points=np.concatenate(valid) if valid else np.zeros((1,2))
            center=(all_points.min(axis=0)+all_points.max(axis=0))/2/figure.dpi
            for obj in members:
                member_key=artist_key(figure,obj)
                if member_key is None: continue
                local=dict(spec)
                from matplotlib.collections import PathCollection
                if 'marker_size' in local and not isinstance(obj,PathCollection) and not any(getattr(c,'lines',(None,))[0] is obj for c in obj.axes.containers): local.pop('marker_size')
                distribution='.box_' in key or '.violin_' in key
                orientation=getattr(obj.axes,'_component_violin_dimensions' if '.violin_' in key else '_component_box_dimensions',[])
                horizontal=distribution and int(key.split('_')[-1])<len(orientation) and orientation[int(key.split('_')[-1])]=='y'
                width=spec.get('width_scale',1) if distribution else 1
                sx=spec.get('scale',1)*(1 if horizontal else width);sy=spec.get('scale',1)*(width if horizontal else 1)
                local['_sx']=sx;local['_sy']=sy
                if sx!=1 or sy!=1:
                    pts=artist_points(obj,figure.canvas.get_renderer());pts=pts[np.isfinite(pts).all(axis=1)]
                    if len(pts):
                        c=(pts.min(axis=0)+pts.max(axis=0))/2/figure.dpi
                        local['dx']=spec.get('dx',0)+(c[0]-center[0])*(sx-1)*72
                        local['dy']=spec.get('dy',0)+(c[1]-center[1])*(sy-1)*72
                expanded[member_key]=local
        else: expanded[key]={**expanded.get(key,{}),**spec}
    # Explicit individual text overrides take precedence over whole-axis defaults.
    for key,spec in value.items():
        if key not in groups and not key.endswith(('xaxis_text','yaxis_text')): expanded[key]={**expanded.get(key,{}),**spec}
    value=expanded
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    for key, spec in sorted(value.items(), key=lambda item: '.segment_' in item[0]):
        obj = resolve_component(figure, key)
        if obj is None: continue
        if 'hidden' in spec: obj.set_visible(not spec['hidden'])
        if 'linestyle' in spec and hasattr(obj,'set_linestyle'): obj.set_linestyle(spec['linestyle'])
        for field, setter in (('color', 'set_color'), ('fill_color', 'set_facecolor'),
                              ('edge_color', 'set_edgecolor'), ('linewidth', 'set_linewidth')):
            if field in spec and hasattr(obj, setter): getattr(obj, setter)(spec[field])
            elif field=='edge_color' and field in spec and hasattr(obj,'set_color'): obj.set_color(spec[field])
        from matplotlib.lines import Line2D
        if isinstance(obj,Line2D):
            cap_color=spec.get('edge_color',spec.get('color'))
            if cap_color is not None: obj.set_markeredgecolor(cap_color)
            if 'color' in spec: obj.set_markerfacecolor(spec['color'])
            if 'linewidth' in spec: obj.set_markeredgewidth(spec['linewidth'])
        if 'marker_size' in spec:
            if isinstance(obj,PathCollection): obj.set_sizes([spec['marker_size']**2])
            elif hasattr(obj,'set_markersize'): obj.set_markersize(spec['marker_size'])
        apply_opacity(obj,spec)
        tick_match=re.fullmatch(r'(axes_\d+)\.([xy])tick_(major|minor)_(\d+)_[12]',key)
        if tick_match and 'color' in spec:
            axis=figure.axes[int(tick_match[1][5:])];axis_obj=axis.xaxis if tick_match[2]=='x' else axis.yaxis
            ticks=axis_obj.get_major_ticks() if tick_match[3]=='major' else axis_obj.get_minor_ticks()
            if int(tick_match[4])<len(ticks):
                for line in (getattr(ticks[int(tick_match[4])],'tick'+key[-1]+'line'),):
                    line.set_color(spec['color']);line.set_markeredgecolor(spec['color'])
        if isinstance(obj, Text):
            if 'text' in spec: obj.set_text(spec['text'])
            if 'font_family' in spec: obj.set_fontfamily(spec['font_family'])
            if 'font_size' in spec: obj.set_fontsize(spec['font_size'])
        dx, dy, scale = spec.get('dx', 0) / 72, spec.get('dy', 0) / 72, spec.get('scale', 1)
        if isinstance(obj, Axes):
            if any(k in spec for k in ('dx', 'dy', 'scale','x_scale','y_scale')):
                obj._component_axis_layout=dict(spec)
                apply_axis_layout(obj)
            continue
        if isinstance(obj, Legend):
            box = obj.get_window_extent(renderer).transformed(figure.dpi_scale_trans.inverted())
            obj.set_bbox_to_anchor((box.x0 + dx, box.y0 + dy), transform=figure.dpi_scale_trans)
            obj.set_loc('lower left') if hasattr(obj, 'set_loc') else obj._set_loc(3)
            for text in obj.get_texts(): text.set_fontsize(text.get_fontsize()*scale)
            continue
        if not any(k in spec for k in ('dx', 'dy', 'scale','width_scale','_sx','_sy')): continue
        obj.set_clip_on(False)
        if isinstance(obj, Text):
            obj.set_fontsize(obj.get_fontsize()*scale)
            affine = Affine2D().translate(dx, dy)
        else:
            if isinstance(obj, PathCollection):
                points = obj.get_offset_transform().transform(obj.get_offsets())
                cx, cy = points.mean(axis=0) / figure.dpi if len(points) else (0, 0)
                obj.set_sizes(obj.get_sizes()*scale*scale)
            else:
                points=artist_points(obj,renderer);points=points[__import__('numpy').isfinite(points).all(axis=1)]
                if not len(points): continue
                center=(points.min(axis=0)+points.max(axis=0))/2/figure.dpi
                cx,cy=center
            affine = Affine2D().translate(-cx, -cy).scale(spec.get('_sx',scale),spec.get('_sy',scale)).translate(cx+dx, cy+dy)
        original = obj.get_offset_transform() if isinstance(obj, PathCollection) else obj.get_data_transform() if isinstance(obj, Patch) else obj.get_transform()
        transform = original + figure.dpi_scale_trans.inverted() + affine + figure.dpi_scale_trans
        if isinstance(obj, PathCollection): obj.set_offset_transform(transform)
        else: obj.set_transform(transform)


    if point_specs:
        from point_components import apply_points
        apply_points(figure,point_specs)
    sync_axis_ticks(figure,value)


def sync_axis_ticks(figure,value=None):
    value=value or {}
    # Tick strokes belong to their axis spine; text colors are independent.
    for ai,axis in enumerate(figure.axes):
        spec=value.get(f'axes_{ai}',{})
        for dimension,sides in (('x',('bottom','top')),('y',('left','right'))):
            length=spec.get(dimension+'_tick_length');width=spec.get(dimension+'_tick_width')
            params={}
            if length is not None: params['length']=length
            if width is not None: params['width']=width
            if params: axis.tick_params(axis=dimension,which='both',**params)
            axis_obj=axis.xaxis if dimension=='x' else axis.yaxis
            for tick in [*axis_obj.get_major_ticks(),*axis_obj.get_minor_ticks()]:
                for line,side in zip((tick.tick1line,tick.tick2line),sides):
                    color=axis.spines[side].get_edgecolor()
                    line.set_color(color);line.set_markeredgecolor(color)


def apply_axis_layout(axis):
    spec=getattr(axis,'_component_axis_layout',None)
    if not spec: return
    current=tuple(axis.get_position().bounds)
    # tight_layout may have run after customization. Apply to its latest
    # rectangle, or to the saved unscaled rectangle when already applied.
    base=getattr(axis,'_component_axis_base',current) if current==getattr(axis,'_component_axis_applied',None) else current
    axis._component_axis_base=base
    x,y,width,height=base;fw,fh=axis.figure.get_size_inches()
    sx=spec.get('scale',1)*spec.get('x_scale',1);sy=spec.get('scale',1)*spec.get('y_scale',1)
    axis.set_position([x+spec.get('dx',0)/72/fw+width*(1-sx)/2,
                       y+spec.get('dy',0)/72/fh+height*(1-sy)/2,width*sx,height*sy])
    axis._component_axis_applied=tuple(axis.get_position().bounds)


def install_layout_tracking():
    from matplotlib.figure import Figure
    if getattr(Figure.tight_layout,'_component_layout_tracking',False): return
    original=Figure.tight_layout
    def tight_layout(figure,*args,**kwargs):
        for axis in figure.axes:
            if hasattr(axis,'_component_axis_layout') and tuple(axis.get_position().bounds)==getattr(axis,'_component_axis_applied',None):
                axis.set_position(axis._component_axis_base)
                axis._component_axis_applied=None
        result=original(figure,*args,**kwargs)
        for axis in figure.axes: apply_axis_layout(axis)
        return result
    tight_layout._component_layout_tracking=True
    Figure.tight_layout=tight_layout


def apply_opacity(obj,spec):
    if 'alpha' in spec: obj.set_alpha(spec['alpha'])
    if not any(field in spec for field in ('fill_alpha','edge_alpha')): return
    from matplotlib.colors import to_rgba_array, to_rgba
    from matplotlib.lines import Line2D
    if isinstance(obj,Line2D):
        inherited=obj.get_alpha()
        color=obj.get_color();edge=obj.get_markeredgecolor();face=obj.get_markerfacecolor()
        if isinstance(edge,str) and edge=='auto': edge=color
        if isinstance(face,str) and face=='auto': face=color
        obj.set_alpha(None)
        obj.set_color(to_rgba(color,spec.get('edge_alpha',inherited)))
        obj.set_markeredgecolor(to_rgba(edge,spec.get('edge_alpha',inherited)))
        obj.set_markerfacecolor(to_rgba(face,spec.get('fill_alpha',inherited)))
        return
    if not hasattr(obj,'get_facecolor') or not hasattr(obj,'get_edgecolor'): return
    faces=to_rgba_array(obj.get_facecolor()).copy();edges=to_rgba_array(obj.get_edgecolor()).copy()
    obj.set_alpha(None)
    if 'fill_alpha' in spec and len(faces): faces[:,3]=spec['fill_alpha']
    if 'edge_alpha' in spec and len(edges): edges[:,3]=spec['edge_alpha']
    obj.set_facecolor(faces if hasattr(obj,'get_offsets') else faces[0] if len(faces) else 'none')
    obj.set_edgecolor(edges if hasattr(obj,'get_offsets') else edges[0] if len(edges) else 'none')
