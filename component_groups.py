"""Group native statistical plot artists without rewriting their data."""
import numpy as np
from functools import wraps


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


def _orientation(original, axis, args, kwargs):
    import inspect
    bound = inspect.signature(original).bind(axis, *args, **kwargs)
    return 'y' if bound.arguments.get('orientation') == 'horizontal' or bound.arguments.get('vert') is False else 'x'


def install_group_tracking():
    from matplotlib.axes import Axes
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
    return groups


def artist_key(figure, obj):
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
                    p = artist_points(part, renderer)
                    if not len(p) or not np.isfinite(p).all(): continue
                    style = {}
                    for field in ('color', 'edgecolor', 'facecolor', 'linewidth'):
                        getter = getattr(part, 'get_'+field, None)
                        if getter is not None: style[field] = np.asarray(getter()).tolist()
                    parts.append({'key': part_key, 'group_key': key, 'kind': 'patch' if isinstance(part, PolyCollection) else 'line',
                                  'label': '小提琴主体' if isinstance(part, PolyCollection) else '统计图组成线条',
                                  'style': style, 'hit_path_px': p.tolist()})
        for record in records:
            if record['key'] in keys: record['group_key'] = key
        if paths:
            points = np.concatenate(paths)
            kind=key.split('.')[1].rsplit('_',1)[0]
            label={'box':'箱型图','violin':'小提琴图','mean_error':'均值与 error bar','bars':'柱形系列','stem':'茎状图'}.get(kind)
            if kind=='group': label=figure.axes[int(key.split('.')[0][5:])]._component_custom_groups[int(key.rsplit('_',1)[1])][1]
            result.append({'key': key, 'kind': 'statistical_group', 'plot_type': kind, 'label': label,
                           'members': keys, 'part_targets': parts, 'hit_paths_px': paths,
                           'bbox': [*points.min(axis=0).tolist(), *points.max(axis=0).tolist()]})
    return result
