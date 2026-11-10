"""Deterministic chart layers from observed plotting inputs, never inferred rows."""
import re

CATEGORY_MODES = ('boxplot', 'violinplot', 'scatter', 'mean_error', 'mean_line', 'mean_bar')
DENSITY_MODES = ('histogram_count', 'density_count', 'histogram', 'density')
DISTRIBUTION_MODES = CATEGORY_MODES + DENSITY_MODES
XY_MODES = ('line', 'scatter')
STAT_ROLES = {'boxes': 'edge', 'bodies': 'edge', 'medians': 'median', 'cmedians': 'median',
              'whiskers': 'whisker', 'caps': 'cap', 'fliers': 'flier'}
STAT_FIELDS = {role+suffix for role in set(STAT_ROLES.values()) for suffix in ('_color', '_alpha')}


def validate_palettes(value):
    import math
    if not isinstance(value, dict) or len(value) > 50:
        raise ValueError('组别配色配置无效')
    clean = {}
    for key, entries in value.items():
        if not isinstance(key, str) or not re.fullmatch(r'axes_\d+', key) or not isinstance(entries, list) or len(entries) > 2000:
            raise ValueError('组别配色目标无效')
        seen = set(); rows = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - ({'position', 'series_index', 'label', 'color'} | STAT_FIELDS):
                raise ValueError('组别配色记录无效')
            field = 'position' if 'position' in entry else 'series_index'
            number = entry.get(field)
            if ('position' in entry and 'series_index' in entry or isinstance(number, bool)
                    or not isinstance(number, (int, float)) or not math.isfinite(number)
                    or field == 'series_index' and (not isinstance(number, int) or number < 0)):
                raise ValueError('组别配色标识无效')
            if not isinstance(entry.get('label', ''), str) or len(entry.get('label', '')) > 500:
                raise ValueError('组名无效')
            if not isinstance(entry.get('color'), str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', entry['color']):
                raise ValueError('组别颜色须为 #RRGGBB')
            if (field, number) in seen:
                raise ValueError('组别配色标识重复')
            seen.add((field, number))
            row = {field: number, 'label': entry.get('label', ''), 'color': entry['color']}
            for name in STAT_FIELDS & entry.keys():
                item = entry[name]
                if name.endswith('_color'):
                    if not isinstance(item, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', item):
                        raise ValueError('统计线颜色无效')
                elif isinstance(item, bool) or not isinstance(item, (int, float)) or not 0 <= item <= 1:
                    raise ValueError('统计线不透明度无效')
                row[name] = item
            rows.append(row)
        clean[key] = rows
    return clean


def _rgb(artist):
    import numpy as np
    from matplotlib.colors import to_hex, to_rgba
    for getter in ('get_facecolor', 'get_color', 'get_edgecolor'):
        method = getattr(artist, getter, None)
        if method is None:
            continue
        try:
            color = method()
            if not isinstance(color, str):
                color = np.asarray(color)
                if not color.size: continue
                if color.ndim > 1: color = color[0]
            rgba = to_rgba(color)
            if rgba[3] > 0:
                return to_hex(rgba, keep_alpha=False)
        except (TypeError, ValueError):
            pass
    return None


def _group_palette(axis, groups):
    """Read the currently painted colors, matching groups by data position."""
    import numpy as np
    from component_groups import artist_points
    dimension, positions, values = groups
    category = axis.yaxis if dimension == 0 else axis.xaxis
    ticks = category.get_majorticklocs()
    texts = [text.get_text() for text in category.get_ticklabels()]
    labels = getattr(axis, '_plot_mode_original_labels', {}).get('groups')
    if labels is None:
        labels = [next((label for tick, label in zip(ticks, texts) if np.isclose(tick, p)), f'组 {i+1}')
                  for i, p in enumerate(positions)]
    colors = {}
    candidates = [*axis.patches, *axis.collections, *axis.lines]
    candidates.sort(key=lambda artist: 0 if getattr(artist, '_plot_mode_group_position', None) is not None
                    else 1 if getattr(artist, '_chat_semantic_data', {}).get('type') in ('box_statistics', 'violin_statistics') else 2)
    renderer = axis.figure.canvas.get_renderer()
    for artist in candidates:
        if not artist.get_visible(): continue
        color = _rgb(artist)
        if color is None: continue
        position = getattr(artist, '_plot_mode_group_position', None)
        if position is None:
            try:
                points = artist_points(artist, renderer)
                points = points[np.isfinite(points).all(axis=1)]
                points = axis.transData.inverted().transform(points)
                if not len(points): continue
                coordinates = points[:, 1-dimension]
                position = float((coordinates.min()+coordinates.max())/2)
            except (TypeError, ValueError, AttributeError):
                continue
        matched = next((p for p in positions if np.isclose(p, position, atol=1e-7, rtol=1e-7)), None)
        if matched is not None and matched not in colors:
            colors[matched] = color
    inherited = {entry['position']: entry['color'] for entry in getattr(axis, '_plot_mode_palette', []) if 'position' in entry}
    from matplotlib.colors import to_hex
    rows = [{'position': p, 'label': label,
             'color': colors.get(p, inherited.get(p, to_hex(f'C{i % 10}')))}
            for i, (p, label) in enumerate(zip(positions, labels))]
    statistics = _statistical_colors(axis, positions)
    for row in rows: row.update(statistics.get(row['position'], {}))
    return rows


def _statistical_colors(axis, positions):
    import numpy as np
    from matplotlib.colors import to_hex, to_rgba_array
    result = {row['position']: {k: v for k, v in row.items() if k in STAT_FIELDS}
              for row in getattr(axis, '_plot_mode_palette', []) if 'position' in row}
    for artist in [*axis.patches, *axis.collections, *axis.lines]:
        role = STAT_ROLES.get(getattr(artist, '_plot_mode_stat_role',
                                      getattr(artist, '_chat_semantic_data', {}).get('component')))
        group_positions = getattr(artist, '_plot_mode_group_positions', None)
        position = getattr(artist, '_plot_mode_group_position', None)
        if role is None or group_positions is None and position is None: continue
        getter = getattr(artist, 'get_edgecolor' if role == 'edge' else 'get_color', None)
        if getter is None: continue
        try: rgba = to_rgba_array(getter())
        except (ValueError, TypeError): continue
        if not len(rgba): continue
        alpha = artist.get_alpha()
        for index, p in enumerate(group_positions if group_positions is not None else [position]):
            if not any(np.isclose(p, target) for target in positions): continue
            color = rgba[index % len(rgba)]
            result.setdefault(p, {}).update({role+'_color': to_hex(color, keep_alpha=False),
                                             role+'_alpha': float(color[3] if alpha is None else alpha)})
    return result


def _stat_rgba(row, role, default='#000000'):
    from matplotlib.colors import to_rgba
    return to_rgba(row.get(role+'_color', default), row.get(role+'_alpha', 1))


def _series_palette(axis, series):
    result = []
    for index, item in enumerate(series):
        active = next((artist for artist in [*axis.lines, *axis.collections]
                       if getattr(artist, '_plot_mode_series_index', None) == index), item['artist'])
        from matplotlib.colors import to_hex
        result.append({'series_index': index, 'label': item['label'],
                       'color': _rgb(active) or to_hex(item['color'])})
    return result


def validate_modes(value):
    if not isinstance(value, dict) or len(value) > 50:
        raise ValueError('绘图类型配置无效')
    clean = {}
    for key, modes in value.items():
        if not isinstance(key, str) or not re.fullmatch(r'axes_\d+', key):
            raise ValueError('绘图类型的目标子图无效')
        if (not isinstance(modes, list) or not modes or len(modes) > 6
                or any(not isinstance(mode, str) or mode not in (*DISTRIBUTION_MODES, *XY_MODES) for mode in modes)
                or len(set(modes)) != len(modes)):
            raise ValueError('请选择至少一种有效图型，且不要重复选择')
        clean[key] = list(modes)
    return clean


def _groups(axis):
    import numpy as np
    records = getattr(axis, '_plot_mode_samples', [])
    if not records:
        return None
    groups = {}
    dimension = records[0]['dimension']
    for record in records:
        if dimension != record['dimension']:
            raise ValueError('此子图混合了不同方向的分布，无法自动组合')
        for position, values in zip(record['positions'], record['values']):
            values = np.asarray(values, dtype=float).reshape(-1)
            if not len(values) or not np.isfinite(values).all():
                raise ValueError('原始观测为空或含非有限值，请先检查数据')
            if position in groups and not np.array_equal(np.sort(groups[position]), np.sort(values)):
                raise ValueError('同一组位置存在多批不同数据，无法自动确定绘图样本')
            groups[position] = values.copy()
    if not groups:
        raise ValueError('未记录有效的原始观测组')
    return dimension, list(groups), list(groups.values())


def _xy(axis):
    import numpy as np
    from matplotlib.collections import PathCollection
    if hasattr(axis, '_plot_mode_xy'):
        return axis._plot_mode_xy
    series = []
    for artist in [*axis.lines, *axis.collections]:
        label = artist.get_label()
        if getattr(artist, '_chat_semantic_data', {}).get('type') in ('box_statistics', 'violin_statistics'):
            continue
        if not artist.get_visible():
            continue
        if artist.get_transform() != axis.transData:
            if not isinstance(artist, PathCollection) or artist.get_offset_transform() != axis.transData:
                continue
        if isinstance(artist, PathCollection):
            points = np.ma.asarray(artist.get_offsets())
            color = artist.get_facecolor()
            color = color[0] if len(color) else '#1f77b4'
        elif hasattr(artist, 'get_xydata'):
            points = np.ma.asarray(artist.get_xydata())
            color = artist.get_color()
        else:
            continue
        if np.ma.is_masked(points):
            continue
        points = np.asarray(points, dtype=float)
        if len(points) == 4 and points[0,0] == points[1,0] and points[2,0] == points[3,0] and points[1,1] == points[2,1]:
            continue  # Conventional significance bracket, not a data series.
        if len(points) and np.isfinite(points).all():
            display_label = label if isinstance(label, str) and not label.startswith('_') else '_nolegend_'
            series.append({'artist': artist, 'points': points.copy(), 'label': display_label, 'color': color})
    return series


def capabilities(figure):
    result = []
    for index, axis in enumerate(figure.axes):
        if axis.name != 'rectilinear' or not axis.axison:
            continue
        try:
            groups = _groups(axis)
            supported = list(DISTRIBUTION_MODES) if groups else (list(XY_MODES) if _xy(axis) else [])
            unavailable = {}
            if groups:
                import numpy as np
                if any(len(v)<2 or np.ptp(v)==0 for v in groups[2]):
                    for mode in ('violinplot', 'density', 'density_count'):
                        unavailable[mode] = '常量或单样本组无法估计密度'
                if any(len(v)<2 for v in groups[2]):
                    for mode in ('mean_error', 'mean_bar'):
                        unavailable[mode] = '计算 SEM 至少需要两个原始观测'
                if axis.texts or any(getattr(line, '_chat_semantic_data', {}).get('type') != 'box_statistics'
                                     and not getattr(line, '_plot_mode_generated', False) for line in axis.lines):
                    for mode in DENSITY_MODES:
                        unavailable[mode] = '此子图有配对线或统计标注，直接改为密度坐标会改变其含义'
                supported = [mode for mode in supported if mode not in unavailable]
            reason = '' if supported else '没有可核对的原始分组观测或带名称的数据系列'
        except ValueError as error:
            supported, reason, groups, unavailable = [], str(error), None, {}
        result.append({'key': f'axes_{index}', 'axis_label': axis.get_label(),
                       'label': axis.get_title() or axis.get_ylabel() or axis.get_xlabel() or f'子图 {index+1}',
                       'supported': supported, 'unavailable': unavailable, 'reason': reason,
                       'group_counts': [len(v) for v in groups[2]] if groups else [],
                       'palette': _group_palette(axis, groups) if groups else _series_palette(axis, _xy(axis)),
                       'selected': getattr(axis, '_plot_modes_selected',
                           [getattr(axis, '_plot_mode_samples', [{}])[-1].get('kind', 'boxplot')] if groups
                           else list(dict.fromkeys('scatter' if hasattr(item['artist'], 'get_offsets') else 'line' for item in _xy(axis))))})
    return result


def _remove(artist):
    if artist.axes is not None:
        artist.remove()


def _distribution_layers(axis, groups, modes, palette):
    import numpy as np
    from matplotlib.collections import PathCollection
    dimension, positions, values = groups
    horizontal = dimension == 0
    density_mode = any(mode in DENSITY_MODES for mode in modes)
    category_axis = axis.yaxis if dimension == 0 else axis.xaxis
    tick_positions = category_axis.get_majorticklocs()
    tick_labels = [text.get_text() for text in category_axis.get_ticklabels()]
    labels = [next((label for tick, label in zip(tick_positions, tick_labels) if np.isclose(tick, position)), f'组 {i+1}')
              for i, position in enumerate(positions)]
    if not hasattr(axis, '_plot_mode_original_labels'):
        axis._plot_mode_original_labels = {'xlabel': axis.get_xlabel(), 'ylabel': axis.get_ylabel(), 'groups': labels}
    original_labels = axis._plot_mode_original_labels
    labels = original_labels['groups']
    value_label = original_labels['xlabel'] if dimension == 0 else original_labels['ylabel']
    if not density_mode:
        axis.set_xlabel(original_labels['xlabel']); axis.set_ylabel(original_labels['ylabel'])
        (axis.set_yticks if horizontal else axis.set_xticks)(positions, labels)
    spacing = min(np.diff(sorted(positions))) if len(positions) > 1 else 1
    width = float(spacing) * .55
    by_position = {entry['position']: entry['color'] for entry in palette}
    style_by_position = {entry['position']: entry for entry in palette}
    colors = [by_position[position] for position in positions]
    axis._plot_mode_palette = palette
    # Remove distributions and observed sample scatter; preserve paired lines,
    # significance brackets, text and unrelated artists.
    for artist in list(axis.lines) + list(axis.patches) + list(axis.collections):
        statistical = getattr(artist, '_chat_semantic_data', {}).get('type') in ('box_statistics', 'violin_statistics')
        generated = getattr(artist, '_plot_mode_generated', False)
        sample = False
        if isinstance(artist, PathCollection) and artist.get_offset_transform() == axis.transData:
            points = np.asarray(artist.get_offsets())
            if len(points):
                for position, observations in zip(positions, values):
                    if (len(points) == len(observations)
                            and np.allclose(np.sort(points[:, dimension]), np.sort(observations))
                            and np.max(np.abs(points[:, 1-dimension] - position)) < spacing*.45):
                        sample = True
        if statistical or generated or sample:
            _remove(artist)
    for container in list(axis.containers):
        if getattr(container, '_plot_mode_generated', False):
            if container in axis.containers:
                axis.containers.remove(container)
    axis._component_boxes = []; axis._component_box_dimensions = []
    axis._component_violins = []; axis._component_violin_dimensions = []
    axis._component_point_regions = []; axis._component_violin_point_regions = []
    old_artists = set(axis.lines) | set(axis.patches) | set(axis.collections)
    old_containers = {id(container) for container in axis.containers}
    orientation = 'horizontal' if horizontal else 'vertical'
    axis._plot_mode_drawing = True
    try:
        if density_mode:
            from matplotlib.ticker import AutoLocator, ScalarFormatter
            axis.xaxis.set_major_locator(AutoLocator()); axis.xaxis.set_major_formatter(ScalarFormatter())
            axis.yaxis.set_major_locator(AutoLocator()); axis.yaxis.set_major_formatter(ScalarFormatter())
            count_mode = any(mode in ('histogram_count', 'density_count') for mode in modes)
            axis.set_xlabel(value_label or '观测值'); axis.set_ylabel('Count' if count_mode else 'Probability density')
            edges = np.histogram_bin_edges(np.concatenate(values), bins='auto')
            bin_width = float(edges[1] - edges[0])
            if 'density_count' in modes:
                axis.set_ylabel(f'Count per bin (width={bin_width:g})')
            elif count_mode:
                from matplotlib.ticker import MaxNLocator
                axis.yaxis.set_major_locator(MaxNLocator(integer=True))
            # Brackets/paired connectors use category coordinates and cannot
            # be interpreted on a density axis. Require a clean distribution.
            for artist in list(axis.lines):
                if getattr(artist, '_plot_mode_generated', False): _remove(artist)
            if 'histogram' in modes or 'histogram_count' in modes:
                for position, observations, color, label in zip(positions, values, colors, labels):
                    _, _, patches = axis.hist(observations, bins=edges, density=not count_mode, color=color, alpha=.35, label=label)
                    for patch in patches: patch._plot_mode_group_position = position
            if 'density' in modes or 'density_count' in modes:
                from scipy.stats import gaussian_kde
                all_values = np.concatenate(values)
                padding = max(float(np.ptp(all_values))*.15, .1)
                grid = np.linspace(float(all_values.min())-padding, float(all_values.max())+padding, 256)
                for position, observations, color, label in zip(positions, values, colors, labels):
                    # KDE integrates to one; N * bin width converts its height
                    # to the estimated number of observations per shared bin.
                    scale = len(observations) * bin_width if count_mode else 1
                    line, = axis.plot(grid, gaussian_kde(observations)(grid) * scale, color=color,
                                      label=label if 'histogram_count' not in modes and 'histogram' not in modes else '_nolegend_', linewidth=1.5)
                    line._plot_mode_group_position = position
            if len(values) > 1:
                axis.legend()
        if 'violinplot' in modes:
            violin = axis.violinplot(values, positions=positions, widths=width,
                                     orientation=orientation, showmedians=True, showextrema=False)
            for position, body, color in zip(positions, violin['bodies'], colors):
                from matplotlib.colors import to_rgba
                body.set_alpha(None); body.set_facecolor(to_rgba(color, .35))
                body.set_edgecolor(_stat_rgba(style_by_position[position], 'edge'))
                body._plot_mode_group_position = position
            violin['cmedians'].set_color([_stat_rgba(style_by_position[p], 'median') for p in positions])
        if 'mean_bar' in modes:
            means = [float(np.mean(v)) for v in values]
            sem = [float(np.std(v, ddof=1)/np.sqrt(len(v))) if len(v)>1 else 0 for v in values]
            if horizontal:
                bars = axis.barh(positions, means, height=width, xerr=sem, color=colors, alpha=.4, capsize=3)
            else:
                bars = axis.bar(positions, means, width=width, yerr=sem, color=colors, alpha=.4, capsize=3)
            for position, patch in zip(positions, bars.patches): patch._plot_mode_group_position = position
        if 'boxplot' in modes:
            boxes = axis.boxplot(values, positions=positions, widths=width*.65,
                                 orientation=orientation, patch_artist=True, manage_ticks=False,
                                 showfliers='scatter' not in modes)
            for position, patch, color in zip(positions, boxes['boxes'], colors):
                from matplotlib.colors import to_rgba
                patch.set_alpha(None); patch.set_facecolor(to_rgba(color, .45 if len(modes)>1 else .8))
                patch.set_edgecolor(_stat_rgba(style_by_position[position], 'edge'))
                patch._plot_mode_group_position = position
            for component in ('medians', 'whiskers', 'caps', 'fliers'):
                stride = 2 if component in ('whiskers', 'caps') else 1
                for index, line in enumerate(boxes[component]):
                    row = style_by_position[positions[index//stride]]
                    rgba = _stat_rgba(row, STAT_ROLES[component])
                    line.set_alpha(None); line.set_color(rgba); line.set_markeredgecolor(rgba)
        if 'scatter' in modes:
            for position, observations, color in zip(positions, values, colors):
                # Deterministic jitter, without touching the project's RNG state.
                offset = np.random.default_rng(0).uniform(-width*.25, width*.25, len(observations))
                category = position + offset
                x, y = (observations, category) if horizontal else (category, observations)
                scatter = axis.scatter(x, y, s=12, color=color, alpha=.65, zorder=3)
                scatter._plot_mode_group_position = position
                scatter._plot_mode_layer = 'scatter'
        if 'mean_line' in modes:
            means = [float(np.mean(v)) for v in values]
            x, y = (means, positions) if horizontal else (positions, means)
            from matplotlib.collections import LineCollection
            points = np.column_stack((x, y))
            segments, segment_colors = [], []
            for i in range(len(points)-1):
                middle = (points[i]+points[i+1])/2
                segments.extend(([points[i], middle], [middle, points[i+1]]))
                segment_colors.extend((colors[i], colors[i+1]))
            if segments: axis.add_collection(LineCollection(segments, colors=segment_colors, linewidths=1.5))
            for position, px, py, color in zip(positions, x, y, colors):
                marker = axis.scatter([px], [py], color=color, s=20, zorder=4)
                marker._plot_mode_group_position = position
                marker._component_point_role = 'mean'
        if 'mean_error' in modes:
            for position, observations, color in zip(positions, values, colors):
                mean = float(np.mean(observations))
                sem = float(np.std(observations, ddof=1)/np.sqrt(len(observations))) if len(observations)>1 else 0
                x, y = (mean, position) if horizontal else (position, mean)
                error = axis.errorbar(x, y, **({'xerr': sem} if horizontal else {'yerr': sem}),
                                     fmt='o', color=color, capsize=3, zorder=5)
                for artist in [error.lines[0], *error.lines[1], *error.lines[2]]:
                    artist._plot_mode_group_position = position
    finally:
        axis._plot_mode_drawing = False
    for artist in (set(axis.lines) | set(axis.patches) | set(axis.collections)) - old_artists:
        artist._plot_mode_generated = True
    for container in axis.containers:
        if id(container) not in old_containers:
            container._plot_mode_generated = True
    # Keep full raw observations inside the visible range, including outliers
    # omitted by the original boxplot. Collection-aware bounds survive relim().
    if density_mode:
        # Reset the inherited category data bounds for the new coordinate
        # interpretation. Histogram patches and density lines support relim.
        axis.relim(); axis.autoscale(enable=True)
        return
    points = np.concatenate([np.column_stack((v, np.full(len(v), p))) if horizontal
                             else np.column_stack((np.full(len(v), p), v))
                             for p, v in zip(positions, values)])
    axis.relim()
    for collection in axis.collections:
        bounds = collection.get_datalim(axis.transData).get_points()
        if np.isfinite(bounds).all(): axis.update_datalim(bounds)
    axis.update_datalim(points)


def apply_modes(figure, value, palettes=None):
    import numpy as np
    value = validate_modes(value)
    palettes = validate_palettes(palettes or {})
    plans = []
    for key, modes in value.items():
        index = int(key[5:])
        if index >= len(figure.axes):
            raise ValueError('目标子图已变化，请重新选择')
        axis = figure.axes[index]
        groups = _groups(axis)
        supported = DISTRIBUTION_MODES if groups else XY_MODES
        if any(mode not in supported for mode in modes):
            raise ValueError('当前数据不支持所选图型；分布图需要原始逐样本观测')
        if any(mode in DENSITY_MODES for mode in modes) and any(mode in CATEGORY_MODES for mode in modes):
            raise ValueError('直方图/密度曲线可相互叠加；不能与使用类别坐标的箱线图等叠加')
        if any(mode in ('histogram_count', 'density_count') for mode in modes) and any(mode in ('histogram', 'density') for mode in modes):
            raise ValueError('样本数与概率密度的纵轴单位不同，不能直接叠加；请选择同一种纵轴单位')
        if groups and any(mode in ('violinplot', 'density', 'density_count') for mode in modes) and any(len(v)<2 or np.ptp(v)==0 for v in groups[2]):
            raise ValueError('常量或单样本组无法估计密度，请改选箱线图、散点图或直方图')
        if groups and any(mode in DENSITY_MODES for mode in modes):
            if axis.texts or any(getattr(line, '_chat_semantic_data', {}).get('type') != 'box_statistics'
                                 and not getattr(line, '_plot_mode_generated', False) for line in axis.lines):
                raise ValueError('此子图含配对连线或统计标注，不能直接将类别坐标改为密度坐标；请先使用独立的分布子图')
        if groups and any(mode in ('mean_error', 'mean_bar') for mode in modes) and any(len(v)<2 for v in groups[2]):
            raise ValueError('计算 SEM 至少需要两个原始观测')
        series = [] if groups else _xy(axis)
        if not groups and not series:
            raise ValueError('未找到可核对的数据系列，不能从图片或汇总值反推原始样本')
        palette = _group_palette(axis, groups) if groups else _series_palette(axis, series)
        field = 'position' if groups else 'series_index'
        for entry in palette:
            match = next((saved for saved in palettes.get(key, [])
                          if saved.get(field) == entry[field] and saved.get('label', '') == entry['label']), None)
            if match:
                entry.update({name: value for name, value in match.items() if name == 'color' or name in STAT_FIELDS})
        plans.append((axis, modes, groups, series, palette))
    if plans:
        from component_editor import lock_range_layout
        lock_range_layout(figure)
    for axis, modes, groups, series, palette in plans:
        position = axis.get_position().frozen()
        axis.set_box_aspect(None); axis.set_aspect('auto'); axis.set_position(position)
        if groups:
            _distribution_layers(axis, groups, modes, palette)
        else:
            axis._plot_mode_xy = series
            for artist in list(axis.lines) + list(axis.collections):
                if getattr(artist, '_plot_mode_generated', False) or any(artist is s['artist'] for s in series):
                    _remove(artist)
            for index, item in enumerate(series):
                color = palette[index]['color']
                x, y = item['points'].T
                if 'line' in modes:
                    line, = axis.plot(x, y, color=color, label=item['label'])
                    line._plot_mode_generated = True
                    line._plot_mode_series_index = index
                if 'scatter' in modes:
                    points = axis.scatter(x, y, color=color, label=item['label'] if 'line' not in modes else '_nolegend_')
                    points._plot_mode_generated = True
                    points._plot_mode_series_index = index
        axis.autoscale(enable=True)
        for side in ('left', 'right'):
            axis.spines[side].set_bounds(*sorted(axis.get_ylim()))
        for side in ('bottom', 'top'):
            axis.spines[side].set_bounds(*sorted(axis.get_xlim()))
        axis._plot_modes_selected = list(modes)
