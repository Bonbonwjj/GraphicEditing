"""Extract display names from a rendered figure, without changing the figure."""
import json
import math
import os
from pathlib import Path


class RenderedImage(bytes):
    naming = None


def clean(value):
    return ' '.join(str(value).split())


def figure_naming(fig):
    axes = [ax for ax in fig.axes if ax.get_visible() and not hasattr(ax, '_colorbar')]
    if len(axes) != 1 or axes[0].name != 'rectilinear':
        return {'status': 'fallback', 'reason': '多子图、双轴或非直角坐标图，保留原名'}
    ax = axes[0]
    ylabel, xlabel = clean(ax.get_ylabel()), clean(ax.get_xlabel())
    ticks = [clean(t.get_text()) for t in ax.get_xticklabels() if t.get_visible()]
    ticks = [t for t in ticks if t]
    # Matplotlib categorical units are unambiguous, including numeric-looking categories.
    categorical = hasattr(ax.xaxis.get_units(), '_mapping')
    def numeric(t):
        try:
            return math.isfinite(float(t.replace('−', '-')))
        except ValueError:
            return False
    groups = ticks if categorical or (ticks and not any(numeric(t) for t in ticks)) else []
    xpart = '&'.join(groups) if groups else xlabel
    if not ylabel or not xpart:
        return {'status': 'fallback', 'reason': '缺少可明确识别的轴标题或组别，保留原名'}
    return {'status': 'ready', 'display_name': xpart + '_' + ylabel,
            'x_groups': groups, 'x_label': xlabel, 'y_label': ylabel,
            'group_key': json.dumps(['categories', groups] if groups else ['continuous', xlabel], ensure_ascii=False)}


def install_capture(output, metadata, interaction_report=None):
    from matplotlib.axes import Axes
    from chat_runner import _install_stat_capture
    _install_stat_capture(Axes)
    from component_groups import install_group_tracking
    install_group_tracking()
    from matplotlib.figure import Figure
    # Preview workers export files and never open interactive figure windows.
    Figure.show = lambda self, *args, **kwargs: None
    original = Figure.savefig
    def savefig(fig, fname, *args, **kwargs):
        target = (isinstance(fname, (str, os.PathLike))
                  and Path(fname).resolve() == Path(output).resolve())
        if target:
            from component_editor import apply_axis_layout
            for axis in fig.axes: apply_axis_layout(axis)
        captured = []
        def capture_export(event):
            # Savefig's final draw uses the actual export DPI and tight crop.
            # Capturing here preserves both outlying labels and hit coordinates.
            try:
                from chat_runner import _capture
                captured[:] = [_capture(fig, event.renderer)]
            except Exception:
                captured.clear()
        callback = fig.canvas.mpl_connect('draw_event', capture_export) if target and interaction_report else None
        try:
            result = original(fig, fname, *args, **kwargs)
        finally:
            if callback is not None: fig.canvas.mpl_disconnect(callback)
        try:
            if target:
                Path(metadata).write_text(json.dumps(figure_naming(fig), ensure_ascii=False), encoding='utf-8', newline="\n")
                if interaction_report and captured:
                    report = captured[-1]
                    from PIL import Image
                    with Image.open(output) as exported:
                        report['render_size_px'] = list(exported.size)
                    Path(interaction_report).write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8', newline="\n")
        except Exception:
            Path(metadata).write_text('{"status":"fallback","reason":"无法读取轴信息"}', encoding='utf-8', newline="\n")
        return result
    Figure.savefig = savefig
