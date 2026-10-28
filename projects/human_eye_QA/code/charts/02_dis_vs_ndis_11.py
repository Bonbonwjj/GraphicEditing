import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from studio_style import apply_style, finish_figure

project = Path(os.environ['CHART_PROJECT_DIR'])
panels = pd.read_csv(project / 'data' / 'direct_panel_metadata.csv')
values = pd.read_csv(project / 'data' / 'direct_panel_subject_values.csv')

panel = panels[panels.panel_id.eq('02_dis_vs_ndis_11')].iloc[0]
panel_values = values[values.panel_id.eq(panel.panel_id)]

left_label = panel['left_label']
right_label = panel['right_label']
left_color = panel['left_color']
right_color = panel['right_color']

apply_style()

fig, ax = plt.subplots(figsize=(5.4, 4.8))

left_vals = panel_values[panel_values.group_label.eq(left_label)]
right_vals = panel_values[panel_values.group_label.eq(right_label)]

left_map = dict(zip(left_vals.subject_id, left_vals.value))
right_map = dict(zip(right_vals.subject_id, right_vals.value))

x_left, x_right = 0.0, 1.0

# Connect paired subjects where a subject has values in both groups
paired = sorted(set(left_map) & set(right_map))
for sid in paired:
    ax.plot([x_left, x_right], [left_map[sid], right_map[sid]],
            color='0.75', linewidth=0.8, zorder=1)

# Individual subject points
jitter = 0.04
for i, sid in enumerate(sorted(left_map)):
    dx = jitter * ((i % 5) - 2) / 2.0
    ax.scatter(x_left + dx, left_map[sid], s=14, color=left_color,
               edgecolor='white', linewidth=0.4, zorder=3)
for i, sid in enumerate(sorted(right_map)):
    dx = jitter * ((i % 5) - 2) / 2.0
    ax.scatter(x_right + dx, right_map[sid], s=14, color=right_color,
               edgecolor='white', linewidth=0.4, zorder=3)

# Group means
left_mean = left_vals.value.mean()
right_mean = right_vals.value.mean()
ax.scatter([x_left], [left_mean], s=55, marker='D', color=left_color,
           edgecolor='black', linewidth=0.6, zorder=4)
ax.scatter([x_right], [right_mean], s=55, marker='D', color=right_color,
           edgecolor='black', linewidth=0.6, zorder=4)

# Significance annotation
p_value = panel['p_value']
ax.text(0.5, 1.02, f'p = {p_value:.3g}', transform=ax.transAxes,
        ha='center', va='bottom', fontsize=8)

ax.set_xticks([x_left, x_right])
ax.set_xticklabels([left_label, right_label])
ax.set_xlim(-0.5, 1.5)
ax.set_title(panel['title'], fontsize=9)
ax.set_ylabel(panel['ylabel'], fontsize=8)

ax.set_position([.34, .23, .60, .66])
finish_figure(fig, os.environ['CHART_OUTPUT'])
