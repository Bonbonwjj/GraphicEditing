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
    from matplotlib.figure import Figure
    # Preview workers export files and never open interactive figure windows.
    Figure.show = lambda self, *args, **kwargs: None
    original = Figure.savefig
    def savefig(fig, fname, *args, **kwargs):
        if (interaction_report and isinstance(fname, (str, os.PathLike))
                and Path(fname).resolve() == Path(output).resolve()):
            # Keep the complete canvas aligned with component hit coordinates.
            kwargs.pop('bbox_inches', None)
        result = original(fig, fname, *args, **kwargs)
        try:
            if isinstance(fname, (str, os.PathLike)) and Path(fname).resolve() == Path(output).resolve():
                Path(metadata).write_text(json.dumps(figure_naming(fig), ensure_ascii=False), encoding='utf-8', newline="\n")
                if interaction_report:
                    # Capture hit-test geometry while the figure still exists;
                    # many chart helpers close it immediately after savefig.
                    from chat_runner import _capture
                    fig.canvas.draw()
                    report = _capture(fig, fig.canvas.get_renderer())
                    Path(interaction_report).write_text(
                        json.dumps(report, ensure_ascii=False), encoding='utf-8', newline="\n")
        except Exception:
            # Naming must never prevent a successful figure export.
            Path(metadata).write_text('{"status":"fallback","reason":"无法读取轴信息"}', encoding='utf-8', newline="\n")
        return result
    Figure.savefig = savefig
