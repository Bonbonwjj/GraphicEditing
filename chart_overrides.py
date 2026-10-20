"""Apply explicit chart-local display settings to an already created figure."""


def apply_chart_parameters(fig, settings):
    # This helper changes only this Figure's objects, never shared defaults.
    if len(fig.axes) != 1 or fig.axes[0].name != 'rectilinear':
        raise ValueError('单图参数路径需要唯一的普通坐标轴；多子图请指定目标后使用改图流程。')
    ax = fig.axes[0]
    for key, value in settings.items():
        if key == 'text_scale':
            from matplotlib.text import Text
            fig.canvas.draw()
            for text in fig.findobj(match=Text):
                if text.get_visible() and text.get_text():
                    text.set_fontsize(text.get_fontsize()*value)
        elif key in ('xlabel_scale','ylabel_scale'):
            text=ax.xaxis.label if key=='xlabel_scale' else ax.yaxis.label
            text.set_fontsize(text.get_fontsize()*value)
        elif key in ('spine_scale','xspine_scale','yspine_scale'):
            names=('bottom','top') if key=='xspine_scale' else ('left','right') if key=='yspine_scale' else tuple(ax.spines)
            for name in names:
                spine=ax.spines.get(name)
                if spine is not None and spine.get_visible():
                    spine.set_linewidth(spine.get_linewidth()*value)
        elif key == 'xlabel_fontsize':
            ax.xaxis.label.set_fontsize(value)
        elif key == 'ylabel_fontsize':
            ax.yaxis.label.set_fontsize(value)
        elif key == 'tick_fontsize':
            ax.tick_params(axis='both', labelsize=value)
        elif key == 'line_color':
            if len(ax.lines) != 1 or ax.containers or ax.collections:
                raise ValueError('折线颜色存在多个可能目标，请指定系列；未自动选择。')
            ax.lines[0].set_color(value)
        elif key == 'legend_loc':
            legend = ax.get_legend()
            if legend is None:
                raise ValueError('当前图没有图例，不能仅通过位置参数新增图例。')
            legend.set_loc(value)
        elif key == 'legend_fontsize':
            legend = ax.get_legend()
            if legend is None:
                raise ValueError('当前图没有图例，无法修改图例字号。')
            for text in legend.get_texts():
                text.set_fontsize(value)
        elif key in ('xlim', 'ylim'):
            getattr(ax, 'set_' + key)(value)
            spine=ax.spines.get('bottom' if key=='xlim' else 'left')
            if spine is not None:
                spine.set_bounds(*value)
        else:
            raise ValueError('未知的单图参数：' + key)
