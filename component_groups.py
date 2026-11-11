"""Group native statistical plot artists without rewriting their data."""
import numpy as np
from functools import wraps


def compatible_orientation(callable_, kwargs):
    """Translate Matplotlib's orientation keyword for pre-3.10 releases."""
    import inspect
    kwargs=dict(kwargs)
    if ('orientation' in kwargs and kwargs.get('vert') is not None
            and kwargs['vert'] != (kwargs['orientation']=='vertical')):
        raise ValueError('orientation and vert specify conflicting directions')
    parameters=inspect.signature(callable_).parameters
    if 'orientation' in kwargs and 'orientation' not in parameters and 'vert' in parameters:
        value=kwargs.pop('orientation')
        if value not in ('vertical','horizontal'):
            raise ValueError("orientation must be 'vertical' or 'horizontal'")
        if 'vert' in kwargs and kwargs['vert'] is not None and kwargs['vert'] != (value=='vertical'):
            raise ValueError('orientation and vert specify conflicting directions')
        kwargs['vert']=value=='vertical'
    return kwargs


class CollectionSegment:
    """A selectable presentation layer for one shared LineCollection segment.

    Violin extrema/medians share collections across several violins. Per-segment
    colors, widths and affine transforms keep their original coordinates intact.
    """
    def __init__(self, collection, index):
        self.collection, self.index = collection, index
        self.axes, self.figure = collection.axes, collection.figure

    def get_path(self):
        from matplotlib.path import Path
        return Path(self.collection.get_segments()[self.index])

    def get_transform(self):
        from matplotlib.transforms import Affine2D
        transforms = self.collection.get_transforms()
        prefix = Affine2D(transforms[self.index % len(transforms)]) if len(transforms) else Affine2D()
        return prefix + self.collection.get_transform()

    def set_transform(self, transform):
        from matplotlib.transforms import Affine2D
        original = self.collection.get_transforms()
        count = len(self.collection.get_segments())
        matrices = np.array([original[i % len(original)] if len(original) else Affine2D().get_matrix()
                             for i in range(count)])
        matrices[self.index] = (transform + self.collection.get_transform().inverted()).get_matrix()
        self.collection._transforms = matrices
        self.collection.stale = True

    def _colors(self):
        from matplotlib.colors import to_rgba_array
        colors = to_rgba_array(self.collection.get_edgecolor())
        count = len(self.collection.get_segments())
        return np.array([colors[i % len(colors)] if len(colors) else (0, 0, 0, 0) for i in range(count)])

    def get_color(self): return tuple(self._colors()[self.index])
    def get_edgecolor(self): return self._colors()[self.index:self.index+1]
    def get_facecolor(self): return np.empty((0, 4))
    def set_facecolor(self, color): pass

    def set_edgecolor(self, color):
        from matplotlib.colors import to_rgba_array
        colors = self._colors()
        colors[self.index] = to_rgba_array(color)[0]
        # Materialize effective alpha before clearing a collection-wide alpha.
        self.collection.set_alpha(None)
        self.collection.set_edgecolor(colors)

    set_color = set_edgecolor

    def get_linewidth(self):
        values = self.collection.get_linewidths()
        return float(values[self.index % len(values)])

    def set_linewidth(self, width):
        values = self.collection.get_linewidths()
        widths = [values[i % len(values)] for i in range(len(self.collection.get_segments()))]
        widths[self.index] = width
        self.collection.set_linewidth(widths)

    def set_linestyle(self, style):
        from matplotlib.collections import LineCollection
        values = self.collection.get_linestyles()
        styles = [values[i % len(values)] for i in range(len(self.collection.get_segments()))]
        styles[self.index] = LineCollection([], linestyles=style).get_linestyles()[0]
        self.collection.set_linestyle(styles)

    def get_alpha(self): return None
    def set_alpha(self, alpha):
        if alpha is not None:
            color = list(self.get_color()); color[3] = alpha
            self.set_edgecolor(color)

    def get_visible(self): return self.collection.get_visible() and self.get_color()[3] != 0
    def set_visible(self, visible):
        if not visible: self.set_alpha(0)
    def set_clip_on(self, value): self.collection.set_clip_on(value)

    @property
    def _component_annotation_link(self):return getattr(self.collection,'_component_annotation_links',{}).get(self.index)

    @_component_annotation_link.setter
    def _component_annotation_link(self,model):
        links=getattr(self.collection,'_component_annotation_links',{});links[self.index]=model;self.collection._component_annotation_links=links


class LinePoint:
    """Move one marker/cap in a shared Line2D without changing its coordinates."""
    def __init__(self,line,index):
        self.line,self.index=line,index
        self.axes,self.figure=line.axes,line.figure

    def __getattr__(self,name):return getattr(self.line,name)

    def get_path(self):
        from matplotlib.path import Path
        return Path(self.line.get_xydata()[self.index:self.index+1])

    def get_transform(self):return self.line.get_transform()

    def set_transform(self,transform):
        from component_links import LinkedVertexTransform
        vertices=self.get_path().vertices
        base=self.line.get_transform()
        shift=(transform.transform(vertices)-base.transform(vertices))*72/self.figure.dpi
        self.line.set_transform(LinkedVertexTransform(base,self.figure,vertices,shift))


def _errorbar_centers(error):
    line,_caps,bars=error.lines
    if line is not None:return np.asarray(line.get_xydata())
    if hasattr(error,'_component_centers'):return error._component_centers
    segments=next((bar.get_segments() for bar in bars if len(bar.get_segments())),[])
    return np.asarray([np.mean(segment,axis=0) for segment in segments if len(segment)])


def _errorbar_parts(error,index):
    line,caps,bars=error.lines
    result=[LinePoint(line,index)] if line is not None and index<len(line.get_xydata()) else []
    endpoints=[p for bar in bars if index<len(bar.get_segments()) for p in bar.get_segments()[index]]
    if endpoints:
        endpoints=np.asarray(endpoints)
        for cap in caps:
            for vi,point in enumerate(cap.get_xydata()):
                if np.isclose(point,endpoints,rtol=1e-7,atol=1e-9).all(axis=1).any():result.append(LinePoint(cap,vi))
    result.extend(CollectionSegment(bar,index) for bar in bars if index<len(bar.get_segments()) and len(bar.get_segments()[index]))
    return result


def summary_items(axis):
    """Individual categorical bars/means, including separately drawn error bars."""
    from matplotlib.container import BarContainer,ErrorbarContainer
    errors=[c for c in axis.containers if isinstance(c,ErrorbarContainer)]
    used=set();items=[]
    for ci,container in enumerate(c for c in axis.containers if isinstance(c,BarContainer)):
        horizontal=container.orientation=='horizontal';dimension=0 if horizontal else 1
        for patch in container.patches:
            center=np.array([patch.get_x()+patch.get_width(),patch.get_y()+patch.get_height()/2] if horizontal else [patch.get_x()+patch.get_width()/2,patch.get_y()+patch.get_height()])
            members=[patch]
            for error in errors:
                for index,value in enumerate(_errorbar_centers(error)):
                    if np.allclose(value,center,rtol=1e-7,atol=1e-9):
                        members.extend(_errorbar_parts(error,index));used.add((id(error),index))
            items.append({'name':f'bar_item_{sum(i["kind"]=="bar" for i in items)}','kind':'bar','parent':f'bars_{ci}',
                          'members':members,'region':{'dimension':dimension,'position':float(center[1-dimension]),'mean':float(center[dimension]),'low':None,'high':None,'rule':'display_iqr'}})
    for ci,error in enumerate(errors):
        dimension=0 if error.has_xerr and not error.has_yerr else 1
        for index,center in enumerate(_errorbar_centers(error)):
            if not np.isfinite(center).all():continue
            if (id(error),index) in used:continue
            items.append({'name':f'mean_item_{sum(i["kind"]=="mean" for i in items)}','kind':'mean','parent':f'mean_error_{ci}',
                          'members':_errorbar_parts(error,index),'region':{'dimension':dimension,'position':float(center[1-dimension]),'mean':float(center[dimension]),'low':None,'high':None,'rule':'display_iqr'}})
    from matplotlib.collections import PathCollection
    for item in items:
        r=item['region'];center=np.array([r['position'],r['mean']] if r['dimension']==1 else [r['mean'],r['position']])
        for obj in axis.collections:
            if isinstance(obj,PathCollection) and not getattr(obj,'_component_point_overlay',False):
                offsets=np.asarray(obj.get_offsets())
                if len(offsets)==1 and np.allclose(offsets[0],center,rtol=1e-7,atol=1e-9):
                    obj._component_point_role='mean';item['members'].append(obj)
    return items


def movement_bindings(figure):
    """Movement ownership is finer than container-wide color/style ownership."""
    from matplotlib.container import ErrorbarContainer
    groups=component_groups(figure);owners={};children={}
    for ai,axis in enumerate(figure.axes):
        items=summary_items(axis)
        for item in items:
            key=f'axes_{ai}.{item["name"]}'
            children.setdefault(f'axes_{ai}.{item["parent"]}',[]).append(key)
            for member in item['members']:
                member_key=artist_key(figure,member)
                if member_key:owners.setdefault(member_key,set()).add(key)
                if isinstance(member,LinePoint):owners.setdefault(artist_key(figure,member.line),set()).add(key)
                if isinstance(member,CollectionSegment):owners.setdefault(artist_key(figure,member.collection),set()).add(key)
        for i,error in enumerate(c for c in axis.containers if isinstance(c,ErrorbarContainer)):
            leaves=[f'axes_{ai}.{item["name"]}' for item in items if any(isinstance(obj,LinePoint) and obj.line in error.lines[1] or isinstance(obj,CollectionSegment) and obj.collection in error.lines[2] for obj in item['members'])]
            if leaves:children[f'axes_{ai}.mean_error_{i}']=leaves
    for key,members in groups.items():
        if key in children or '.bar_item_' in key or '.mean_item_' in key:continue
        for member in members:
            name=artist_key(figure,member)
            if name:owners.setdefault(name,set()).add(key)
    for key,leaves in owners.items():
        if len(leaves)>1 and all('.bar_item_' in leaf or '.mean_item_' in leaf for leaf in leaves):children.setdefault(key,sorted(leaves))
    bindings={key:next(iter(values)) for key,values in owners.items() if len(values)==1}
    from point_components import layers
    for layer in layers(figure):
        if layer['point_role']!='mean' and not any('.stem_' in key and layer['owner'] in members for key,members in groups.items()):continue
        matches=[]
        for key,members in groups.items():
            if key in children:continue
            if any(obj is layer['owner'] or isinstance(obj,LinePoint) and obj.line is layer['owner'] and obj.index in layer['indices'] for obj in members):matches.append(key)
        if len(matches)==1:bindings[layer['key']]=matches[0]
    for key,leaves in children.items():
        if len(leaves)==1:bindings[key]=leaves[0]
    return bindings,children


def normalize_movement(figure,styles):
    bindings,children=movement_bindings(figure)
    result={key:dict(spec) for key,spec in styles.items()}
    groups=component_groups(figure);aliases={}
    for key,spec in list(result.items()):
        target=bindings.get(key)
        if not target or target==key or key in children:continue
        primary=artist_key(figure,groups[target][0]) if groups.get(target) else None
        rank=0 if key==primary else 1 if '.points_mean_' in key else 2
        for field in ('dx','dy'):
            if field in spec:
                candidate=(rank,key,spec.pop(field));identity=(target,field)
                if identity not in aliases or candidate[:2]<aliases[identity][:2]:aliases[identity]=candidate
    for (target,field),(_rank,_key,value) in aliases.items():
        group=result.setdefault(target,{});group[field]=group.get(field,0)+value
    inherited={}
    # Prefer a bar's container over its separately drawn errorbar container.
    for key in sorted(children,key=lambda key:('.bars_' not in key,key)):
        for leaf in children[key]:
            for field in ('dx','dy'):
                if field in result.get(key,{}):inherited.setdefault((leaf,field),result[key][field])
    for (leaf,field),value in inherited.items():
        if (leaf,field) not in aliases:
            spec=result.setdefault(leaf,{});spec[field]=spec.get(field,0)+value
    for key in children:
        if key in result:
            for field in ('dx','dy'):result[key].pop(field,None)
    return {key:spec for key,spec in result.items() if spec}


def summary_vertex_links(figure):
    result={}
    for ai,axis in enumerate(figure.axes):
        for item in summary_items(axis):
            group=f'axes_{ai}.{item["name"]}'
            for member in item['members']:
                if not isinstance(member,LinePoint):continue
                key=artist_key(figure,member.line)
                vertices=result.setdefault(key,[[] for _ in member.line.get_xydata()])
                vertices[member.index].append(group)
    return result


def _orientation(original, axis, args, kwargs):
    import inspect
    bound = inspect.signature(original).bind(axis, *args, **kwargs)
    return 'y' if bound.arguments.get('orientation') == 'horizontal' or bound.arguments.get('vert') is False else 'x'


def _already_custom_grouped(axis, artist):
    return any(artist in members for members, _label in getattr(axis, '_component_custom_groups', []))


def _line_matches_fill(line, band, x, lower, upper):
    """Conservatively identify a center curve, not an area-fill boundary."""
    from matplotlib.colors import to_rgba
    try:
        lx=np.asarray(line.get_xdata(),dtype=float);y=np.asarray(line.get_ydata(),dtype=float)
        if lx.shape!=x.shape or y.shape!=lower.shape or not np.allclose(lx,x,equal_nan=True): return False
        tolerance=np.maximum(1,np.maximum(np.abs(lower),np.abs(upper)))*1e-10
        finite=np.isfinite(y)&np.isfinite(lower)&np.isfinite(upper)
        if not finite.any(): return False
        if not np.all((y[finite]>=lower[finite]-tolerance[finite])&(y[finite]<=upper[finite]+tolerance[finite])): return False
        strict=(y[finite]>lower[finite]+tolerance[finite])&(y[finite]<upper[finite]-tolerance[finite])
        if strict.mean()<.5: return False
        faces=band.get_facecolor()
        return bool(len(faces)) and np.allclose(to_rgba(line.get_color())[:3],faces[0][:3],atol=1/255)
    except (TypeError,ValueError):
        return False


def install_group_tracking():
    from matplotlib.axes import Axes
    if not getattr(Axes.errorbar,'_component_center_tracking',False):
        original_errorbar=Axes.errorbar
        @wraps(original_errorbar)
        def errorbar(axis,*args,**kwargs):
            result=original_errorbar(axis,*args,**kwargs)
            try:
                import inspect
                values=inspect.signature(original_errorbar).bind(axis,*args,**kwargs).arguments
                x,y=np.broadcast_arrays(np.asarray(axis.convert_xunits(values['x']),dtype=float),np.asarray(axis.convert_yunits(values['y']),dtype=float))
                result._component_centers=np.column_stack((x.ravel(),y.ravel()))
            except (KeyError,TypeError,ValueError):pass
            return result
        errorbar._component_center_tracking=True
        Axes.errorbar=errorbar
    for method in ('boxplot','violinplot'):
        original=getattr(Axes,method)
        if getattr(original,'_plot_forge_orientation_compat',False):continue
        @wraps(original)
        def compatible(axis,*args,__original=original,**kwargs):
            return __original(axis,*args,**compatible_orientation(__original,kwargs))
        compatible._plot_forge_orientation_compat=True
        setattr(Axes,method,compatible)
    # A paper curve and its fill_between uncertainty band are one semantic
    # series.  Matplotlib returns independent Line2D/PolyCollection artists,
    # so remember the call inputs and expose them as one editable component.
    if not getattr(Axes.fill_between,'_plot_forge_band_tracking',False):
        original_fill_between=Axes.fill_between
        @wraps(original_fill_between)
        def fill_between(axis,*args,**kwargs):
            result=original_fill_between(axis,*args,**kwargs)
            try:
                import inspect
                bound=inspect.signature(original_fill_between).bind(axis,*args,**kwargs)
                bound.apply_defaults()
                x=np.asarray(bound.arguments['x'],dtype=float)
                y1=np.broadcast_to(np.asarray(bound.arguments['y1'],dtype=float),x.shape)
                y2=np.broadcast_to(np.asarray(bound.arguments['y2'],dtype=float),x.shape)
                lower,upper=np.minimum(y1,y2),np.maximum(y1,y2)
                match=next((line for line in reversed(axis.lines)
                            if not _already_custom_grouped(axis,line)
                            and _line_matches_fill(line,result,x,lower,upper)),None)
                if match is not None:
                    register_component_group(axis,[result,match],'曲线与填充区域')
                else:
                    axis._plot_forge_pending_bands=getattr(axis,'_plot_forge_pending_bands',[])
                    axis._plot_forge_pending_bands.append((result,x,lower,upper))
            except (KeyError,TypeError,ValueError):
                pass
            return result
        fill_between._plot_forge_band_tracking=True
        Axes.fill_between=fill_between
    if not getattr(Axes.plot,'_plot_forge_band_tracking',False):
        original_plot=Axes.plot
        @wraps(original_plot)
        def plot(axis,*args,**kwargs):
            result=original_plot(axis,*args,**kwargs)
            pending=getattr(axis,'_plot_forge_pending_bands',[])
            if pending:
                for line in result:
                    for index,(band,bx,lower,upper) in reversed(list(enumerate(pending))):
                        if _already_custom_grouped(axis,line) or not _line_matches_fill(line,band,bx,lower,upper):continue
                        register_component_group(axis,[band,line],'曲线与填充区域')
                        pending.pop(index);break
            return result
        plot._plot_forge_band_tracking=True
        Axes.plot=plot
    if not getattr(Axes.bxp, '_component_tracking', False):
        original_bxp = Axes.bxp
        @wraps(original_bxp)
        def bxp(axis, *args, **kwargs):
            result = original_bxp(axis, *args, **kwargs)
            groups = getattr(axis, '_component_boxes', [])
            dimensions=getattr(axis,'_component_box_dimensions',[])
            import inspect
            bound=inspect.signature(original_bxp).bind(axis,*args,**kwargs)
            stats=bound.arguments.get('bxpstats',[])
            regions=getattr(axis,'_component_point_regions',[])
            for i, box in enumerate(result.get('boxes', [])):
                orientation=_orientation(original_bxp, axis, args, kwargs)
                dimensions.append(orientation)
                points=box.get_path().vertices if hasattr(box,'get_path') else np.column_stack(box.get_data())
                dimension=0 if orientation=='x' else 1
                regions.append({'dimension':1-dimension,'position':float((points[:,dimension].min()+points[:,dimension].max())/2),
                    'low':stats[i]['whislo'],'high':stats[i]['whishi'],'mean':stats[i].get('mean'), 'rule':'original_whiskers'})
                for name,role in (('means','mean'),('fliers','outliers')):
                    for obj in result.get(name,[])[i:i+1]:obj._component_point_role=role
                members = [box, *result.get('whiskers', [])[i*2:i*2+2],
                           *result.get('caps', [])[i*2:i*2+2],
                           *result.get('medians', [])[i:i+1],
                           *result.get('means', [])[i:i+1], *result.get('fliers', [])[i:i+1]]
                groups.append(members)
            axis._component_boxes = groups
            axis._component_box_dimensions=dimensions
            axis._component_point_regions=regions
            return result
        bxp._component_tracking = True
        Axes.bxp = bxp
    if not getattr(Axes.violin, '_component_tracking', False):
        original_violin = Axes.violin
        @wraps(original_violin)
        def violin(axis, *args, **kwargs):
            result = original_violin(axis, *args, **kwargs)
            groups = getattr(axis, '_component_violins', [])
            dimensions = getattr(axis, '_component_violin_dimensions', [])
            statistics = args[0] if args else kwargs['vpstats']
            quantile_index = 0
            for i, body in enumerate(result.get('bodies', [])):
                members = [body]
                for name, collection in result.items():
                    if name == 'bodies': continue
                    indexes = range(quantile_index, quantile_index+len(statistics[i].get('quantiles', []))) if name == 'cquantiles' else [i]
                    members.extend(CollectionSegment(collection, j) for j in indexes if j < len(collection.get_segments()))
                quantile_index += len(statistics[i].get('quantiles', []))
                groups.append(members)
                dimensions.append(_orientation(original_violin, axis, args, kwargs))
                orientation=dimensions[-1];coordinate=0 if orientation=='x' else 1
                vertices=body.get_paths()[0].vertices
                regions=getattr(axis,'_component_violin_point_regions',[])
                regions.append({'dimension':1-coordinate,'position':float((vertices[:,coordinate].min()+vertices[:,coordinate].max())/2),
                    'low':None,'high':None,'mean':statistics[i].get('mean'),'rule':'display_iqr'})
                axis._component_violin_point_regions=regions
            axis._component_violins = groups
            axis._component_violin_dimensions = dimensions
            return result
        violin._component_tracking = True
        Axes.violin = violin


def register_component_group(axis, members, label='自定义图形'):
    """Register explicit semantic membership for additional/custom plot types."""
    if not members or any(obj.axes is not axis for obj in members):
        raise ValueError('整体分组的组成部分必须属于同一个子图')
    groups = getattr(axis, '_component_custom_groups', [])
    groups.append((list(members), str(label)))
    axis._component_custom_groups = groups
    return f'axes_{axis.figure.axes.index(axis)}.group_{len(groups)-1}'


def summary_group_regions(axis):
    """Categorical anchors for means/error bars and bar containers."""
    from matplotlib.container import ErrorbarContainer, BarContainer,StemContainer
    result = {}
    bar_errors = {id(c.errorbar) for c in axis.containers if isinstance(c, BarContainer) and c.errorbar is not None}
    for i, container in enumerate(c for c in axis.containers if isinstance(c, ErrorbarContainer)):
        if id(container) in bar_errors: continue
        dimension = 0 if container.has_xerr and not container.has_yerr else 1
        line, _caps, bars = container.lines
        centers = _errorbar_centers(container)
        result[f'mean_error_{i}'] = [{'dimension':dimension,'position':float(p[1-dimension]),
            'mean':float(p[dimension]),'low':None,'high':None,'rule':'display_iqr'} for p in centers]
    for i, container in enumerate(c for c in axis.containers if isinstance(c, BarContainer)):
        horizontal = container.orientation == 'horizontal'
        result[f'bars_{i}'] = [{'dimension':0 if horizontal else 1,
            'position':float(p.get_y()+p.get_height()/2 if horizontal else p.get_x()+p.get_width()/2),
            'mean':float(p.get_x()+p.get_width() if horizontal else p.get_y()+p.get_height()),
            'low':None,'high':None,'rule':'display_iqr'} for p in container.patches]
    for item in summary_items(axis):result[item['name']]=[item['region']]
    for i,container in enumerate(c for c in axis.containers if isinstance(c,StemContainer)):
        marker,stems,_baseline=container.lines if hasattr(container,'lines') else tuple(container)
        segments=stems.get_segments() if hasattr(stems,'get_segments') else [stem.get_xydata() for stem in stems]
        dimension=next((int(np.argmax(np.ptp(segment,axis=0))) for segment in segments if len(segment) and np.any(np.ptp(segment,axis=0)>0)),1)
        result[f'stem_{i}']=[{'dimension':dimension,'position':float(p[1-dimension]),'mean':float(p[dimension]),'low':None,'high':None,'rule':'display_iqr'} for p in marker.get_xydata() if np.isfinite(p).all()]
    return result


def component_groups(figure):
    from matplotlib.container import ErrorbarContainer, BarContainer, StemContainer
    from matplotlib.collections import PathCollection
    groups = {}
    for ai, axis in enumerate(figure.axes):
        for i, members in enumerate(getattr(axis, '_component_boxes', [])):
            active=[obj for obj in members if artist_key(figure,obj) is not None]
            if active:groups[f'axes_{ai}.box_{i}'] = active
        for i, members in enumerate(getattr(axis, '_component_violins', [])):
            active=[obj for obj in members if artist_key(figure,obj) is not None]
            if active:groups[f'axes_{ai}.violin_{i}'] = active
        bar_errors = {id(c.errorbar) for c in axis.containers if isinstance(c, BarContainer) and c.errorbar is not None}
        for i, container in enumerate(c for c in axis.containers if isinstance(c, ErrorbarContainer)):
            if id(container) in bar_errors: continue
            line, caps, bars = container.lines
            if line is not None:line._component_point_role='mean'
            members = ([line] if line is not None else []) + list(caps) + list(bars)
            # Some scientific renderers draw mean markers using scatter separately.
            centers = []
            for bar in bars:
                centers.extend(np.mean(segment, axis=0) for segment in bar.get_segments() if len(segment))
            for obj in axis.collections:
                if not isinstance(obj, PathCollection) or getattr(obj,'_component_point_overlay',False): continue
                offsets = np.asarray(obj.get_offsets())
                if len(offsets) == 1 and any(np.allclose(offsets[0], center, rtol=1e-7, atol=1e-9) for center in centers):
                    obj._component_point_role='mean'
                    members.append(obj)
            groups[f'axes_{ai}.mean_error_{i}'] = list(dict.fromkeys(members))
        for i, container in enumerate(c for c in axis.containers if isinstance(c, BarContainer)):
            members = list(container.patches)
            if container.errorbar is not None:
                line, caps, bars = container.errorbar.lines
                members += ([line] if line is not None else []) + list(caps) + list(bars)
            groups[f'axes_{ai}.bars_{i}'] = members
        for i, container in enumerate(c for c in axis.containers if isinstance(c, StemContainer)):
            groups[f'axes_{ai}.stem_{i}'] = list(container)
        for i, (members, label) in enumerate(getattr(axis, '_component_custom_groups', [])):
            groups[f'axes_{ai}.group_{i}'] = members
        for item in summary_items(axis):groups[f'axes_{ai}.{item["name"]}']=item['members']
    return groups


def artist_key(figure, obj):
    if isinstance(obj,LinePoint):
        parent=artist_key(figure,obj.line)
        return f'{parent}.vertex_{obj.index}' if parent else None
    if isinstance(obj, CollectionSegment):
        parent = artist_key(figure, obj.collection)
        return f'{parent}.segment_{obj.index}' if parent else None
    for ai, axis in enumerate(figure.axes):
        for prefix, items in (('line', axis.lines), ('collection', axis.collections), ('patch', axis.patches)):
            for i, item in enumerate(items):
                if item is obj: return f'axes_{ai}.{prefix}_{i}'


def artist_points(obj, renderer):
    from matplotlib.collections import PathCollection, LineCollection
    if isinstance(obj, PathCollection):
        return np.asarray(obj.get_offset_transform().transform(obj.get_offsets()))
    if isinstance(obj, LineCollection):
        points = [artist_points(CollectionSegment(obj, i), renderer) for i in range(len(obj.get_segments()))]
        return np.concatenate(points) if points else np.empty((0, 2))
    if hasattr(obj, 'get_path'):
        return obj.get_transform().transform(obj.get_path().vertices)
    if hasattr(obj, 'get_paths'):
        paths = [path.vertices for path in obj.get_paths() if len(path.vertices)]
        return obj.get_transform().transform(np.concatenate(paths)) if paths else np.empty((0, 2))
    box = obj.get_window_extent(renderer)
    return np.array([[box.x0, box.y0], [box.x1, box.y1]])


def group_report(figure, records):
    result = []
    renderer = figure.canvas.get_renderer()
    for key, members in component_groups(figure).items():
        keys = [artist_key(figure, obj) for obj in members]
        paths, parts = [], []
        for obj in members:
            points = artist_points(obj, renderer)
            points = points[np.isfinite(points).all(axis=1)]
            if len(points):
                paths.append(points.tolist())
                member_key = artist_key(figure, obj)
                from matplotlib.collections import LineCollection, PolyCollection
                candidates = [CollectionSegment(obj, j) for j in range(len(obj.get_segments()))] if isinstance(obj, LineCollection) else [obj]
                for part in candidates:
                    part_key = artist_key(figure, part)
                    if not isinstance(part, CollectionSegment) and any(r['key'] == part_key and r.get('hit_path_px') for r in records): continue
                    if isinstance(part,LinePoint) and str(part.get_marker()).lower() not in ('_','|','none','',' '):continue
                    p = artist_points(part, renderer)
                    if not len(p) or not np.isfinite(p).all(): continue
                    if isinstance(part,LinePoint) and part.get_marker() in ('_','|'):
                        radius=part.get_markersize()*figure.dpi/144
                        vector=np.array([radius,0] if part.get_marker()=='_' else [0,radius])
                        p=np.array([p[0]-vector,p[0]+vector])
                    style = {}
                    for field in ('color', 'edgecolor', 'facecolor', 'linewidth'):
                        getter = getattr(part, 'get_'+field, None)
                        if getter is not None: style[field] = np.asarray(getter()).tolist()
                    parts.append({'key': part_key, 'group_key': key, 'kind': 'patch' if isinstance(part, PolyCollection) else 'line',
                                  'label': '小提琴主体' if isinstance(part, PolyCollection) else '统计图组成线条',
                                  'style': style, 'hit_path_px': p.tolist()})
        for record in records:
            if record['key'] in keys and not any(part in key for part in ('.bar_item_','.mean_item_')): record['group_key'] = key
        if paths:
            points = np.concatenate(paths)
            kind=key.split('.')[1].rsplit('_',1)[0]
            label={'box':'箱型图','violin':'小提琴图','mean_error':'均值与 error bar','bars':'柱形系列','bar_item':'柱形与误差棒','mean_item':'均值与误差棒','stem':'茎状图'}.get(kind)
            if kind=='group': label=figure.axes[int(key.split('.')[0][5:])]._component_custom_groups[int(key.rsplit('_',1)[1])][1]
            locked_selection=label=='曲线与填充区域'
            result.append({'key': key, 'kind': 'statistical_group', 'plot_type': kind, 'label': label,
                           'locked_selection': locked_selection,
                           'linked_properties': ['color'] if locked_selection else [],'movement_only':kind in ('bar_item','mean_item'),
                           'members': keys, 'part_targets': parts, 'hit_paths_px': paths,
                           'bbox': [*points.min(axis=0).tolist(), *points.max(axis=0).tolist()]})
    bindings,children=movement_bindings(figure)
    for record in records:
        if record['key'] in bindings:record['movement_group']=bindings[record['key']]
    for group in result:
        group['selection_children']=children.get(group['key'],[])
        for part in group['part_targets']:
            if part['key'] in bindings:part['movement_group']=bindings[part['key']]
    return result
