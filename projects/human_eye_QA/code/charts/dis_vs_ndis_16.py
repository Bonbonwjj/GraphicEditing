import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from studio_style import apply_style, finish_figure

apply_style()

project = Path(os.environ['CHART_PROJECT_DIR'])
panels = pd.read_csv(project / 'data' / 'direct_panel_metadata.csv')
values = pd.read_csv(project / 'data' / 'direct_panel_subject_values.csv')

panel = panels[panels.panel_id.eq('02_dis_vs_ndis_16')].iloc[0]
panel_values = values[values.panel_id.eq(panel.panel_id)]

# Preserve the group order defined by the metadata (left, then right)
group_order = [panel['left_label'], panel['right_label']]
colors = {panel['left_label']: panel['left_color'],
          panel['right_label']: panel['right_color']}

fig, ax = plt.subplots(figsize=(5.4, 4.8))

x_positions = {label: i for i, label in enumerate(group_order)}

# Connect paired subjects across groups
subjects = sorted(panel_values.subject_id.unique())
for sid in subjects:
    rows = panel_values[panel_values.subject_id.eq(sid)]
    if len(rows) == len(group_order):
        xs = [x_positions[g] for g in group_order]
        ys = [rows[rows.group_label.eq(g)].value.iloc[0] for g in group_order]
        ax.plot(xs, ys, color='0.75', linewidth=0.8, zorder=1)

# Subject-level points
rng = np.random.default_rng(0)
for label in group_order:
    gvals = panel_values[panel_values.group_label.eq(label)].value.values
    x = x_positions[label]
    jitter = rng.uniform(-0.06, 0.06, size=len(gvals))
    ax.scatter(np.full(len(gvals), x) + jitter, gvals, s=14,
               color=colors[label], edgecolor='none', zorder=2)
    # Group mean +/- SEM
    mean = float(np.mean(gvals))
    sem = float(np.std(gvals, ddof=1) / np.sqrt(len(gvals))) if len(gvals) > 1 else 0.0
    ax.errorbar(x, mean, yerr=sem, fmt='o', markersize=5,
                color=colors[label], ecolor=colors[label],
                elinewidth=1.2, capsize=3, zorder=3)

# Significance annotation
p_value = panel['p_value']
if pd.notna(p_value):
    y_max = panel_values.value.max()
    y_min = panel_values.value.min()
    span = y_max - y_min if y_max > y_min else 1.0
    y_bar = y_max + 0.12 * span
    ax.plot([0, 0, 1, 1], [y_bar - 0.03 * span, y_bar, y_bar, y_bar - 0.03 * span],
            color='0.2', linewidth=0.8)
    if p_value < 0.001:
        star_text = '***'
    elif p_value < 0.01:
        star_text = '**'
    elif p_value < 0.05:
        star_text = '*'
    else:
        star_text = 'n.s.'
    ax.text(0.5, y_bar + 0.02 * span, star_text, ha='center', va='bottom', fontsize=8)
    ax.set_ylim(top=y_bar + 0.10 * span)

ax.set_xticks(range(len(group_order)))
ax.set_xticklabels(group_order)
ax.set_xlim(-0.5, len(group_order) - 0.5)
ax.set_ylabel(panel['ylabel'])
ax.set_title(panel['title'])

ax.set_position([.34, .23, .60, .66])
finish_figure(fig, os.environ['CHART_OUTPUT'])
