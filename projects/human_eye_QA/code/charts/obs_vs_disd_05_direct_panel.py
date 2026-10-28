import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ['CHART_PROJECT_DIR'])
panels = pd.read_csv(project / 'data' / 'direct_panel_metadata.csv')
values = pd.read_csv(project / 'data' / 'direct_panel_subject_values.csv')

panel = panels[panels.panel_id.eq('01_obs_vs_disd_05')].iloc[0]
panel_values = values[values.panel_id.eq(panel.panel_id)]

groups = list(dict.fromkeys(panel_values.group_label))
colors = {panel.left_label: panel.left_color, panel.right_label: panel.right_color}

def color_for(label):
    return colors.get(label, '#4477AA')

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

rng = np.random.default_rng(0)
positions = {label: i for i, label in enumerate(groups)}

datasets = []
for label in groups:
    datasets.append(panel_values.loc[panel_values.group_label.eq(label), 'value'].to_numpy(dtype=float))

vp = ax.violinplot(
    datasets,
    positions=[positions[label] for label in groups],
    widths=0.6,
    showextrema=False,
    showmedians=False,
)
for body, label in zip(vp['bodies'], groups):
    body.set_facecolor(color_for(label))
    body.set_edgecolor(color_for(label))
    body.set_alpha(0.35)
    body.set_zorder(1)

for label, vals in zip(groups, datasets):
    x0 = positions[label]
    # Jittered subject-level points
    jitter = rng.uniform(-0.08, 0.08, size=vals.size)
    ax.scatter(
        np.full(vals.size, x0) + jitter,
        vals,
        s=12,
        color=color_for(label),
        alpha=0.65,
        linewidths=0,
        zorder=3,
    )
    # Median marker
    ax.scatter([x0], [float(np.median(vals))], s=30, color=color_for(label), zorder=4)

# Significance annotation between the two groups
p_value = float(panel.p_value)
if p_value < 0.001:
    stars = '***'
elif p_value < 0.01:
    stars = '**'
elif p_value < 0.05:
    stars = '*'
else:
    stars = 'n.s.'

if len(groups) == 2:
    x1, x2 = positions[groups[0]], positions[groups[1]]
    y_vals = panel_values.value.to_numpy(dtype=float)
    y_min, y_max = float(np.min(y_vals)), float(np.max(y_vals))
    span = y_max - y_min if y_max > y_min else 1.0
    bar_y = y_max + 0.08 * span
    ax.plot([x1, x1, x2, x2], [bar_y, bar_y + 0.03 * span, bar_y + 0.03 * span, bar_y],
            color='0.2', linewidth=1.0, zorder=1)
    ax.text((x1 + x2) / 2, bar_y + 0.05 * span, stars,
            ha='center', va='bottom', fontsize=16, color='0.2')
    ax.set_ylim(y_min - 0.08 * span, y_max + 0.22 * span)

ax.set_xticks([positions[label] for label in groups])
ax.set_xticklabels(groups)
ax.set_ylabel(panel.ylabel)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

ax.set_position([.34, .23, .60, .66])
finish_figure(fig, os.environ['CHART_OUTPUT'])
