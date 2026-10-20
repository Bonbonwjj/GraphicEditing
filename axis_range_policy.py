"""Chart-local final display parameters, including equal linear numeric ticks."""
def apply_chart_parameters(fig, settings):
    from chart_overrides import apply_chart_parameters as apply_values
    apply_values(fig,settings)
    from chart_type_defaults import _profile
    import numpy as np
    for key in ('xlim','ylim'):
        if key not in settings:continue
        ax=fig.axes[0];axis=ax.xaxis if key=='xlim' else ax.yaxis
        if axis.get_scale()!='linear':continue
        converter=axis.get_converter() if hasattr(axis,'get_converter') else axis.converter
        if converter is not None:continue
        # get_ticklabels resolves the locator/formatter without another render.
        # Category/date/custom labels retain their semantics.
        labels=[t.get_text() for t in axis.get_ticklabels() if t.get_visible() and t.get_text()]
        try:
            for label in labels:float(label.replace('−','-'))
        except ValueError:continue
        lo,hi=map(float,settings[key])
        count=max(2,int(_profile()['global']['max_numeric_y_major_tick_labels']))
        axis.set_ticks(np.linspace(lo,hi,count).tolist())
        getattr(ax,'set_'+key)((lo,hi))
